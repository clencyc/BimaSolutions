"""Generate notebooks/flood_risk_model.ipynb from code. Run: python scripts/build_notebook.py"""
from pathlib import Path
import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]
cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip()))
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip()))

md("""
# Nairobi urban flood risk model (Team A, ML component)

Chain: **Hazard → Vulnerability → Exposure → Financial engine → EP curve**, plus an ML hotspot layer that
changes the hazard. Model logic lives in `src/`; this notebook runs it and shows the results.

> Exposure is **synthetic** and hazard is a **terrain proxy**. No number below is an observed loss.
> Assumptions: `src/config.py` and `outputs/assumptions.json`.

**Key assumptions** – the five rasters are nested views of one surface S, so the smallest footprint
(*extreme*) is the most frequent scenario (RP5) and the largest (*common*) is RP250; depth = 4 m × max(0, S − t);
vulnerability = JRC Africa residential curve adapted per housing class.
""")

md("## 1. Setup and run")
code("""
import sys, json, warnings
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib.pyplot as plt

ROOT = Path.cwd().resolve()
while not (ROOT / "src").exists():
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT)); warnings.filterwarnings("ignore")
pd.set_option("display.width", 160); pd.set_option("display.max_columns", 40); pd.set_option("display.float_format", "{:,.4g}".format)

from src import config, hazard, risk, vulnerability, plots, pipeline
plots.style()
res = pipeline.run_pipeline()          # loads Dataset/, trains, validates, computes losses (~2 min, seeded)
exposure, summary, hotspots = res["exposure"], res["summary"], res["hotspots"]
""")

md("## 2. Exposure and hotspot baseline")
code("""
from src import exposure as expo
display(expo.exposure_summary(exposure))
hv = res["hotspot_validation"]
print(f"Baseline rule (proxy at point > 0) flags {hv.baseline_flagged.sum()} of {len(hv)} known hotspots")
r = res["rasters"]["common"]; extent = (r.x_origin, r.x_origin + r.shape[1]*r.x_res, r.y_origin - r.shape[0]*r.y_res, r.y_origin)
plots.hotspot_map(r.values, extent, exposure, hotspots, hv);
""")

md("""
## 3. Vulnerability
`damage_ratio = min(cap, JRC(depth × multiplier))` per housing class.
""")
code("""
display(pd.DataFrame(config.HOUSING_CLASS_VULNERABILITY).T)
plots.vulnerability_curves(vulnerability.vulnerability_curves());
display(res["vulnerability_matrix"].round(3))
""")

md("""
## 4. Hotspot model validation
24 positives, so: 5-fold stratified CV repeated 10×, leave-one-out scoring of every hotspot, and two baselines
(point rule; max within 500 m). Raw-coordinate variants are shown only to document why they were rejected
(they memorise where known hotspots are).
""")
code("""
cv = res["cv_results"]; hm = res["hotspot_metrics"]
print("selected model:", res["chosen_model"])
display(cv[[c for c in cv.columns if c.endswith("_mean")]].round(3))
plots.cv_comparison(cv);
plots.baseline_vs_ml_hotspots(hv);
for k in ["hotspots_recovered_by_ml_missed_by_baseline", "hotspots_lost_by_ml_flagged_by_baseline", "hotspots_missed_by_both"]:
    print(f"{k}: {hm[k]}")
""")
md("""
**Reading it honestly.** Proxy-derived features reach ROC-AUC ≈ 0.7, no better than the simple 500 m heuristic and
well above the point rule (0.56). The ML recovers 5 hotspots the proxy misses, loses 4 it hits, and 7 western
hotspots are missed by both: the proxy cannot see drainage. ML uplift is therefore labelled low confidence.
""")

md("""
## 5. Scenarios, EP curve and expected loss
Three nested hazard layers through the same engine: proxy only → + known hotspots → + ML (adopted).
""")
code("""
display(res["scenarios"])
plots.ep_curves(res["ep_baseline"], res["ep_hotspots"], res["ep_augmented"], res["ep_naive_mapping"]);
aal = {k: risk.ep_aal(e) for k, e in [("baseline_proxy", res["ep_baseline"]), ("proxy_plus_hotspots", res["ep_hotspots"]), ("ml_augmented", res["ep_augmented"])]}
display(pd.DataFrame({"AAL (KES)": aal, "AAL rate": {k: float(risk.loss_rate(v, expo.total_exposure(exposure))) for k, v in aal.items()}}))
display(res["loss_by_class"].round(0))
plots.loss_by_scenario_and_class(res["loss_by_class"], list(res["scenarios"].scenario));
""")
code("""
# Sensitivity of the result to the ML flag threshold
sm = summary.set_index("building_id").loc[exposure.building_id]
risk.threshold_sensitivity(exposure, exposure[config.HAZARD_COLUMNS["common"]].values, sm.ml_hotspot_likelihood.values,
                           sm.hotspot_proximity.values, res["s_reference"], res["scenarios"])
""")

md("""
## 6. Risk ranking
`risk_score` = percentile of annual loss rate (AAL / TIV); `rank_by_expected_loss` ranks absolute AAL.
""")
code("""
cols = ["building_id", "housing_class", "tiv_kes", "hazard_source", "proxy_susceptibility", "ml_hotspot_likelihood",
        "annual_flood_probability", "expected_annual_loss_kes", "risk_score", "risk_class", "confidence"]
display(summary[cols].head(10).round(4))
display(pd.crosstab(summary.hazard_source, summary.confidence))
plots.top_buildings(summary);
plots.risk_map(summary, hotspots);
""")

md("""
## 7. Explainability
Permutation importance and SHAP for the hotspot model; a deterministic loss decomposition per building.
""")
code("""
display(res["importance"].head(8).round(3))
plots.feature_importance(res["importance"]);
top = summary[summary.hazard_source == "ml_model"].head(3)
for _, r in top.iterrows():
    print(f"{r.building_id} ({r.housing_class}, {r.nearest_hotspot} at {r.nearest_hotspot_distance_m:,.0f} m)\\n  ML drivers: {r.ml_risk_drivers}\\n  loss drivers: {r.loss_drivers}")
""")

md("## 8. Baseline vs ML-augmented")
code("""
rp = risk.loss_at_return_period
cmp = pd.DataFrame({
    "baseline (proxy only)": {"hotspots flagged (of 24)": int(hv.baseline_flagged.sum()), "hotspot ROC-AUC": hm["baseline_roc_auc_point_score"],
        "buildings with hazard": int((summary.proxy_susceptibility > 0).sum()), "AAL (KES)": aal["baseline_proxy"],
        "RP100 (KES)": rp(res["ep_baseline"], 100), "RP250 (KES)": rp(res["ep_baseline"], 250)},
    "ML-augmented (adopted)": {"hotspots flagged (of 24)": int(hv.ml_flagged.sum()), "hotspot ROC-AUC": hm["ml_roc_auc_loo"],
        "buildings with hazard": int((summary.augmented_susceptibility > 0).sum()), "AAL (KES)": aal["ml_augmented"],
        "RP100 (KES)": rp(res["ep_augmented"], 100), "RP250 (KES)": rp(res["ep_augmented"], 250)}})
display(cmp)
plots.baseline_vs_ml_building_loss(summary);
""")
md("""
**Limitations.** Synthetic exposure and proxy hazard; only 24 labelled hotspots (13 ungeocoded ones may sit in the
background set); the model cannot see drainage; return periods and the 4 m depth anchor are assumptions, so the EP
curve's shape is more reliable than its level; JRC values are transcribed and adapted; ground-up losses only.
""")

md("## 9. Export")
code("""
paths = pipeline.write_outputs(res)
pred = pd.read_csv(config.OUTPUT_DIR / "risk_predictions.csv")
assert list(pred.columns) == pipeline.RISK_PREDICTION_COLUMNS
assert np.allclose(pred.expected_loss_kes, pred.damage_ratio * pred.exposure_kes)
print(len(paths), "files written to outputs/;", pred.shape, "rows in risk_predictions.csv")
pred.head(5)
""")

nb = nbf.v4.new_notebook(); nb["cells"] = cells
nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
out = ROOT / "notebooks" / "flood_risk_model.ipynb"
nbf.write(nb, out); print("wrote", out.relative_to(ROOT), "with", len(cells), "cells")
