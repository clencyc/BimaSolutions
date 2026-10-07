# Model design: how each challenge requirement maps to the implementation

Source: `Team_A_Nairobi_Problem_Statement.docx`. Quotes are from the document; the right-hand column is
where the requirement is met.

| # | Document requirement | Implementation |
|---|---|---|
| 1 | "Ingest hazard data" (Step 1, option 1 or 2) | `data.load_hazard_rasters` reads the five GeoTIFFs with Pillow/NumPy; `exposure.attach_hazard_scores` does the raster lookup (option 2) and is verified against the pre-attached CSV (option 1). |
| 2 | "decide how the 0–1 susceptibility score represents real-world flood severity … clearly explain what you assumed" | Assumption **H2** in `config.py`: `depth = 4 m × max(0, S − t_k)`, anchored on the document's own "1 ≈ 4 m" example. |
| 3 | "decide what return period each tier could reasonably represent and clearly state that assumption" | Assumption **H1**: tiers are nested views of one surface (verified in `hazard.infer_tier_thresholds`); smallest footprint = RP5 … largest = RP250. The naive file-name mapping is computed too (`scenario_table(..., "naive")`) and shown to give a loss curve that falls with rarity. |
| 4 | "Applies a documented and sourced vulnerability/depth-damage function … adapt an existing curve transparently" | `vulnerability.damage_ratio`: JRC/Huizinga 2017 Africa residential curve (**V1**), per-class depth multiplier and cap (**V2**) with rationale strings. |
| 5 | "The curve should also reflect construction type" / "losses typically capped at 80–95 %" | Four housing classes with multipliers 1.5 / 1.2 / 1.0 / 0.7 and caps 0.95 / 0.90 / 0.85 / 0.80. |
| 6 | "a documented vulnerability function **and vulnerability matrix**" | `vulnerability.vulnerability_matrix` (class × scenario) exported to `outputs/vulnerability_matrix.csv`. |
| 7 | "a structured portfolio … their characteristics, their values, and the information needed to connect them to the hazard and vulnerability stages" | `exposure.build_exposure` → standard columns, `tiv_kes`, housing class, five hazard scores, synthetic flag. |
| 8 | Step 4 financial engine: look up severity → vulnerability → damage ratio → × insured value → sum per scenario → repeat across return periods | `risk.scenario_losses`, `risk.ep_curve`, `risk.average_annual_loss`. |
| 9 | "Produce a return-period loss curve (EP curve)" | `outputs/ep_curve.csv`, figure `08_ep_curve.png`, for three hazard layers. |
| 10 | "Use AI in a way that materially enhances the result" / "Hazard layer improvement: particularly relevant to Team A" | ML hotspot model (`hazard.candidate_models`, `cross_validate_models`, `leave_one_out_probabilities`, `bootstrap_predictions`) whose flagged likelihood feeds `hazard.augment_susceptibility`; the known hotspots are also ingested as a structured hazard signal. Effect quantified in `portfolio_summary.json` (AAL 272 m → 607 m KES) and `hotspot_validation.csv`. |
| 11 | "Clearly state every assumption and every use of the provided synthetic data" | `config.assumptions_as_dict` → `outputs/assumptions.json`; `is_synthetic` on every prediction row; notebook §1 and §16. |
| 12 | "Do not present placeholder numbers as real observations" | README banner, notebook banner, `confidence` and `hazard_source` on every row, matched-FPR and LOO metrics reported without inflation. |
| 13 | "Total exposure, loss at key return periods, EP curve, breakdown by construction class, output of AI feature" (Step 6 minimum) | `portfolio_summary.json`, `ep_curve.csv`, `loss_by_housing_class.csv`, `hotspot_validation.csv` + `model_metrics.json`. The interface itself is the agent/dashboard team's deliverable; these files are its data contract. |
| 14 | "The 12 misses … flood because of drainage-system issues that this proxy cannot detect … an opportunity to improve the model" | Explicitly tested: which hotspots the ML recovers (5), loses (4), and which neither sees (7). Documented as the signal gap the agent layer should fill with drainage / settlement data. |

## Architecture

```
Dataset/ ──► data.py ──► exposure.py ──┐
                 │                     ├──► hazard.py ──► risk.py ──► outputs/
   rasters ──────┴─► feature rasters ──┘   (proxy S, ML p,   (depth → damage → loss,
                        ▲                   hotspot kernel,   EP, AAL, ranking,
   hotspots ────────────┘                   S_aug)            confidence)
                                              │
                                        explain.py (SHAP, importance, drivers)
```

## Validation strategy (24 positives)

1. Repeated stratified 5-fold CV × 10 (ROC-AUC, average precision, recall/FPR at 0.5).
2. Leave-one-out likelihood for each hotspot (`hotspot_validation.csv`).
3. Recall at the baseline's false-positive rate (`model_metrics.json`).
4. Two baselines (point rule; 500 m neighbourhood max) and a coordinates variant reported for transparency.
5. 100 bootstrap refits → `ml_likelihood_std` per building.

## Things deliberately **not** done

* No deep learning: 24 labels cannot support it and it would not be explainable.
* No building density or coordinate features in the adopted model (synthetic density is not an observation;
  coordinates memorise the label).
* No invented drainage data. The gap is stated and left for the agent layer to fill with cited sources.
