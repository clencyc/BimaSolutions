# AI Workflow Summary

This document describes the AI workflow for the Nairobi flood-risk model.

## 1. Goal

The AI workflow builds a transparent flood-risk model for a synthetic Nairobi portfolio, with the objective of:

- estimating flood susceptibility at the building level
- linking susceptibility to hazard, vulnerability, and loss
- producing portfolio-level exceedance and average annual loss outputs
- identifying the most material flood hotspots and model drivers
- exposing a commercial pricing contract built from the model outputs

## 2. Data inputs

The workflow starts from the available Nairobi portfolio and hazard data:

- synthetic building exposure data
- geocoded flood hotspot locations
- terrain-based flood proxy rasters
- property characteristics such as housing class, area, and insured value

The model is designed to work with a structured dataset where each row represents a building or property record.

## 3. Exposure preparation

The first AI stage standardises the raw exposure data and ensures that each building has the required fields for downstream risk modelling:

- building identifier
- latitude and longitude
- housing class
- floor area
- insured value (`tiv_kes`)
- hazard and spatial context features

This stage creates the model-ready portfolio used by the hazard and financial engine.

## 4. Hazard modelling

The hazard stage uses a layered AI and statistical approach:

- terrain-based flood proxy susceptibility
- proximity to known government hotspots
- ML hotspot uplift model derived from proxy-driven neighbourhood features

This produces a final susceptibility score per building and classifies the main hazard driver as one of:

- proxy
- known hotspot
- ML model
- none

The important point is that the workflow is auditable: each building can be traced to the source of the hazard signal.

## 5. Vulnerability and damage stage

Once hazard susceptibility is known, the workflow maps flood depth to vulnerability and loss:

- depth is estimated from the susceptibility signal
- vulnerability is inferred using a depth-damage function adapted by construction type
- damage ratio is applied to insured value
- building-level losses are computed for each scenario and return period

This produces a consistent bridge between physical flood intensity and financial loss.

## 6. Financial loss engine

The model then converts damaged exposure into portfolio loss metrics:

- scenario loss by building
- portfolio exceedance curve (EP curve)
- average annual loss (AAL)
- loss at return periods such as 5, 10, 25, 100 and 250 years
- building ranking by contribution to total portfolio risk

This stage is the main financial output of the AI workflow.

## 7. Model validation and confidence

The workflow explicitly measures model quality and uncertainty:

- cross-validation of hotspot detection performance
- leave-one-out hotspot scoring
- false-positive rate comparison against baselines
- model confidence and uncertainty bands
- risk classification by confidence and hazard source

This ensures the AI workflow is transparent about which outputs are high-confidence and which are weaker.

## 8. AI uplift and business interpretation

The AI model is used to improve hotspot detection beyond the terrain baseline. In practice, the workflow does three things:

- identifies likely flood-prone buildings from proxy terrain conditions
- adds known hotspot proximity as a structured hazard signal
- uses the ML hotspot model to improve detection where the proxy alone is weak

This is the value of the AI component: it materially improves the ranking and flood-risk signal, while remaining transparent about its limits.

## 9. Commercial pricing layer

The pricing layer takes model outputs such as:

- `tiv_kes`
- `expected_annual_loss_kes`
- `risk_class`
- `confidence`

and converts them into a commercial quote using a documented formula.

The pricing formula used by the model is:

```text
gross_premium = max(minimum_premium, AAL × (1 + risk_margin + expense_loading + commission_loading + profit_loading + reinsurance_loading))
```

This stage does not replace the AI model; it uses the model outputs as technical pricing inputs for a transparent commercial quote.

## 10. Output artifacts

The workflow produces machine-readable outputs used for downstream analysis and sharing, including:

- building-level risk predictions
- building risk summary table
- EP curve data
- feature importance outputs
- hotspot validation results
- model metrics and CV outputs
- vulnerability curves and matrix
- portfolio summary data

These outputs become the evidence base for the final model interpretation.

## 11. AI workflow principle

The key principle of the AI workflow is that the model remains the source of truth for:

- flood hazard assessment
- loss estimation
- risk ranking
- pricing inputs
- model uncertainty and assumptions

The AI workflow is therefore a deterministic analytical engine that supports underwriting and portfolio understanding, not a black-box generator of results.
