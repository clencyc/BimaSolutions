"""Commercial pricing helpers for the model API.

This module keeps the pricing logic explicit and shareable. It converts the
technical model output (AAL, risk class, confidence, TIV) into a commercial
quote with transparent loadings, deductible, and limit suggestions.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PricingAssumptions:
    expense_loading: float = 0.10
    commission_loading: float = 0.10
    profit_loading: float = 0.08
    reinsurance_loading: float = 0.06
    minimum_premium_kes: float = 250_000.0
    deductible_floor_kes: float = 250_000.0

    risk_margin_by_class: dict[str, float] | None = None
    deductible_pct_by_class: dict[str, float] | None = None
    limit_pct_by_class: dict[str, float] | None = None

    def resolved(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "risk_margin_by_class": self.risk_margin_by_class or {
                "negligible": 0.05,
                "low": 0.08,
                "medium": 0.15,
                "high": 0.25,
                "very_high": 0.40,
            },
            "deductible_pct_by_class": self.deductible_pct_by_class or {
                "negligible": 0.005,
                "low": 0.01,
                "medium": 0.02,
                "high": 0.05,
                "very_high": 0.075,
            },
            "limit_pct_by_class": self.limit_pct_by_class or {
                "negligible": 1.00,
                "low": 0.95,
                "medium": 0.90,
                "high": 0.80,
                "very_high": 0.70,
            },
        }


DEFAULT_ASSUMPTIONS = PricingAssumptions()


def pricing_formula() -> str:
    return (
        "gross_premium = max(minimum_premium, AAL × (1 + risk_margin + "
        "expense_loading + commission_loading + profit_loading + "
        "reinsurance_loading))"
    )


def _lookup(table: dict[str, float], key: str, default: float) -> float:
    return float(table.get(str(key), default))


def commercial_quote(row: pd.Series | dict[str, Any], assumptions: PricingAssumptions | None = None) -> dict[str, Any]:
    """Return a transparent commercial quote for one modeled building."""
    assumptions = assumptions or DEFAULT_ASSUMPTIONS
    cfg = assumptions.resolved()
    r = row if isinstance(row, dict) else row.to_dict()

    tiv = float(r.get("tiv_kes", r.get("exposure_kes", 0.0)))
    aal = float(r.get("expected_annual_loss_kes", 0.0))
    risk_class = str(r.get("risk_class", "medium"))
    confidence = str(r.get("confidence", "medium"))

    confidence_loading = {"high": 0.00, "medium": 0.03, "low": 0.05}.get(confidence, 0.03)
    risk_margin = _lookup(cfg["risk_margin_by_class"], risk_class, cfg["risk_margin_by_class"]["medium"])
    adjusted_risk_margin = risk_margin + confidence_loading

    expense_loading = float(cfg["expense_loading"])
    commission_loading = float(cfg["commission_loading"])
    profit_loading = float(cfg["profit_loading"])
    reinsurance_loading = float(cfg["reinsurance_loading"])

    total_loading = adjusted_risk_margin + expense_loading + commission_loading + profit_loading + reinsurance_loading
    technical_premium = aal
    loading_premium = aal * total_loading
    gross_premium = max(float(cfg["minimum_premium_kes"]), technical_premium + loading_premium)
    quoted_rate_pct_tiv = gross_premium / tiv if tiv > 0 else np.nan

    deductible_pct = _lookup(cfg["deductible_pct_by_class"], risk_class, cfg["deductible_pct_by_class"]["medium"])
    limit_pct = _lookup(cfg["limit_pct_by_class"], risk_class, cfg["limit_pct_by_class"]["medium"])
    deductible = max(float(cfg["deductible_floor_kes"]), tiv * deductible_pct)
    limit = tiv * limit_pct

    return {
        "tiv_kes": tiv,
        "expected_annual_loss_kes": aal,
        "risk_class": risk_class,
        "confidence": confidence,
        "technical_premium_kes": technical_premium,
        "risk_margin_rate": adjusted_risk_margin,
        "expense_loading_rate": expense_loading,
        "commission_loading_rate": commission_loading,
        "profit_loading_rate": profit_loading,
        "reinsurance_loading_rate": reinsurance_loading,
        "loading_premium_kes": loading_premium,
        "gross_premium_kes": gross_premium,
        "quoted_rate_pct_tiv": quoted_rate_pct_tiv,
        "deductible_kes": deductible,
        "suggested_limit_kes": limit,
        "formula": pricing_formula(),
        "assumptions": cfg,
    }


def quote_table(df: pd.DataFrame, assumptions: PricingAssumptions | None = None) -> pd.DataFrame:
    rows = []
    for _, row in df.iterrows():
        quote = commercial_quote(row, assumptions)
        quote["building_id"] = row.get("building_id")
        rows.append(quote)
    return pd.DataFrame(rows)
