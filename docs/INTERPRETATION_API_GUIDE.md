# Interpretation API Guide

This API is a separate interpretation-only layer for the dashboard. It is intentionally not the model/calculation endpoint.

## Purpose

This service should be used only for:

- plain-language summaries of model output
- follow-up question answering
- underwriting-friendly explanations
- narrative reporting based on already-calculated results

It should not be used for:

- calculating risk scores
- calculating AAL
- calculating premium
- calculating loss or EP curve values
- generating formulas
- replacing the deterministic model layer

## Running the service

From the project root:

```bash
source .venv/bin/activate
python -m src.interpretation_api
```

By default this runs on port `5001`.

If you want to expose it publicly with ngrok:

```bash
ngrok http 5001
```

## Health check

```bash
curl http://127.0.0.1:5001/health
```

Example response:

```json
{
  "status": "ok",
  "service": "interpretation_only"
}
```

## Summary endpoint

### `POST /api/interpretation/summary`

This endpoint receives model output JSON and returns a plain-language summary.

Example request:

```bash
curl -X POST http://127.0.0.1:5001/api/interpretation/summary \
  -H "Content-Type: application/json" \
  -d '{
    "portfolio_summary": {
      "portfolio_aal_kes": { "ml_augmented": 607333848.44 }
    },
    "building_risk_summary": [
      { "building_id": "NBO-0316", "risk_score": 87.4 },
      { "building_id": "NBO-1042", "risk_score": 81.2 }
    ]
  }'
```

Example response:

```json
{
  "summary": "The portfolio shows elevated flood risk under the adopted model view.",
  "interpretation_only": true,
  "source": "groq"
}
```

## Question endpoint

### `POST /api/interpretation/question`

This endpoint accepts a question plus the relevant model output payload and returns an answer based on the provided data.

Example request:

```bash
curl -X POST http://127.0.0.1:5001/api/interpretation/question \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Which building appears to be the highest risk?",
    "context": {
      "building_risk_summary": [
        { "building_id": "NBO-0316", "risk_score": 87.4 },
        { "building_id": "NBO-1042", "risk_score": 81.2 }
      ]
    }
  }'
```

Example response:

```json
{
  "answer": "Based on the supplied model output, NBO-0316 appears to be the highest-risk building.",
  "interpretation_only": true,
  "source": "groq"
}
```

## Separation rule

This interpretation API is separate from the model API:

- model API: risk, loss, EP curve, quote calculation
- interpretation API: explanation and follow-up answer only

The interpretation API should never be used as the source of truth for calculations.
