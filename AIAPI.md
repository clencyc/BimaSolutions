# Flood Model API — Frontend Integration

The Django backend proxies the model API so frontend code can use the Django
backend's origin and does not need to call the ngrok service directly.

## Backend setup

Set `FLOOD_MODEL_API_BASE_URL` in the Django backend environment:

```text
FLOOD_MODEL_API_BASE_URL=https://309a-165-90-19-21.ngrok-free.app
```

This is the current ngrok tunnel URL and may change when the model API tunnel
restarts. The backend defaults to this URL if the environment variable is not
set. Restart Django after changing it.

The Django process must be able to reach the model API. Its requests include
ngrok's `ngrok-skip-browser-warning` header.

## Frontend base URL and authentication

Use the deployed Django backend's own base URL, not the ngrok model URL. For
local development this is usually `http://127.0.0.1:8000`.

First obtain a Django JWT by posting the user's email and password to
`/auth/login/`:

```http
POST /auth/login/
Content-Type: application/json

{"email":"user@example.com","password":"..."}
```

The login response contains `access` and `refresh`. All model proxy endpoints
below require the access token:

```http
Authorization: Bearer <access>
```

The model API itself does not receive or validate the user's JWT; authentication
is enforced by Django before it proxies the request.

## Model endpoints

All successful responses are JSON; monetary values are in Kenyan shillings
(KES). Paths below are relative to the Django backend base URL and include a
trailing slash.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/model/health/` | Check model service availability |
| `GET` | `/api/model/buildings/` | Get results for all buildings |
| `GET` | `/api/model/portfolio-summary/` | Get portfolio-wide exposure and loss results |
| `GET` | `/api/model/metrics/` | Get validation and training metrics |
| `GET` | `/api/model/formula/` | Get premium formula and assumptions |
| `POST` | `/api/model/extract/` | Extract building data with Groq and run the flood model |
| `GET` | `/api/model/quote/{building_id}/` | Quote using a building's model result |
| `POST` | `/api/model/quote/` | Quote from supplied model inputs |

### `POST /api/model/extract/`

Accepts unstructured text/JSON in `data`, or a base64-encoded PDF/image in
`document`. The Django backend calls Groq directly for flexible,
document-specific extraction; it does not assume every input is already an
exposure spreadsheet. It returns a document type, summary, structured
`extracted_data`, and any candidate building `extracted_rows`. If all candidate
rows contain valid model inputs, Django sends those rows to the flood model
service and includes `model_run`. Otherwise, extraction still succeeds and
`model_run` is `null`, with missing/invalid fields reported in
`model_readiness.issues`. The model service does not perform extraction.

Text or JSON request:

```json
{
  "portfolio_name": "Client assets",
  "data": "Building B-1, Kibera, latitude -1.29, longitude 36.82, masonry, insured for KES 1,000,000. Hazard scores: 0.2, 0.3, 0.4, 0.5, 0.6."
}
```

PDF request:

```json
{
  "portfolio_name": "Client assets",
  "document": {
    "mime_type": "application/pdf",
    "data_base64": "<base64-encoded document>"
  }
}
```

PDF documents are limited to 20 MiB. The backend extracts selectable PDF text
before sending it to Groq; scanned/image-only PDFs require OCR first. The flood model
requires a building ID, coordinates, neighbourhood, supported construction
class, insured value in KES, and at least one hazard score (0–1) per row.
Missing values are never invented or inferred from qualitative descriptions;
when model fields are absent, the document extraction is still returned and
the model is not run. Other errors include `503` when Groq is not configured
or temporarily unavailable, and `502` when it rejects the request or returns
an invalid response.

Set `GROQ_API_KEY` in the **Django backend's** environment. Optionally set
`GROQ_MODEL` there to override the default `llama-3.3-70b-versatile`. Never send the
Groq key from the frontend. Django enforces JWT authentication and forwards
only validated rows to the flood model service.

### `GET /api/model/buildings/`

Returns a JSON array. Each building currently includes:

```json
{
  "building_id": "NBO-0316",
  "housing_class": "concrete_rcc",
  "tiv_kes": 522650000.0,
  "expected_annual_loss_kes": 41030248.4560233,
  "aal_rate": 0.0785042541969258,
  "risk_score": 97.0,
  "risk_class": "very_high",
  "confidence": "medium"
}
```

The live dataset currently contains 600 building records.

### `GET /api/model/portfolio-summary/`

Important fields include `n_buildings`, `total_exposure_kes`,
`portfolio_aal_kes`, `loss_by_return_period_kes`, `buildings_with_hazard`,
`confidence_counts`, and `hazard_source_counts`.

Model variants currently include `baseline_proxy`, `proxy_plus_hotspots`, and
`ml_augmented`. Treat these as separate estimates; do not add them together.

### `GET /api/model/metrics/`

Returns nested validation data, including `selected_model`,
`cross_validation`, `hotspot_level`, `tier_thresholds`, and
`representative_depths_m`. Render nested metrics dynamically rather than
assuming a fixed list of model names.

### `GET /api/model/formula/`

Returns `pricing_formula` and `assumptions`. Use the returned assumptions in
the UI rather than hard-coding pricing factors.

### `GET /api/model/quote/{building_id}/`

Example:

```http
GET /api/model/quote/NBO-0316/
```

The response includes the building's TIV, AAL, risk class, confidence,
technical and gross premium, loading rates, quoted rate, deductible, suggested
limit, formula, and assumptions.

### `POST /api/model/quote/`

Request:

```json
{
  "tiv_kes": 522650000,
  "expected_annual_loss_kes": 41030248.46,
  "risk_class": "very_high",
  "confidence": "medium"
}
```

`risk_class` accepts `negligible`, `low`, `medium`, `high`, or `very_high`.
`confidence` accepts `low`, `medium`, or `high`. The response contains the
same quote fields as the building quote endpoint.

## JavaScript example

```js
const API_BASE_URL = "http://127.0.0.1:8000"; // Set to the Django backend URL.

async function getModelBuildings(accessToken) {
  const response = await fetch(`${API_BASE_URL}/api/model/buildings/`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) {
    throw new Error(`Model API returned HTTP ${response.status}`);
  }
  return response.json();
}

async function getBuildingQuote(accessToken, buildingId) {
  const response = await fetch(
    `${API_BASE_URL}/api/model/quote/${encodeURIComponent(buildingId)}/`,
    { headers: { Authorization: `Bearer ${accessToken}` } }
  );
  if (!response.ok) {
    throw new Error(`Model API returned HTTP ${response.status}`);
  }
  return response.json();
}
```

## Errors and operational notes

- Django returns `401` when the access token is missing or invalid.
- A model service connection failure or invalid response returns `502`.
- Valid JSON error responses from the model service preserve their HTTP status.
- The ngrok URL is a development/demo tunnel, not a stable production hostname.
- Model results support underwriting decisions; final approval remains with
  the underwriter.
