"""End-to-end pipeline: data -> exposure -> hazard (proxy + ML) -> vulnerability -> loss.

Run as ``python -m src.pipeline`` or call :func:`run_pipeline` from the notebook.
Every artefact the agent layer needs is written to ``outputs/`` by
:func:`write_outputs`.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from . import config, data, exposure as expo, hazard, risk, explain, vulnerability

RISK_PREDICTION_COLUMNS = [
    "building_id", "latitude", "longitude", "housing_class", "scenario",
    "return_period_years", "exceedance_probability", "exposure_kes",
    "flood_probability", "hazard_source", "proxy_susceptibility",
    "ml_hotspot_likelihood", "ml_likelihood_std", "augmented_susceptibility",
    "hazard_severity", "flood_depth_m", "vulnerability_class_cap",
    "damage_ratio", "expected_loss_kes", "baseline_loss_kes", "risk_score",
    "risk_class", "confidence", "is_synthetic",
]


def run_pipeline(data_dir: Path = config.DATA_DIR, n_boot: int = 100,
                 n_repeats: int = 10, seed: int = config.RANDOM_SEED, verbose: bool = True) -> dict:
    """Execute the full model and return a dictionary of in-memory results."""
    t0 = time.time()
    log = (lambda *a: print(*a)) if verbose else (lambda *a: None)
    np.random.seed(seed)

    # ---- 1. data ---------------------------------------------------------- #
    raw = data.load_exposure(data_dir / config.EXPOSURE_WITH_HAZARD_FILE.name)
    hotspots = data.load_hotspots(data_dir / config.HOTSPOTS_FILE.name)
    rasters = data.load_hazard_rasters(data_dir)
    log(f"[data] {len(raw)} buildings, {len(hotspots)} hotspots, {len(rasters)} rasters")

    # ---- 2. exposure ------------------------------------------------------ #
    exposure = expo.build_exposure(raw, rasters)
    thresholds = hazard.infer_tier_thresholds(exposure)
    scenarios = hazard.scenario_table(thresholds)
    log(f"[hazard] inferred tier thresholds: { {k: round(v, 4) for k, v in thresholds.items()} }")

    # ---- 3. hazard features and ML hotspot model -------------------------- #
    fr = hazard.build_feature_rasters(rasters["common"])
    X, y, meta = hazard.build_training_set(hotspots, exposure, fr)
    X_hot = X[y == 1].reset_index(drop=True)
    X_bld = hazard.location_features(fr, exposure["latitude"], exposure["longitude"])
    log(f"[ml] training set: {int(y.sum())} hotspots vs {int((y == 0).sum())} background buildings, "
        f"{X.shape[1]} features")

    models = hazard.candidate_models(seed)
    cv = hazard.cross_validate_models(X, y, models, n_repeats=n_repeats, seed=seed)
    # Variant: add raw coordinates. Reported for transparency only - with 24
    # positives a coordinate model memorises *where* known hotspots are, which
    # the deterministic hotspot-proximity layer already encodes honestly.
    X_ll = X.assign(latitude=meta["latitude"].values, longitude=meta["longitude"].values)
    cv_ll = hazard.cross_validate_models(X_ll, y, models, n_repeats=n_repeats, seed=seed)
    cv_ll = cv_ll.loc[list(models)].rename(index=lambda n: f"{n}+latlon")
    cv = pd.concat([cv, cv_ll])
    chosen = hazard.select_model(cv)
    log(f"[ml] cross-validation done; selected model: {chosen}")
    model = models[chosen].fit(X, y)
    loo_p = hazard.leave_one_out_probabilities(models[chosen], X, y)
    boot = hazard.bootstrap_predictions(models[chosen], X, y, X_bld, n_boot=n_boot, seed=seed)
    p_bld, p_bld_std = model.predict_proba(X_bld)[:, 1], boot.std(axis=0)

    # hotspot-level validation table (baseline vs ML, each hotspot predicted out-of-sample)
    hot_val = pd.DataFrame({
        "hotspot": hotspots["name"], "latitude": hotspots["lat"], "longitude": hotspots["lon"],
        "proxy_score_at_point": X_hot["s_point"].values,
        "proxy_max_500m": X_hot["s_max_500"].values,
        "baseline_flagged": hazard.baseline_point_flag(X_hot),
        "ml_likelihood_loo": loo_p[y == 1],
    })
    hot_val["ml_flagged"] = hot_val["ml_likelihood_loo"] >= config.ML_FLAG_THRESHOLD
    bg_loo = loo_p[y == 0]
    hotspot_metrics = {
        "baseline_recall": float(hot_val["baseline_flagged"].mean()),
        "baseline_false_positive_rate": float((X[y == 0]["s_point"] > 0).mean()),
        "ml_recall_loo": float(hot_val["ml_flagged"].mean()),
        "ml_false_positive_rate_loo": float((bg_loo >= config.ML_FLAG_THRESHOLD).mean()),
        "ml_roc_auc_loo": float(hazard.roc_auc_score(y, loo_p)),
        "ml_average_precision_loo": float(hazard.average_precision_score(y, loo_p)),
        "baseline_roc_auc_point_score": float(hazard.roc_auc_score(y, X["s_point"])),
        "baseline_roc_auc_max_500m": float(hazard.roc_auc_score(y, X["s_max_500"])),
        "ml_recall_at_baseline_fpr_loo": hazard.recall_at_matched_fpr(
            y, loo_p, float((X[y == 0]["s_point"] > 0).mean()))[0],
        "max500_recall_at_baseline_fpr": hazard.recall_at_matched_fpr(
            y, X["s_max_500"].values, float((X[y == 0]["s_point"] > 0).mean()))[0],
        "ml_recall_at_10pct_fpr_loo": hazard.recall_at_matched_fpr(y, loo_p, 0.10)[0],
        "max500_recall_at_10pct_fpr": hazard.recall_at_matched_fpr(y, X["s_max_500"].values, 0.10)[0],
        "hotspots_recovered_by_ml_missed_by_baseline": hot_val.loc[
            hot_val["ml_flagged"] & ~hot_val["baseline_flagged"], "hotspot"].tolist(),
        "hotspots_lost_by_ml_flagged_by_baseline": hot_val.loc[
            ~hot_val["ml_flagged"] & hot_val["baseline_flagged"], "hotspot"].tolist(),
        "hotspots_missed_by_both": hot_val.loc[
            ~hot_val["ml_flagged"] & ~hot_val["baseline_flagged"], "hotspot"].tolist(),
    }
    log(f"[ml] hotspot recall baseline {hotspot_metrics['baseline_recall']:.2f} -> "
        f"ML (LOO) {hotspot_metrics['ml_recall_loo']:.2f}; FPR baseline "
        f"{hotspot_metrics['baseline_false_positive_rate']:.2f} -> ML {hotspot_metrics['ml_false_positive_rate_loo']:.2f}")

    # ---- 4. hazard augmentation ------------------------------------------ #
    d_hot, idx_hot = data.nearest_point_distance(exposure["latitude"], exposure["longitude"],
                                                 hotspots["lat"], hotspots["lon"])
    kernel = hazard.hotspot_proximity_kernel(d_hot)
    s_ref = hazard.hotspot_reference_susceptibility(X_hot)
    s_proxy = exposure[config.HAZARD_COLUMNS["common"]].values
    s_hot, _ = hazard.augment_susceptibility(s_proxy, p_bld, kernel, s_ref, use_ml=False)
    s_aug, source = hazard.augment_susceptibility(s_proxy, p_bld, kernel, s_ref)
    log(f"[hazard] S_ref={s_ref:.3f}; buildings with hazard: proxy {int((s_proxy > 0).sum())} -> "
        f"+known hotspots {int((s_hot > 0).sum())} -> +ML {int((s_aug > 0).sum())}")

    # ---- 5. financial engine (baseline proxy vs ML-augmented) ------------- #
    long_base = risk.scenario_losses(exposure, s_proxy, scenarios)
    long_hot = risk.scenario_losses(exposure, s_hot, scenarios)
    long_aug = risk.scenario_losses(exposure, s_aug, scenarios)
    ep_base, ep_hot, ep_aug = risk.ep_curve(long_base), risk.ep_curve(long_hot), risk.ep_curve(long_aug)
    # naive file-name mapping, shown in the notebook as the rejected alternative
    ep_naive = risk.ep_curve(risk.scenario_losses(exposure, s_proxy, hazard.scenario_table(thresholds, "naive")))
    summary = risk.rank_buildings(risk.building_summary(exposure, long_aug))
    base_summary = risk.building_summary(exposure, long_base)[["building_id", "expected_annual_loss_kes"]]
    summary = summary.merge(base_summary.rename(columns={"expected_annual_loss_kes": "baseline_expected_annual_loss_kes"}),
                            on="building_id")

    # hazard columns onto the summary (aligned by building id)
    haz = pd.DataFrame({
        "building_id": exposure["building_id"], "proxy_susceptibility": s_proxy,
        "ml_hotspot_likelihood": p_bld, "ml_likelihood_std": p_bld_std,
        "hotspot_proximity": kernel, "nearest_hotspot": hotspots["name"].values[idx_hot],
        "nearest_hotspot_distance_m": d_hot, "augmented_susceptibility": s_aug, "hazard_source": source,
    })
    summary = summary.merge(haz, on="building_id")
    summary["confidence"] = risk.confidence_label(summary["proxy_susceptibility"], summary["ml_hotspot_likelihood"],
                                                  summary["ml_likelihood_std"], summary["hazard_source"],
                                                  summary["nearest_hotspot_distance_m"])

    # ---- 6. explainability ----------------------------------------------- #
    importance = explain.feature_importance(model, X, y, seed)
    X_bld_aligned = X_bld.set_index(exposure["building_id"]).loc[summary["building_id"]].reset_index(drop=True)
    shap_bld = explain.shap_values(model, X, X_bld_aligned)
    summary["ml_risk_drivers"] = explain.top_drivers(shap_bld, X_bld_aligned)
    summary["loss_drivers"] = explain.loss_drivers(summary)

    # vulnerability matrix at a fixed "typical exposed building": the median augmented
    # susceptibility among buildings with any hazard, pushed through each scenario.
    s_typical = float(np.median(s_aug[s_aug > 0]))
    rep_depth = {row.scenario: float(hazard.depth_from_susceptibility(s_typical, row.susceptibility_threshold))
                 for row in scenarios.itertuples()}
    vmatrix = vulnerability.vulnerability_matrix(rep_depth)

    # ---- 7. agent-facing long table --------------------------------------- #
    predictions = _build_predictions(exposure, summary, long_aug, long_base)

    log(f"[done] {time.time() - t0:.1f}s; portfolio AAL baseline KES {risk.ep_aal(ep_base):,.0f} -> "
        f"augmented KES {risk.ep_aal(ep_aug):,.0f}")
    return {
        "exposure": exposure, "hotspots": hotspots, "rasters": rasters, "thresholds": thresholds,
        "scenarios": scenarios, "feature_rasters": fr, "X": X, "y": y, "meta": meta, "X_buildings": X_bld,
        "cv_results": cv, "chosen_model": chosen, "model": model, "loo_probabilities": loo_p,
        "bootstrap": boot, "hotspot_validation": hot_val, "hotspot_metrics": hotspot_metrics,
        "s_reference": s_ref, "long_baseline": long_base, "long_augmented": long_aug,
        "ep_baseline": ep_base, "ep_hotspots": ep_hot, "ep_augmented": ep_aug, "ep_naive_mapping": ep_naive,
        "long_hotspots": long_hot, "summary": summary,
        "loss_by_class": risk.loss_by_housing_class(exposure, long_aug),
        "loss_by_class_baseline": risk.loss_by_housing_class(exposure, long_base),
        "importance": importance, "shap_buildings": shap_bld, "X_buildings_aligned": X_bld_aligned,
        "vulnerability_matrix": vmatrix, "representative_depths": rep_depth, "s_typical": s_typical,
        "predictions": predictions,
    }


def _build_predictions(exposure, summary, long_aug, long_base) -> pd.DataFrame:
    """Long, agent-friendly table: one row per building x scenario."""
    cols = ["building_id", "latitude", "longitude", "housing_class", "tiv_kes", "annual_flood_probability",
            "hazard_source", "proxy_susceptibility", "ml_hotspot_likelihood", "ml_likelihood_std",
            "augmented_susceptibility", "risk_score", "risk_class", "confidence"]
    base = long_base[["building_id", "scenario", "loss_kes"]].rename(columns={"loss_kes": "baseline_loss_kes"})
    df = (long_aug.merge(base, on=["building_id", "scenario"])
                  .merge(summary[cols], on="building_id"))
    df["exposure_kes"] = df["tiv_kes"]
    df["flood_probability"] = df["annual_flood_probability"]
    df["expected_loss_kes"] = df["loss_kes"]
    df["vulnerability_class_cap"] = df["housing_class"].map(
        {k: v["max_damage_ratio"] for k, v in config.HOUSING_CLASS_VULNERABILITY.items()})
    df["is_synthetic"] = True
    return df.sort_values(["return_period_years", "expected_loss_kes"], ascending=[True, False])[RISK_PREDICTION_COLUMNS].reset_index(drop=True)


def write_outputs(res: dict, out_dir: Path = config.OUTPUT_DIR) -> list[Path]:
    """Persist every agent-consumable artefact. Returns the written paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "models").mkdir(exist_ok=True)
    written = []

    def save(df: pd.DataFrame, name: str, **kw):
        p = out_dir / name
        df.to_csv(p, index=kw.pop("index", False), **kw)
        written.append(p)

    save(res["predictions"], "risk_predictions.csv")
    save(res["summary"], "building_risk_summary.csv")
    ep = res["ep_baseline"].rename(columns={"portfolio_loss_kes": "baseline_proxy_loss_kes",
                                            "buildings_flooded": "baseline_buildings_flooded",
                                            "mean_damage_ratio_flooded": "baseline_mean_damage_ratio"})
    ep = ep.merge(res["ep_hotspots"][["scenario", "portfolio_loss_kes", "buildings_flooded"]].rename(
        columns={"portfolio_loss_kes": "proxy_plus_hotspots_loss_kes",
                 "buildings_flooded": "proxy_plus_hotspots_buildings_flooded"}), on="scenario")
    ep = ep.merge(res["ep_augmented"].rename(columns={"portfolio_loss_kes": "ml_augmented_loss_kes",
                                                      "buildings_flooded": "ml_augmented_buildings_flooded",
                                                      "mean_damage_ratio_flooded": "ml_augmented_mean_damage_ratio"}),
                  on=["scenario", "return_period_years", "exceedance_probability"])
    save(ep, "ep_curve.csv")
    save(res["loss_by_class"], "loss_by_housing_class.csv")
    save(res["loss_by_class_baseline"], "loss_by_housing_class_baseline.csv")
    save(res["hotspot_validation"], "hotspot_validation.csv")
    save(res["cv_results"].reset_index(), "model_cv_results.csv")
    save(res["importance"], "feature_importance.csv")
    save(res["vulnerability_matrix"].reset_index(), "vulnerability_matrix.csv")
    save(vulnerability.vulnerability_curves(), "vulnerability_curves.csv")
    save(res["scenarios"], "scenarios.csv")
    save(res["ep_naive_mapping"], "ep_curve_rejected_naive_mapping.csv")

    total_tiv = expo.total_exposure(res["exposure"])
    portfolio = {
        "total_exposure_kes": total_tiv,
        "n_buildings": int(len(res["exposure"])),
        "portfolio_aal_kes": {"baseline_proxy": risk.ep_aal(res["ep_baseline"]),
                              "proxy_plus_hotspots": risk.ep_aal(res["ep_hotspots"]),
                              "ml_augmented": risk.ep_aal(res["ep_augmented"])},
        "loss_by_return_period_kes": {
            row.scenario: {"return_period_years": int(row.return_period_years),
                           "baseline_proxy": float(row.baseline_proxy_loss_kes),
                           "proxy_plus_hotspots": float(row.proxy_plus_hotspots_loss_kes),
                           "ml_augmented": float(row.ml_augmented_loss_kes)}
            for row in ep.itertuples()},
        "buildings_with_hazard": {"baseline_proxy": int((res["summary"]["proxy_susceptibility"] > 0).sum()),
                                  "ml_augmented": int((res["summary"]["augmented_susceptibility"] > 0).sum())},
        "hazard_source_counts": res["summary"]["hazard_source"].value_counts().to_dict(),
        "confidence_counts": res["summary"]["confidence"].value_counts().to_dict(),
    }
    metrics = {
        "selected_model": res["chosen_model"],
        "model_selection_rule": "highest mean average precision in 5-fold x 20-repeat stratified CV; "
                                "ties within one standard error resolved toward the simpler model",
        "cross_validation": json.loads(res["cv_results"].to_json(orient="index")),
        "hotspot_level": res["hotspot_metrics"],
        "training_set": {"positives": int(res["y"].sum()), "background": int((res["y"] == 0).sum()),
                         "features": list(res["X"].columns)},
        "s_hotspot_reference": res["s_reference"],
        "tier_thresholds": res["thresholds"],
        "representative_depths_m": res["representative_depths"],
        "typical_exposed_building_susceptibility": res["s_typical"],
    }
    for name, obj in [("portfolio_summary.json", portfolio), ("model_metrics.json", metrics),
                      ("assumptions.json", config.assumptions_as_dict())]:
        p = out_dir / name
        p.write_text(json.dumps(obj, indent=2, default=_json_default))
        written.append(p)

    mp = out_dir / "models" / "hotspot_model.joblib"
    joblib.dump({"model": res["model"], "features": list(res["X"].columns), "name": res["chosen_model"],
                 "s_reference": res["s_reference"], "thresholds": res["thresholds"]}, mp)
    written.append(mp)
    return written


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.bool_,)):
        return bool(o)
    raise TypeError(f"not serialisable: {type(o)}")


def main() -> None:
    res = run_pipeline()
    paths = write_outputs(res)
    print("written:")
    for p in paths:
        print("  ", p.relative_to(config.PROJECT_ROOT))


if __name__ == "__main__":
    main()
