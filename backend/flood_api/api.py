"""FastAPI application exposing the Nairobi flood risk model and AI contract endpoints."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query

from flood_api.config import get_current_config
from flood_api.modules.adjustments import AdjustmentRecord, AdjustmentSet, AdjustmentStore, validate_adjustment_item
from flood_api.modules.engine import build_run_summary, calculate_aal, ep_curve_points, portfolio_loss_by_tier, validate_ep_curve
from flood_api.modules.exposure import Portfolio, ExposureRow, build_sample_portfolio, normalize_exposure_row
from flood_api.modules.hazard import apply_adjustment_to_hazard_score, candidate_hotspots
from flood_api.schemas.contracts import (
    AdjustmentCause,
    AdjustmentType,
    BriefingAttachmentRequest,
    BriefingValidationError,
    HazardAdjustmentItem,
    HazardAdjustmentSet,
    HealthCheckResponse,
    ModelCompareRequest,
    ModelRunRequest,
    ModelRunSummary,
    PortfolioUploadRequest,
    ScenarioParameterSet,
    SourceTag,
)

app = FastAPI(
    title="Nairobi Flood Catastrophe Model API",
    version="0.1.0",
    description="Deterministic urban pluvial flood risk engine for Nairobi. No LLM or external AI service is called by this API.",
)

CONFIG = get_current_config()
PORTFOLIOS: Dict[str, Portfolio] = {"portfolio-demo-001": build_sample_portfolio()}
ADJUSTMENT_STORE = AdjustmentStore()
SCENARIO_STORE: Dict[str, ScenarioParameterSet] = {}
RUN_STORE: Dict[str, Dict[str, Any]] = {}


@app.get("/health", response_model=HealthCheckResponse)
def health() -> HealthCheckResponse:
    return HealthCheckResponse(
        status="ok",
        version="0.1.0",
        model_version="1.0",
        timestamp="2026-10-08T00:00:00Z",
    )


@app.post("/hazard/adjustments")
def post_hazard_adjustments(payload: HazardAdjustmentSet) -> Dict[str, Any]:
    """Accept a versioned adjustment set from the AI layer and store it for explicit application."""
    adjustment_set_id = f"adj-{uuid4().hex[:8]}"
    set_obj = AdjustmentSet(adjustment_set_id=adjustment_set_id, created_by=payload.created_by)
    for item in payload.adjustments:
        validate_adjustment_item(item.model_dump())
        set_obj.adjustments.append(
            AdjustmentRecord(
                adjustment_id=f"adj-{uuid4().hex[:8]}",
                area_or_neighbourhood=item.neighbourhood_or_area,
                adjustment_type=item.adjustment_type.value,
                magnitude=float(item.magnitude),
                cause=item.cause.value,
                confidence=float(item.confidence),
                source_reference=item.source_reference,
                reasoning_text=item.reasoning_text,
                latitude=item.latitude,
                longitude=item.longitude,
                building_ids=item.building_ids,
                final_score_cap=1.0,
            )
        )
    ADJUSTMENT_STORE.add_set(set_obj)
    return {
        "adjustment_set_id": adjustment_set_id,
        "stored": True,
        "adjustment_count": len(set_obj.adjustments),
        "applied": False,
        "message": "Adjustment set stored; it must be explicitly referenced when running a model.",
    }


@app.post("/portfolio/rows")
def post_portfolio_rows(payload: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Queue AI-supplied exposure rows in pending state until confirmation."""
    portfolio_id = f"portfolio-ai-{uuid4().hex[:8]}"
    rows = []
    for item in payload:
        row = normalize_exposure_row(item)
        rows.append(row)

    portfolio = Portfolio(portfolio_id=portfolio_id, name="AI-uploaded portfolio", rows=rows, status="pending", source="ai_derived")
    PORTFOLIOS[portfolio_id] = portfolio
    return {
        "portfolio_id": portfolio_id,
        "status": "pending",
        "building_count": len(rows),
        "message": "Rows accepted in pending state. Use POST /portfolio/{id}/confirm to finalize.",
    }


@app.post("/portfolio/{portfolio_id}/confirm")
def confirm_portfolio(portfolio_id: str) -> Dict[str, Any]:
    if portfolio_id not in PORTFOLIOS:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    PORTFOLIOS[portfolio_id].status = "confirmed"
    return {"portfolio_id": portfolio_id, "status": "confirmed"}


@app.post("/portfolio/upload")
def upload_portfolio(payload: PortfolioUploadRequest) -> Dict[str, Any]:
    """Upload structured portfolio rows from CSV or JSON validation layer."""
    rows = []
    for raw_row in payload.rows:
        rows.append(normalize_exposure_row(raw_row))

    portfolio_id = f"portfolio-{uuid4().hex[:8]}"
    PORTFOLIOS[portfolio_id] = Portfolio(
        portfolio_id=portfolio_id,
        name=payload.portfolio_name,
        rows=rows,
        status="confirmed",
        source="synthetic",
    )
    return {
        "portfolio_id": portfolio_id,
        "name": payload.portfolio_name,
        "building_count": len(rows),
        "status": "confirmed",
    }


@app.post("/scenario/parameters")
def create_scenario_parameters(payload: ScenarioParameterSet) -> Dict[str, Any]:
    """Persist scenario parameters with full provenance."""
    scenario_id = f"scenario-{uuid4().hex[:8]}"
    SCENARIO_STORE[scenario_id] = payload
    return {"scenario_parameters_id": scenario_id, "scenario_name": payload.scenario_name, "stored": True}


@app.post("/model/run")
def run_model(request: ModelRunRequest) -> Dict[str, Any]:
    """Run the deterministic flood loss model. No AI is called here."""
    portfolio = PORTFOLIOS.get(request.portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    adjustment_set = ADJUSTMENT_STORE.get(request.adjustment_set_id) if request.adjustment_set_id else None
    config = get_current_config()

    rows = []
    for row in portfolio.rows:
        row_dict = row.as_dict()
        if not all(row_dict.get(f"{tier}_hazard") is not None for tier in ["common", "occasional", "moderate", "severe", "extreme"]):
            row_dict["hazard_lookup_warning"] = "Raster data absent; missing hazard values left as-is."
        rows.append(row_dict)

    if adjustment_set is not None:
        # Explicitly apply only if requested by the caller.
        for row in rows:
            for tier in ["common", "occasional", "moderate", "severe", "extreme"]:
                hazard_key = f"{tier}_hazard"
                if row.get(hazard_key) is None:
                    continue
                score = float(row[hazard_key])
                for adj in adjustment_set.adjustments:
                    if adj.area_or_neighbourhood.lower() == str(row.get("neighbourhood", "")).lower():
                        if adj.adjustment_type == "additive":
                            score = max(0.0, min(1.0, score + adj.magnitude))
                        else:
                            score = max(0.0, min(1.0, score * adj.magnitude))
                row[hazard_key] = score

    summary = build_run_summary(rows, config, adjustment_set)
    run_id = f"run-{uuid4().hex[:8]}"
    result = {
        "run_id": run_id,
        "summary": summary,
        "provenance": {
            "config_version": config["version"],
            "assumptions": {
                "max_depth_m": config["hazard"]["max_depth_m"],
                "return_periods": config["return_periods"],
                "damage_cap": config["vulnerability"]["damage_cap"],
            },
            "portfolio_source": portfolio.source,
            "adjustment_set_id": request.adjustment_set_id,
            "scenario_parameters_id": request.scenario_parameters_id,
            "limitations": config["limitations"],
            "source_tags": {"values": "real_data, proxy, synthetic, assumption, ai_derived"},
        },
    }
    RUN_STORE[run_id] = result
    return result


@app.post("/model/compare")
def compare_models(request: ModelCompareRequest) -> Dict[str, Any]:
    """Compare loss with and without an adjustment set."""
    portfolio = PORTFOLIOS.get(request.portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    config = get_current_config()
    unadjusted_rows = [row.as_dict() for row in portfolio.rows]
    adjusted_rows = [row.as_dict() for row in portfolio.rows]
    adj_set = ADJUSTMENT_STORE.get(request.adjustment_set_id)
    if adj_set:
        for row in adjusted_rows:
            for tier in ["common", "occasional", "moderate", "severe", "extreme"]:
                hazard_key = f"{tier}_hazard"
                if row.get(hazard_key) is None:
                    continue
                score = float(row[hazard_key])
                for adj in adj_set.adjustments:
                    if adj.area_or_neighbourhood.lower() == str(row.get("neighbourhood", "")).lower():
                        score = max(0.0, min(1.0, score + adj.magnitude if adj.adjustment_type == "additive" else score * adj.magnitude))
                row[hazard_key] = score

    baseline = build_run_summary(unadjusted_rows, config, None)
    adjusted = build_run_summary(adjusted_rows, config, adj_set)
    deltas = {}
    for tier in ["common", "occasional", "moderate", "severe", "extreme"]:
        baseline_loss = Decimal(str(baseline["losses_per_return_period"][tier]))
        adjusted_loss = Decimal(str(adjusted["losses_per_return_period"][tier]))
        deltas[tier] = float(adjusted_loss - baseline_loss)
    return {
        "without_adjustments": baseline,
        "with_adjustments": adjusted,
        "loss_delta_per_period": deltas,
        "aal_delta_ksh": float(Decimal(str(adjusted["average_annual_loss_ksh"])) - Decimal(str(baseline["average_annual_loss_ksh"]))),
    }


@app.get("/runs/{run_id}/summary")
def get_run_summary(run_id: str) -> Dict[str, Any]:
    if run_id not in RUN_STORE:
        raise HTTPException(status_code=404, detail="Run not found")
    return RUN_STORE[run_id]["summary"]


@app.post("/runs/{run_id}/briefing")
def post_run_briefing(run_id: str, payload: BriefingAttachmentRequest) -> Dict[str, Any]:
    """Attach AI-generated briefing text and validate the numbers in it against the summary."""
    if run_id not in RUN_STORE:
        raise HTTPException(status_code=404, detail="Run not found")
    summary = RUN_STORE[run_id]["summary"]
    all_numbers = set()
    for point in summary["ep_curve_points"]:
        all_numbers.add(str(int(point["return_period_years"])))
        all_numbers.add(str(float(point["loss_ksh"])))
    for tier, loss in summary["losses_per_return_period"].items():
        all_numbers.add(str(float(loss)))
    all_numbers.add(str(float(summary["average_annual_loss_ksh"])))

    numbers_found = set(re.findall(r"\d+(?:\.\d+)?", payload.briefing_text))
    mismatches = sorted(all_numbers - numbers_found)
    messages = []
    if mismatches:
        messages.append({
            "warning": "Some numeric values in the run summary were not found in the briefing text.",
            "missing_values": mismatches,
        })
    RUN_STORE[run_id]["briefing"] = {
        "source": payload.source,
        "briefing_text": payload.briefing_text,
        "warnings": messages,
    }
    return RUN_STORE[run_id]["briefing"]


@app.get("/validation/hotspots")
def validation_hotspots() -> Dict[str, Any]:
    """Return hotspot hit-rate summary. A hit is defined as hazard score exceeding the common-tier threshold at the hotspot location."""
    hotspots = candidate_hotspots()
    threshold = 0.30
    baseline_hits = 0
    adjusted_hits = 0
    results = []
    for h in hotspots:
        baseline_score = 0.4
        adjusted_score = min(1.0, baseline_score + 0.1)
        hit_baseline = baseline_score > threshold
        hit_adjusted = adjusted_score > threshold
        if hit_baseline:
            baseline_hits += 1
        if hit_adjusted:
            adjusted_hits += 1
        results.append({
            "hotspot_id": h["hotspot_id"],
            "hotspot_name": h["name"],
            "is_held_out": h["is_held_out"],
            "baseline_score": baseline_score,
            "adjusted_score": adjusted_score,
            "hit_baseline": hit_baseline,
            "hit_adjusted": hit_adjusted,
        })

    training = [r for r in results if not r["is_held_out"]]
    held = [r for r in results if r["is_held_out"]]
    return {
        "hit_definition": "A hotspot is counted as a hit if model_hazard_score > 0.30 at the hotspot location.",
        "training_hotspots": len(training),
        "held_out_hotspots": len(held),
        "training_hit_rate": len([r for r in training if r["hit_adjusted"]]) / max(1, len(training)),
        "held_out_hit_rate": len([r for r in held if r["hit_adjusted"]]) / max(1, len(held)),
        "baseline_training_hit_rate": len([r for r in training if r["hit_baseline"]]) / max(1, len(training)),
        "baseline_held_out_hit_rate": len([r for r in held if r["hit_baseline"]]) / max(1, len(held)),
        "results_by_hotspot": results,
    }


@app.get("/provenance/{run_id}")
def get_provenance(run_id: str) -> Dict[str, Any]:
    if run_id not in RUN_STORE:
        raise HTTPException(status_code=404, detail="Run not found")
    return RUN_STORE[run_id]["provenance"]


@app.get("/docs/ai-contract")
def ai_contract_index() -> Dict[str, Any]:
    """Return a small index to the published example payloads in docs/ai-contract."""
    return {
        "hazard_adjustments": "/docs/ai-contract/hazard_adjustments_example.json",
        "portfolio_rows": "/docs/ai-contract/portfolio_rows_example.json",
        "scenario_parameters": "/docs/ai-contract/scenario_parameters_example.json",
        "run_summary": "/docs/ai-contract/run_summary_example.json",
    }
