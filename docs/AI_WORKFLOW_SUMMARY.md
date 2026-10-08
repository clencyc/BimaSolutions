# AI Workflow Summary

This repository contains the AI/ML and risk-calculation layer for the Nairobi flood-risk model. The backend, API hosting, and UI integration are handled by another team and are intentionally kept separate from the model logic.

## Scope boundary

This project is responsible for:

- data validation and feature preparation
- hazard scoring and hotspot detection
- vulnerability and loss modelling
- portfolio risk outputs
- commercial pricing formula and quote generation
- machine-readable outputs for downstream consumption

This project is not responsible for:

- the main backend application layer
- authentication, user sessions, or RBAC
- database persistence and jobs orchestration
- dashboard UI rendering
- final approvals or underwriting workflow rules outside the model contract

The model outputs are exposed as clean data and API contracts so the backend team can call them without needing the ML logic itself.

## End-to-end workflow

### 1. Data intake

The model starts from the Nairobi portfolio and hazard datasets, including:

- exposure building data
- hazard proxy rasters
- known hotspot locations
- synthetic insurance values and property characteristics

For a future uploaded dataset, the expected flow is:

- upload a new CSV or dataset file in the dashboard
- validation and schema checking on the backend side
- column mapping to the model's expected fields
- pass the normalized dataset to the model pipeline
- receive outputs and summary results

Important: the calculation itself stays inside the model layer; the dashboard/backend should only pass data and consume results.

### 2. Exposure preparation

The exposure layer standardizes the property record set and ensures the required fields exist, such as:

- building identifier
- latitude and longitude
- housing class
- floor area
- total insured value (`tiv_kes`)
- hazard features and synthetic flags

This stage turns raw portfolio data into the model-ready structure used by the hazard and risk engine.

### 3. Hazard scoring

The model computes hazard intensity using a layered approach:

- terrain-based flood susceptibility proxy
- known hotspot proximity signal
- ML hotspot uplift signal when justified by available features

The model then calculates a building-level susceptibility measure and identifies which hazard source contributed most to the result.

### 4. Vulnerability and loss calculation

For every scenario, the model:

- maps flood depth to a damage ratio
- adjusts by construction class
- multiplies damage ratio by total insured value
- aggregates losses across scenarios
- produces expected annual loss and portfolio exceedance metrics

This stage is deterministic and is the core of the financial model.

### 5. Portfolio outputs

The model writes machine-readable outputs such as:

- risk predictions
- building risk summaries
- EP curve data
- hotspot validation data
- feature importance data
- vulnerability curves and matrix
- portfolio summary values

These outputs are the evidence base for underwriters, analysts, and dashboard consumers.

### 6. Commercial pricing layer

The pricing layer is separate from the ML pipeline but uses model inputs such as:

- `tiv_kes`
- `expected_annual_loss_kes`
- `risk_class`
- `confidence`

The quote logic calculates:

- technical premium
- risk margin
- expense loading
- commission loading
- profit loading
- reinsurance loading
- deductible
- suggested limit

The formula is deterministic and kept inside the model layer.

### 7. API contract for downstream systems

The model exposes a contract that the backend/dashboard can call without access to the internal modelling logic. Examples include:

- `GET /health`
- `GET /formula`
- `GET /buildings`
- `GET /portfolio-summary`
- `GET /metrics`
- `GET /quote/<building_id>`
- `GET /quote-by-name`
- `POST /quote`

This is the integration boundary:

- backend team: receives data, orchestrates requests, handles app concerns
- model team: provides outputs, formulas, quote logic, AI-scored risk results

### 8. AI-generated summary layer

The Groq/LLM component is used only for:

- narrative summaries
- report generation explanation
- follow-up question support
- user-friendly business interpretation

It is not used to calculate:

- premiums
- risk scores
- expected annual loss
- EP curves
- formula logic

This separation is important. The model remains the source of truth; the LLM is only a communication layer.

## Responsibility matrix

| Concern | AI/ML model team | Backend team | Dashboard team |
|---|---|---|---|
| Data cleaning and schema mapping | Yes | May support | May support |
| Hazard and vulnerability modelling | Yes | No | No |
| Pricing formula | Yes | No | No |
| API contract design | Yes | Coordinates with team | Consumes |
| Application runtime and hosting | No | Yes | No |
| Database and storage | No | Yes | No |
| UI rendering | No | No | Yes |
| Narrative summarization | Optional AI layer | May integrate | Uses output |

## Recommended future ingestion flow

For future uploaded datasets, the recommended architecture is:

1. backend receives uploaded file
2. backend validates file structure and required columns
3. backend maps raw columns to the model schema
4. backend calls the model pipeline with normalized data
5. model computes outputs and returns risk and pricing results
6. backend stores job metadata and results
7. optional LLM summary explains the result for the underwriter
8. dashboard displays the outputs and quote details

This keeps model calculations inside the model component and avoids mixing formula logic with LLM interpretation.

## Final design principle

The AI model should remain the deterministic source of truth for flood risk and pricing. The backend and dashboard are responsible for application flow, user experience, and data handling. The LLM is an explanatory layer only, never the calculation engine.
