# Nairobi Urban Flood Risk Model (Team A hackathon, ML component)

An end-to-end, explainable flood catastrophe model for a synthetic portfolio of 600 Nairobi buildings:
**hazard → vulnerability → exposure → financial engine → EP curve**, with an ML layer that changes the
hazard output and machine-readable results an agent can reason over.

> All exposure data is **synthetic** and the hazard layer is a **terrain proxy**, not measured flooding.
> No number produced here is an observed loss. Every assumption is listed in
> [`src/config.py`](src/config.py) and exported to `outputs/assumptions.json`.

## 1. The problem

Nairobi's surface-water (pluvial) flooding is priced by judgement; no local CAT model exists. The challenge
supplies a terrain-based susceptibility proxy (five nested 0–1 rasters), 24 geocoded government flood
hotspots and a synthetic building portfolio. The proxy correctly flags only 12 of the 24 hotspots because
the misses (Kibera, Westlands, Lavington, Kawangware …) flood through drainage failure that terrain cannot
see. The task: produce building-level loss by return period and an EP curve, and use AI to materially
change the result while being honest about its limits.

## 2. Modelling approach

| Stage | What we do | Where |
|---|---|---|
| **Exposure** | Validate the synthetic portfolio, standardise fields, attach hazard scores by raster lookup (pure NumPy, verified to 1e-16 against the pre-attached CSV). Insured value = `tiv_kes`. | [`src/exposure.py`](src/exposure.py) |
| **Hazard (proxy)** | The five tiers are nested views of one surface `S`: `tier = max(0,(S−t)/(1−t))`, thresholds inferred from data. Smallest footprint (file *extreme*, 5 % of cells) = most frequent scenario (RP5); largest (*common*, 40 %) = RP250. Depth `= 4 m × max(0, S − t_k)`. | [`src/hazard.py`](src/hazard.py) |
| **Hazard (ML)** | Logistic regression (selected over RF / HGB by repeated stratified CV) that scores "does this location look like a known hotspot?" from proxy-derived neighbourhood features only. Validated leave-one-out; 100 bootstrap refits give an uncertainty band. Gated uplift `S_ref × likelihood` where likelihood ≥ 0.5. | [`src/hazard.py`](src/hazard.py) |
| **Hazard (known hotspots)** | Gaussian proximity kernel (σ = 500 m, cut-off 1.5 km) to the 24 government hotspots, scaled by `S_ref` (data-derived). | [`src/hazard.py`](src/hazard.py) |
| **Vulnerability** | JRC global depth-damage curve (Huizinga et al. 2017, residential, Africa) adapted per housing class with a depth multiplier and a cap of 0.80–0.95. Continuous curve plus the tiered matrix. | [`src/vulnerability.py`](src/vulnerability.py) |
| **Financial engine** | `loss = damage_ratio × tiv_kes` per building per scenario; portfolio EP curve; AAL by trapezoidal integration; risk score, risk class, confidence label. | [`src/risk.py`](src/risk.py) |
| **Explainability** | Permutation importance, SHAP values per building, deterministic loss decomposition. | [`src/explain.py`](src/explain.py) |
| **Orchestration** | One call runs everything with fixed seeds and writes `outputs/`. | [`src/pipeline.py`](src/pipeline.py) |

Three nested hazard layers are run through the identical vulnerability and financial engine so the
contribution of each is auditable: **baseline proxy → + known hotspots → + ML (adopted)**.

### Headline results (synthetic portfolio, total insured value KES 63.6 bn)

| | baseline proxy | + known hotspots | + ML (adopted) |
|---|---|---|---|
| buildings with any modelled hazard | 259 | 318 | 398 |
| portfolio average annual loss | KES 272 m | KES 346 m | KES 607 m |
| 100-year loss | KES 3.58 bn | KES 4.46 bn | KES 8.75 bn |
| 250-year loss | KES 5.95 bn | KES 7.30 bn | KES 12.17 bn |
| hotspots flagged (of 24) | 12 | – | 13 (out of sample) |

### Validation, honestly

* 24 positives only, so: 5-fold stratified CV repeated 10×, leave-one-out scoring of every hotspot, and
  recall compared at the baseline's false-positive rate.
* All ML candidates reach ROC-AUC ≈ 0.68–0.70 on proxy-derived features; a non-ML "max within 500 m"
  heuristic reaches 0.68 and the starter-kit point rule 0.56. Average precision ≈ 0.15 vs 0.06 (prevalence 0.05).
* Out of sample the ML recovers five hotspots the proxy misses (Donholm, Madaraka, Lang'ata, Kileleshwa,
  Kibera) and loses four it hits. Seven western hotspots are missed by both.
* Adding raw coordinates lifts CV AUC to 0.85, but that memorises *where* known hotspots are, which the
  transparent proximity layer already encodes; it was not adopted.
* Conclusion: the terrain proxy carries weak information about drainage-driven hotspots. ML uplift is
  therefore labelled **low confidence** and its threshold sensitivity is reported in the notebook.

## 3. Dataset structure (private, gitignored)

`Dataset/team_a_nairobi/` — never committed.

| file | rows × cols | content |
|---|---|---|
| `exposure_nairobi_with_hazard.csv` | 600 × 14 | `loc_id, lat, lon, housing_class, floor_area_m2, cost_per_m2_kes, tiv_kes, synthetic, source, hazard_score_{common,occasional,moderate,severe,extreme}` |
| `exposure_nairobi_synthetic.csv` | 600 × 9 | same without hazard columns |
| `nairobi_hotspots_geocoded.csv` | 24 × 3 | `name, lat, lon` |
| `nairobi_pluvial_proxy_<tier>.tif` | 1260 × 1439 | float32, EPSG:4326, origin (36.6 E, 1.1 S), 1/3600° (~31 m) pixels |

Housing classes: `informal_iron_sheet` (179), `semi_permanent` (181), `permanent_masonry` (156),
`concrete_rcc` (84). No missing values. `tiv_kes = 10 × floor_area × cost_per_m2`.

## 4. Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Place the starter kit in `Dataset/team_a_nairobi/` (it is gitignored). No GDAL/rasterio needed.

## 5. Running

```bash
# full pipeline from the command line (~2 min; writes outputs/)
python -m src.pipeline

# notebook (regenerate from code, then execute)
python scripts/build_notebook.py
jupyter nbconvert --to notebook --execute --inplace notebooks/flood_risk_model.ipynb
# or open notebooks/flood_risk_model.ipynb in JupyterLab and run all cells

# tests (synthetic fixtures only; the last test checks the output contract if outputs exist)
python -m pytest tests -q
```

## 6. Model limitations

* Synthetic exposure and a proxy hazard: results demonstrate the method, not Nairobi's actual risk.
* 24 labelled hotspots; the 13 ungeocoded ones may be among the "background" training points.
* The ML cannot see drainage; its AUC ≈ 0.7 equals a simple spatial heuristic. Treat its uplift as low confidence.
* Return periods (5/10/25/100/250 y) and the 4 m depth anchor are stated assumptions, not calibrated frequencies.
  The EP curve's shape is more trustworthy than its level.
* JRC curve values are transcribed and adapted without Kenyan claims data.
* Ground-up losses only; no deductibles, limits or reinsurance terms.

## 7. Output files (`outputs/`)

| file | grain | purpose |
|---|---|---|
| `risk_predictions.csv` | building × scenario (3 000 rows) | the agent's main table: exposure, flood probability, hazard source, susceptibility (proxy / ML / augmented), severity, depth, damage ratio, expected loss, baseline loss, risk score/class, confidence |
| `building_risk_summary.csv` | building (600) | AAL, AAL rate, losses and depths per scenario, rank, share of portfolio AAL, nearest hotspot, ML drivers (SHAP), loss drivers |
| `ep_curve.csv` | scenario | portfolio loss for the three hazard layers |
| `ep_curve_rejected_naive_mapping.csv` | scenario | the rejected tier mapping (loss falls with rarity) |
| `loss_by_housing_class*.csv` | class | accumulation view |
| `hotspot_validation.csv` | hotspot (24) | baseline flag vs leave-one-out ML likelihood |
| `model_cv_results.csv`, `model_metrics.json` | model | CV scores, matched-FPR recall, which hotspots were recovered/lost |
| `feature_importance.csv` | feature | permutation importance and coefficients |
| `vulnerability_matrix.csv`, `vulnerability_curves.csv` | class × scenario / depth | documented vulnerability |
| `scenarios.csv`, `portfolio_summary.json`, `assumptions.json` | – | scenario definitions, headline numbers, every assumption |
| `models/hotspot_model.joblib` | – | fitted model with feature list and thresholds |
| `figures/*.png` | – | 12 figures used in the notebook |

## 8. Consuming the outputs from an agent

Every question the agent should answer maps to a column, so the LLM cites evidence instead of inventing it:

| question | evidence |
|---|---|
| Which buildings are highest risk? | `building_risk_summary.csv` sorted by `risk_score` (rate-based) |
| Highest expected loss / portfolio contributors? | `rank_by_expected_loss`, `share_of_portfolio_aal` |
| What happens at 10 / 25 / 100 / 250 years? | `risk_predictions.csv` filtered by `scenario`; `ep_curve.csv`; `portfolio_summary.json` |
| Most vulnerable locations? | `annual_flood_probability`, `augmented_susceptibility`, `nearest_hotspot` |
| Why is this building high risk? | `loss_drivers`, `ml_risk_drivers`, `hazard_source`, `confidence` |
| What should be prioritised? | high `expected_annual_loss_kes` with `confidence = high`; `hazard_source = known_hotspot` for drainage interventions |
| What is assumed vs observed? | `assumptions.json`; `is_synthetic` flag on every row |

Design notes for the agent: `flood_probability` is an annual exceedance probability from the scenario set;
`ml_hotspot_likelihood` is a balanced-class score (not a calibrated probability) with `ml_likelihood_std`
from bootstrapping; `confidence ∈ {high, medium, low}` follows the rule in `src/risk.py::confidence_label`.

## 9. Repository layout

```
src/            model code (config, data, exposure, hazard, vulnerability, risk, explain, plots, pipeline)
notebooks/      flood_risk_model.ipynb (generated by scripts/build_notebook.py, executed)
tests/          pytest suite with synthetic fixtures (never touches Dataset/)
outputs/        machine-readable results and figures
docs/           MODEL_DESIGN.md – requirement-to-implementation map
Dataset/        private starter kit (gitignored)
```
