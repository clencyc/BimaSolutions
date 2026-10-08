# Backend Integration Contract

This document defines the contract between the model/AI layer and the backend team. It keeps the model as the deterministic source of truth and the backend as the runtime, persistence, and integration layer.

## 1. Responsibilities

### Model/AI layer responsibilities

- build the flood risk model
- validate input data and required schema fields
- compute hazard, vulnerability, and risk outputs
- calculate expected annual loss, risk class, and confidence
- compute commercial quote values using the approved formula
- expose machine-readable outputs via the Flask API

### Backend responsibilities

- receive uploads from the dashboard or underwriter workflow
- validate file type and basic schema before handing to the model
- map raw columns to the model schema
- trigger model execution for a given dataset
- store job metadata and results
- expose dashboard-facing API routes
- render summaries for the user interface
- handle authentication, user sessions, and persistence

## 2. Model boundary

The backend should not reimplement or override the model calculations.

The calculations are handled in:

- `src/hazard.py`
- `src/vulnerability.py`
- `src/risk.py`
- `src/pricing.py`
- `src/api.py`

The backend should treat these as the source of truth for:

- flood severity
- risk score and risk class
- expected annual loss
- quote and commercial premium calculation
- assumptions and formula logic

## 3. Expected model input schema

For a standard building portfolio, the model expects fields similar to these:

```json
{
  "building_id": "NBO-0316",
  "latitude": -1.2921,
  "longitude": 36.8219,
  "housing_class": "permanent_masonry",
  "floor_area_m2": 240,
  "cost_per_m2_kes": 52000,
  "tiv_kes": 12480000,
  "synthetic": true,
  "source": "portfolio"
}
```

Additional hazard feature columns may be included or created during preparation.

### Minimum required datapoints for quote generation

For quote generation, the model accepts any of the below modes:

1. stored portfolio building by `building_id`
2. geocoded freeform building name with optional `city` or `country`
3. latitude/longitude nearest-building lookup
4. manual inputs:
   - `tiv_kes`
   - `expected_annual_loss_kes`
   - `risk_class`
   - `confidence`

## 4. Output contract

The model exposes outputs through the API and should be consumed as read-only data by the backend.

### Portfolio summary response

```json
{
  "total_tiv_kes": 63600000000,
  "total_expected_annual_loss_kes": 607000000,
  "average_annual_loss_rate": 0.0095,
  "high_risk_buildings": 42
}
```

### Building summary row

```json
{
  "building_id": "NBO-0316",
  "housing_class": "permanent_masonry",
  "tiv_kes": 12480000,
  "expected_annual_loss_kes": 940000,
  "aal_rate": 0.075,
  "risk_score": 74.2,
  "risk_class": "high",
  "confidence": "medium"
}
```

### Quote response

```json
{
  "building_id": "NBO-0316",
  "tiv_kes": 12480000,
  "expected_annual_loss_kes": 940000,
  "risk_class": "high",
  "confidence": "medium",
  "technical_premium_kes": 940000,
  "risk_margin_rate": 0.25,
  "expense_loading_rate": 0.10,
  "commission_loading_rate": 0.10,
  "profit_loading_rate": 0.08,
  "reinsurance_loading_rate": 0.06,
  "loading_premium_kes": 517000,
  "gross_premium_kes": 1457000,
  "quoted_rate_pct_tiv": 11.67,
  "deductible_kes": 936000,
  "suggested_limit_kes": 8740000,
  "formula": "gross_premium = max(minimum_premium, AAL × (1 + risk_margin + expense_loading + commission_loading + profit_loading + reinsurance_loading))",
  "quote_source": "portfolio_building_id"
}
```

## 5. API endpoints to consume

These are the current contract endpoints the backend can call:

- `GET /health`
- `GET /formula`
- `GET /buildings`
- `GET /portfolio-summary`
- `GET /metrics`
- `GET /quote/<building_id>`
- `GET /quote-by-name`
- `POST /quote`

### `POST /quote` request examples

Stored building lookup:

```json
{
  "building_id": "NBO-0316"
}
```

Name-based lookup:

```json
{
  "building_name": "Kencom House",
  "city": "Nairobi",
  "country": "Kenya"
}
```

Manual underwriting inputs:

```json
{
  "building_name": "Landmark Plaza Commercial Development",
  "tiv_kes": 522650000,
  "expected_annual_loss_kes": 41030248.46,
  "risk_class": "very_high",
  "confidence": "medium"
}
```

Coordinate fallback:

```json
{
  "building_name": "Landmark Plaza Commercial Development",
  "latitude": -1.2847,
  "longitude": 36.8247
}
```

## 6. Pricing formula contract

The pricing logic is defined in `src/pricing.py` and must stay centralized there.

Formula:

```text
gross_premium = max(minimum_premium, AAL × (1 + risk_margin + expense_loading + commission_loading + profit_loading + reinsurance_loading))
```

Commercial rules:

- deductible is based on risk class and TIV
- suggested limit is proportional to TIV
- confidence adds a small risk-margin adjustment
- the minimum premium is enforced

## 7. AI/LLM separation rule

The LLM or Groq summarizer is not part of the calculation engine and must not be used to derive:

- AAL
- risk score
- risk class
- premium values
- deductible or limit values
- pricing formula output

The LLM may be used only for:

- narrative summaries
- underwriting briefing notes
- explanations in plain language
- follow-up question support

## 8. Recommended backend workflow for future uploaded datasets

For a future uploaded dataset, the recommended flow is:

1. dashboard uploads file
2. backend validates the file and schema
3. backend maps columns to the model schema
4. backend invokes the model pipeline
5. model returns risk and quote outputs
6. backend stores job metadata and results
7. optional LLM summary explains the result for users
8. dashboard displays the result set

This keeps the model deterministic and auditable while the dashboard remains a front-end integration layer.

## 9. Key principle

The model is the source of truth for technical risk and commercial pricing. The backend is the orchestrator. The dashboard is the presentation layer. The LLM is the explanation layer.

No part of the calculation engine should be moved into the Groq or dashboard workflow.
