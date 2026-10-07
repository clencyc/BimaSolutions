"""Exposure stage: what is at risk and what it is worth.

The challenge document asks for "a structured portfolio containing the
buildings/assets you want to model, their characteristics, their values, and
the information needed to connect them to the hazard and vulnerability
stages".  :func:`build_exposure` produces exactly that.  Insured value is
taken from ``tiv_kes`` (total insured value in Kenyan shillings) as supplied
in the synthetic portfolio; no values are invented.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config
from .data import Raster

EXPOSURE_OUTPUT_COLUMNS = [
    "building_id", "latitude", "longitude", "housing_class",
    "floor_area_m2", "cost_per_m2_kes", "tiv_kes", "is_synthetic", "source",
]


def build_exposure(portfolio: pd.DataFrame,
                   rasters: dict[str, Raster] | None = None) -> pd.DataFrame:
    """Validate and standardise the exposure portfolio.

    Parameters
    ----------
    portfolio
        Raw starter-kit portfolio (``exposure_nairobi_*.csv``).
    rasters
        Optional dict of hazard rasters.  When given, hazard scores are looked
        up for every building (needed if the portfolio has no hazard columns).

    Returns
    -------
    DataFrame with one row per building, standard column names, the insured
    value ``tiv_kes`` and the five ``hazard_score_<tier>`` columns.
    """
    df = portfolio.copy()
    unknown = set(df["housing_class"]) - set(config.HOUSING_CLASSES)
    if unknown:
        raise ValueError(f"Unknown housing classes without vulnerability parameters: {unknown}")
    if (df["tiv_kes"] <= 0).any():
        raise ValueError("tiv_kes must be positive")

    out = pd.DataFrame({
        "building_id": df["loc_id"].astype(str),
        "latitude": df["lat"].astype(float),
        "longitude": df["lon"].astype(float),
        "housing_class": df["housing_class"].astype(str),
        "floor_area_m2": df["floor_area_m2"].astype(float),
        "cost_per_m2_kes": df["cost_per_m2_kes"].astype(float),
        "tiv_kes": df["tiv_kes"].astype(float),
        "is_synthetic": df["synthetic"].astype(bool),
        "source": df["source"].astype(str),
    })

    hazard_cols = list(config.HAZARD_COLUMNS.values())
    if all(c in df.columns for c in hazard_cols):
        for c in hazard_cols:
            out[c] = df[c].astype(float).values
    elif rasters is not None:
        out = attach_hazard_scores(out, rasters)
    else:
        raise ValueError("Portfolio has no hazard columns and no rasters were supplied")

    for c in hazard_cols:
        if out[c].isna().any():
            raise ValueError(f"Missing hazard scores in {c}; buildings may fall outside the raster")
    return out.reset_index(drop=True)


def attach_hazard_scores(exposure: pd.DataFrame, rasters: dict[str, Raster]) -> pd.DataFrame:
    """Look up the five tier scores for each building from the rasters."""
    out = exposure.copy()
    for tier, col in config.HAZARD_COLUMNS.items():
        out[col] = rasters[tier].sample(out["latitude"].values, out["longitude"].values)
    return out


def exposure_summary(exposure: pd.DataFrame) -> pd.DataFrame:
    """Total insured value, count and share by housing class."""
    g = exposure.groupby("housing_class").agg(
        buildings=("building_id", "count"),
        total_tiv_kes=("tiv_kes", "sum"),
        mean_tiv_kes=("tiv_kes", "mean"),
        mean_floor_area_m2=("floor_area_m2", "mean"),
    )
    g["share_of_tiv"] = g["total_tiv_kes"] / g["total_tiv_kes"].sum()
    return g.sort_values("total_tiv_kes", ascending=False)


def total_exposure(exposure: pd.DataFrame) -> float:
    """Portfolio total insured value in KES."""
    return float(np.sum(exposure["tiv_kes"].values))
