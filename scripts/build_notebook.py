"""Generate notebooks/flood_risk_model.ipynb from code. Run: python scripts/build_notebook.py"""
from pathlib import Path
import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]
nb = nbf.v4.new_notebook()
cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip()))
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip()))

md("""
# Nairobi Urban Flood Challenge: building-level flood risk and loss model

**Team A hackathon, ML component.** This notebook runs the full catastrophe-model chain
*Hazard → Vulnerability → Exposure → Financial engine → EP curve* on the starter kit, and adds an ML
layer that changes the hazard output. Model logic lives in `src/`; this notebook presents it.

> Everything here uses a **synthetic** exposure portfolio and a **terrain-proxy** hazard layer. No number
> below is an observed loss. Every assumption is listed in `src/config.py` and exported to
> `outputs/assumptions.json`.

## 1. Problem definition

A reinsurer needs, for a portfolio of Nairobi buildings:

1. **Hazard** – where surface-water flooding happens and how severe it is, per return period.
2. **Vulnerability** – the damage ratio a building suffers at a given severity, by construction class.
3. **Exposure** – which buildings exist and their insured value (KES).
4. **Financial engine** – per-building and portfolio losses per scenario, an exceedance-probability (EP) curve
   and the average annual loss (AAL).
5. **AI layer (required)** – something that materially changes the output. The starter-kit proxy flags only
   12 of 24 government-named hotspots. We train a hotspot model on proxy-derived neighbourhood features,
   validate it honestly, and feed its evidence (plus the known hotspots) back into the hazard layer.

The outputs are written in a machine-readable form so an agent can answer *which buildings are highest risk,
what happens at 100 years, why is this building high risk* from evidence rather than invention.
""")

md("## 2. Imports and configuration")
code("""
import sys, json, warnings
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib.pyplot as plt

ROOT = Path.cwd().resolve()
while not (ROOT / "src").exists():
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
pd.set_option("display.width", 160); pd.set_option("display.max_columns", 40); pd.set_option("display.float_format", "{:,.4g}".format)

from src import config, data, exposure as expo, hazard, vulnerability, risk, explain, plots, pipeline
plots.style()
np.random.seed(config.RANDOM_SEED)
print("project root:", ROOT.name, "| data dir exists:", config.DATA_DIR.exists(), "| seed:", config.RANDOM_SEED)
pd.DataFrame([{"scenario": s["name"], "return_period": s["return_period"], "footprint_tier": s["footprint_tier"]} for s in config.SCENARIOS])
""")

md("""
## 3. Dataset loading

Files in `Dataset/team_a_nairobi/` (private, gitignored):

| file | content |
|---|---|
| `exposure_nairobi_with_hazard.csv` | 600 synthetic buildings with five pre-attached hazard scores |
| `exposure_nairobi_synthetic.csv` | same 600 buildings without hazard scores |
| `nairobi_hotspots_geocoded.csv` | 24 of the 37 government-named flood hotspots, geocoded |
| `nairobi_pluvial_proxy_{common,…,extreme}.tif` | five 0–1 susceptibility rasters, 1260×1439 cells, ~31 m, EPSG:4326 |
""")
code("""
raw = data.load_exposure()
raw_nohaz = data.load_exposure(config.EXPOSURE_SYNTHETIC_FILE)
hotspots = data.load_hotspots()
rasters = data.load_hazard_rasters()
print(f"exposure: {raw.shape}, without hazard: {raw_nohaz.shape}, hotspots: {hotspots.shape}")
for t, r in rasters.items():
    print(f"raster {t:<11} shape={r.shape} origin=({r.x_origin}, {r.y_origin}) pixel={r.pixel_size_m():.1f} m  zero-fraction={(r.values <= 0).mean():.2f}")
raw.head(3)
""")

md("## 4. Data quality checks")
code("""
display(data.data_quality_report(raw))
display(data.data_quality_report(hotspots))
# (a) the two exposure files describe the same buildings
assert (raw[["loc_id", "lat", "lon", "tiv_kes"]].values == raw_nohaz[["loc_id", "lat", "lon", "tiv_kes"]].values).all()
# (b) our raster lookup reproduces the pre-attached scores exactly
for t, col in config.HAZARD_COLUMNS.items():
    diff = np.abs(rasters[t].sample(raw.lat.values, raw.lon.values) - raw[col].values).max()
    assert diff < 1e-12, (t, diff)
print("raster lookup reproduces CSV hazard columns to <1e-12")
# (c) insured value structure in the synthetic portfolio
ratio = raw.tiv_kes / (raw.floor_area_m2 * raw.cost_per_m2_kes)
print(f"tiv_kes / (area x cost) = {ratio.min():.3f} .. {ratio.max():.3f}  -> TIV is 10 x rebuild cost in this synthetic set")
# (d) the five tiers are nested views of ONE surface S: tier = max(0, (S - t)/(1 - t))
thresholds = hazard.infer_tier_thresholds(raw.rename(columns={}))
print("inferred tier thresholds:", {k: round(v, 4) for k, v in thresholds.items()})
print("they equal the S-quantiles at each tier's zero-fraction:",
      {t: round(float(np.quantile(rasters["common"].values, (rasters[t].values <= 0).mean())), 4) for t in config.TIERS[1:]})
""")

md("""
## 5. Exploratory data analysis

Key facts: 57% of buildings sit on cells the proxy scores at exactly zero; the proxy's footprint shrinks from
40% of cells (`common`) to 5% (`extreme`); and the 12 hotspots the proxy misses are concentrated in the
west and south-west of the city (Westlands, Lavington, Kibera, Kawangware …), where flooding is driven by
drainage rather than terrain.
""")
code("""
ex0 = expo.build_exposure(raw)
display(expo.exposure_summary(ex0))
fr_tmp = hazard.build_feature_rasters(rasters["common"])
hot_feat = hazard.location_features(fr_tmp, hotspots.lat, hotspots.lon)
hot_tbl = hotspots.assign(proxy_at_point=hot_feat.s_point.values, proxy_max_500m=hot_feat.s_max_500.values,
                          baseline_flagged=hazard.baseline_point_flag(hot_feat))
print(f"baseline rule 'proxy at point > 0' flags {hot_tbl.baseline_flagged.sum()} of {len(hot_tbl)} hotspots (document: 12 of 24)")
display(hot_tbl.round(3))
plots.hazard_distribution(ex0);
r = rasters["common"]; extent = (r.x_origin, r.x_origin + r.shape[1]*r.x_res, r.y_origin - r.shape[0]*r.y_res, r.y_origin)
plots.hotspot_map(r.values, extent, ex0, hotspots, hot_tbl.rename(columns={"baseline_flagged": "baseline_flagged"}));
""")

md("""
## 6. Feature engineering

Only features that can be derived from the proxy raster itself are used for the ML hotspot model, so the
model cannot leak the hotspot labels:

* `s_point` – proxy score at the location
* `s_max_r`, `s_mean_r`, `frac_wet_r` for r ∈ {150, 300, 500, 1000} m – neighbourhood maximum, mean and
  share of non-zero cells (hotspots are neighbourhoods, geocodes are centroids)
* `dist_wet_m`, `dist_strong_m` – distance to the nearest non-zero cell and to the nearest cell with S > 0.3

Not used as model inputs: raw coordinates (reported as a variant in §11), building density (the buildings
are synthetic, so their density is not an observation), distance to hotspots (that *is* the label – it is
used only as a separate, transparent hazard layer in §9).
""")
code("""
hot_feat.describe().T[["mean", "min", "max"]].round(3)
""")

md("""
## 7. Exposure calculation

`src/exposure.py::build_exposure` validates the portfolio, standardises names and attaches hazard scores
(from the CSV or by raster lookup). Insured value = `tiv_kes` as supplied, flagged synthetic.
""")
code("""
exposure = expo.build_exposure(raw_nohaz, rasters)   # demonstrates the raster-lookup path
assert np.allclose(exposure[config.HAZARD_COLUMNS["common"]], raw[config.HAZARD_COLUMNS["common"]])
print(f"total exposure: KES {expo.total_exposure(exposure):,.0f} across {len(exposure)} synthetic buildings")
exposure.head()
""")

md("""
## 8. Vulnerability calculation

Reference curve: JRC global flood depth-damage functions (Huizinga, de Moel & Szewczyk 2017), residential,
Africa. Adaptation per housing class (assumption V2): a *depth multiplier* (fragile structures reach a given
damage at shallower depth) and a *cap* of 0.80–0.95 as the document recommends.

`damage_ratio(depth, class) = min(cap_class, JRC(depth × multiplier_class))`
""")
code("""
display(pd.DataFrame(config.HOUSING_CLASS_VULNERABILITY).T)
curves = vulnerability.vulnerability_curves()
plots.vulnerability_curves(curves);
curves[curves.depth_m.isin([0.5, 1.0, 2.0, 3.0, 4.0])].round(3)
""")

md("""
## 9. Hazard and flood-probability modelling

### 9.1 From five tiers to return periods (assumption H1)
The tiers are nested thresholded views of one surface `S` (§4). The file labelled *extreme* flags the 5%
most susceptible cells – the places that flood first, i.e. in **frequent** events. In a **rare** event the
water reaches less susceptible cells and the footprint widens to the 40% flagged in *common*. So the smallest
footprint gets the shortest return period. The intuitive file-name mapping produces a loss curve that
*falls* as events get rarer, which is physically impossible – shown below as the rejected alternative.

### 9.2 Severity to depth (assumption H2)
`depth_k = 4 m × max(0, S − t_k)`: a rising-water-level model anchored on the document's "S = 1 ≈ 4 m" example.

### 9.3 Flood probability
Two quantities are produced per building: the **ML hotspot likelihood** (does this location look like a known
hotspot?) and the **annual flood probability** (exceedance probability of the most frequent scenario in which
the building gets any depth).
""")
code("""
scen = hazard.scenario_table(thresholds)
display(scen)
s_proxy = exposure[config.HAZARD_COLUMNS["common"]].values
ep_nested = risk.ep_curve(risk.scenario_losses(exposure, s_proxy, scen))
ep_naive = risk.ep_curve(risk.scenario_losses(exposure, s_proxy, hazard.scenario_table(thresholds, "naive")))
pd.DataFrame({"return_period": ep_nested.return_period_years,
              "adopted (nested footprints) loss KES": ep_nested.portfolio_loss_kes,
              "rejected (file-name order) loss KES": ep_naive.portfolio_loss_kes})
""")
code("""
X, y, meta = hazard.build_training_set(hotspots, exposure, fr_tmp)
print(f"training set: {int(y.sum())} hotspots (positives) vs {int((y==0).sum())} background buildings "
      f"> {config.HOTSPOT_NEGATIVE_BUFFER_M:.0f} m from any hotspot (treated as unlabelled negatives)")
X.assign(label=y).groupby("label").mean().T.round(3)
""")

md("""
## 10. Model training

`pipeline.run_pipeline` executes the whole chain with fixed seeds: candidate models (logistic regression,
random forest, histogram gradient boosting) are compared with 5-fold stratified CV repeated 10 times, the
winner is refit, every hotspot is scored **leave-one-out**, and 100 bootstrap refits give an uncertainty band
for every building. This cell takes ~2 minutes.
""")
code("""
res = pipeline.run_pipeline()
model_name, cv = res["chosen_model"], res["cv_results"]
print("selected model:", model_name)
""")

md("""
## 11. Model validation

With 24 positives a random 80/20 split is noise, so three complementary checks are used:

1. **Repeated stratified CV** (5 folds × 10 repeats, ~5 hotspots held out each time) – mean ± std of ROC-AUC,
   average precision, recall and false-positive rate at the 0.5 flag threshold.
2. **Leave-one-out** – each hotspot's likelihood comes from a model that never saw it.
3. **Matched operating point** – recall of each method at the *baseline's* false-positive rate.

Two baselines are included: the starter-kit rule (point score > 0) and a non-ML heuristic (max score within 500 m).
""")
code("""
display(cv[[c for c in cv.columns if c.endswith("_mean")]].round(3))
plots.cv_comparison(cv);
hm = res["hotspot_metrics"]
print(json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in hm.items()}, indent=1))
plots.baseline_vs_ml_hotspots(res["hotspot_validation"]);
res["hotspot_validation"].round(3)
""")
md("""
**Reading the results honestly.**

* All three ML models reach ROC-AUC ≈ 0.68–0.70 on proxy-derived features – the same as the simple
  500 m neighbourhood-max heuristic (0.68) and better than the point rule (0.56). Average precision roughly
  doubles versus the point rule (prevalence is 0.05).
* Out of sample, the ML flags 13 of 24 hotspots versus 12 for the baseline. It **recovers five the proxy
  misses** (Donholm, Madaraka, Lang'ata, Kileleshwa, Kibera) but **loses four** the proxy hits (Kiambiu,
  Kayole, Nairobi West, Chiromo). Seven western hotspots are missed by both.
* The `+latlon` variants score much higher (HGB ROC-AUC 0.85) because hotspots cluster spatially. That is
  memorising *where* the known hotspots are, which the deterministic hotspot-proximity layer (§9) already
  encodes transparently; a coordinate model cannot discover new areas, so it is not adopted.
* **Conclusion:** the terrain proxy carries only weak information about drainage-driven hotspots. The ML layer is
  best read as a learned spatial smoothing of the proxy, and its uplift is labelled *low confidence* in the
  outputs. Closing the gap needs new signals (drainage condition, informal-settlement boundaries, more hotspot
  names) – exactly what the agent layer can ingest.
""")

md("""
## 12. Scenario / return-period analysis

Three nested hazard layers are run through the same vulnerability and financial engine:

1. **baseline** – terrain proxy only;
2. **proxy + known hotspots** – buildings within 1.5 km of a government hotspot get at least
   `S_ref × kernel(distance)`;
3. **ML-augmented (adopted)** – additionally, locations the ML model flags (likelihood ≥ 0.5) get `S_ref × likelihood`.

`S_ref` is derived from data: the median 500 m neighbourhood-max susceptibility at the 24 known hotspots.
""")
code("""
print(f"S_ref = {res['s_reference']:.3f}")
plots.ep_curves(res["ep_baseline"], res["ep_hotspots"], res["ep_augmented"], res["ep_naive_mapping"]);
ep = res["ep_baseline"][["scenario", "return_period_years", "exceedance_probability", "portfolio_loss_kes", "buildings_flooded"]].rename(
    columns={"portfolio_loss_kes": "baseline_loss", "buildings_flooded": "baseline_flooded"})
ep["hotspots_loss"] = res["ep_hotspots"].portfolio_loss_kes.values
ep["ml_augmented_loss"] = res["ep_augmented"].portfolio_loss_kes.values
ep["ml_augmented_flooded"] = res["ep_augmented"].buildings_flooded.values
ep
""")

md("""
## 13. Expected loss calculation

Per building and scenario: `loss = damage_ratio × tiv_kes`. The **average annual loss** integrates the
EP curve (trapezoids between scenarios; zero loss for events more frequent than 5 years; flat beyond 250
years). The vulnerability *matrix* evaluates the curves at a typical exposed building (median augmented
susceptibility among buildings with any hazard) pushed through each scenario, as the document's tiered
presentation requires. Zeros in the RP5/RP10 columns mean that typical building is not reached by frequent events.
""")
code("""
aal = {k: risk.average_annual_loss(e.portfolio_loss_kes.values, e.exceedance_probability.values)
       for k, e in [("baseline_proxy", res["ep_baseline"]), ("proxy_plus_hotspots", res["ep_hotspots"]), ("ml_augmented", res["ep_augmented"])]}
tiv = expo.total_exposure(exposure)
display(pd.DataFrame({"portfolio AAL (KES)": aal, "AAL rate": {k: v / tiv for k, v in aal.items()}}))
display(res["vulnerability_matrix"].round(3))
display(res["loss_by_class"].round(0))
plots.loss_by_scenario_and_class(res["loss_by_class"], list(res["scenarios"].scenario));
# sensitivity of the adopted layer to the ML flag threshold
rows = []
summ = res["summary"].set_index("building_id").loc[exposure.building_id]
for thr in [0.5, 0.6, 0.7, 0.8, 1.01]:
    s_aug, _ = hazard.augment_susceptibility(s_proxy, summ.ml_hotspot_likelihood.values, summ.hotspot_proximity.values, res["s_reference"], ml_threshold=thr)
    e = risk.ep_curve(risk.scenario_losses(exposure, s_aug, scen))
    rows.append({"ml_flag_threshold": thr if thr <= 1 else "ML off", "buildings_with_hazard": int((s_aug > 0).sum()),
                 "AAL_kes": risk.average_annual_loss(e.portfolio_loss_kes.values, e.exceedance_probability.values), "RP100_loss_kes": float(e.loc[e.return_period_years == 100, "portfolio_loss_kes"].iloc[0])})
pd.DataFrame(rows)
""")

md("""
## 14. Risk ranking

`risk_score` = percentile rank (0–100) of the annual loss *rate* (AAL / TIV), so it measures how risky the
location + construction is independent of size; `rank_by_expected_loss` ranks absolute AAL for the
accumulation view. `risk_class` bands the score; `confidence` encodes how many independent sources support the hazard.
""")
code("""
summary = res["summary"]
cols = ["building_id", "housing_class", "tiv_kes", "hazard_source", "proxy_susceptibility", "ml_hotspot_likelihood",
        "augmented_susceptibility", "annual_flood_probability", "expected_annual_loss_kes", "aal_rate", "risk_score", "risk_class", "confidence"]
display(summary[cols].head(15).round(4))
display(summary.groupby("risk_class").agg(buildings=("building_id", "count"), tiv=("tiv_kes", "sum"), aal=("expected_annual_loss_kes", "sum")))
display(pd.crosstab(summary.hazard_source, summary.confidence))
plots.top_buildings(summary);
plots.risk_map(summary, hotspots);
""")

md("""
## 15. Explainability

* **Permutation importance** of the hotspot model (drop in average precision when a feature is shuffled).
* **SHAP values** (exact linear explainer for the logistic pipeline) for every building, summarised below and
  stored per building as `ml_risk_drivers`.
* A deterministic **loss decomposition** (`loss_drivers`): hazard source, annual flood probability, insured
  value and vulnerability cap – because loss = hazard × vulnerability × exposure, every number is traceable.
""")
code("""
display(res["importance"].round(3))
plots.feature_importance(res["importance"]);
import shap
shap.summary_plot(res["shap_buildings"], res["X_buildings_aligned"], show=False, max_display=10, color_bar=True)
plt.gcf().set_size_inches(8, 4.5); plt.title("SHAP values of the hotspot model across the 600 buildings", loc="left"); plt.tight_layout(); plt.show()
ml_only = summary[summary.hazard_source == "ml_model"].sort_values("expected_annual_loss_kes", ascending=False).head(5)
for _, r in ml_only.iterrows():
    print(f"{r.building_id} ({r.housing_class}, nearest hotspot {r.nearest_hotspot} at {r.nearest_hotspot_distance_m:,.0f} m)\\n   ML drivers: {r.ml_risk_drivers}\\n   loss drivers: {r.loss_drivers}")
""")

md("""
## 16. Baseline vs improved model comparison
""")
code("""
cmp = pd.DataFrame({
    "baseline (proxy only)": {
        "hotspots flagged (of 24)": int(res["hotspot_validation"].baseline_flagged.sum()),
        "hotspot ROC-AUC": hm["baseline_roc_auc_point_score"],
        "buildings with any hazard": int((summary.proxy_susceptibility > 0).sum()),
        "portfolio AAL (KES)": aal["baseline_proxy"],
        "RP100 loss (KES)": float(res["ep_baseline"].loc[res["ep_baseline"].return_period_years == 100, "portfolio_loss_kes"].iloc[0]),
        "RP250 loss (KES)": float(res["ep_baseline"].loc[res["ep_baseline"].return_period_years == 250, "portfolio_loss_kes"].iloc[0]),
    },
    "ML-augmented (adopted)": {
        "hotspots flagged (of 24)": int(res["hotspot_validation"].ml_flagged.sum()),
        "hotspot ROC-AUC": hm["ml_roc_auc_loo"],
        "buildings with any hazard": int((summary.augmented_susceptibility > 0).sum()),
        "portfolio AAL (KES)": aal["ml_augmented"],
        "RP100 loss (KES)": float(res["ep_augmented"].loc[res["ep_augmented"].return_period_years == 100, "portfolio_loss_kes"].iloc[0]),
        "RP250 loss (KES)": float(res["ep_augmented"].loc[res["ep_augmented"].return_period_years == 250, "portfolio_loss_kes"].iloc[0]),
    }})
display(cmp)
plots.baseline_vs_ml_building_loss(summary);
newly = summary[(summary.proxy_susceptibility <= 0) & (summary.augmented_susceptibility > 0)]
print(f"{len(newly)} buildings had zero proxy hazard and now carry hazard: "
      f"{(newly.hazard_source == 'known_hotspot').sum()} via known hotspots, {(newly.hazard_source == 'ml_model').sum()} via the ML model "
      f"(KES {newly.expected_annual_loss_kes.sum():,.0f} of AAL, {newly.confidence.value_counts().to_dict()})")
""")
md("""
**Limitations (state these to judges).**

* **Synthetic exposure, proxy hazard.** No loss number is an observation. The portfolio is the starter kit's
  synthetic set; the hazard is terrain-derived susceptibility, not modelled depth.
* **Small label set.** 24 positive hotspots; the 13 ungeocoded hotspots may sit among the "background"
  buildings (positive-unlabelled setting). CV standard deviations are wide (±0.07 AUC).
* **Weak signal.** Proxy-derived features reach ROC-AUC ≈ 0.7; the ML cannot see drainage. Its uplift is
  gated at likelihood ≥ 0.5 and labelled low confidence; the threshold sensitivity table in §13 shows how much
  of the AAL depends on it.
* **Assumed return periods and depth scale.** 5/10/25/100/250 years and the 4 m anchor are judgements, not
  calibrated frequencies; the EP curve's *shape* is more trustworthy than its *level*.
* **Vulnerability transfer.** JRC Africa residential curve values are transcribed and adapted; no Kenya claims data.
* **No financial terms.** Ground-up losses only (deductibles, limits and reinsurance are out of scope).
""")

md("""
## 17. Visualizations

All figures shown above are saved to `outputs/figures/`:
""")
code("""
for p in sorted(config.FIGURE_DIR.glob("*.png")):
    print(" ", p.relative_to(ROOT))
""")

md("""
## 18. Export of final model outputs

Machine-readable artefacts for the agent layer. `risk_predictions.csv` has one row per building × scenario;
`building_risk_summary.csv` has one row per building with drivers; `portfolio_summary.json`,
`model_metrics.json` and `assumptions.json` carry the headline numbers, validation evidence and every assumption.
""")
code("""
paths = pipeline.write_outputs(res)
for p in paths:
    print(" ", p.relative_to(ROOT))
pred = pd.read_csv(config.OUTPUT_DIR / "risk_predictions.csv")
assert list(pred.columns) == pipeline.RISK_PREDICTION_COLUMNS
assert np.allclose(pred.expected_loss_kes, pred.damage_ratio * pred.exposure_kes)
print(pred.shape)
pred.head(10)
""")

nb["cells"] = cells
nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
out = ROOT / "notebooks" / "flood_risk_model.ipynb"
nbf.write(nb, out)
print("wrote", out.relative_to(ROOT), "with", len(cells), "cells")
