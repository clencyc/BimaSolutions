# Interpretation API Integration Guide

## Overview

The Interpretation API is a separate interpretation-only layer for providing plain-language insights and explanations based on model output. It is **NOT** for calculations.

### Intended Use Cases
✅ Plain-language summaries of model output
✅ Follow-up question answering
✅ Underwriting-friendly explanations
✅ Narrative reporting based on already-calculated results

### NOT Intended For
❌ Calculating risk scores
❌ Calculating AAL (Average Annual Loss)
❌ Calculating premium
❌ Calculating loss or EP curve values
❌ Generating formulas

---

## Setup

### 1. Environment Configuration

Update your `.env` file with the Interpretation API URL:

```bash
# Local development (Interpretation service running on port 5001)
INTERPRETATION_API_BASE_URL=http://localhost:5001

# Production with ngrok
INTERPRETATION_API_BASE_URL=https://xxxx-xxx-xxx-xxx.ngrok-free.app
```

### 2. Start the Interpretation Service

From the Interpretation API project directory:

```bash
source .venv/bin/activate
python -m src.interpretation_api
```

This runs on port `5001` by default.

### 3. (Optional) Expose with ngrok

```bash
ngrok http 5001
```

Copy the ngrok URL to `INTERPRETATION_API_BASE_URL` in your `.env`.

---

## API Endpoints

All endpoints require authentication (`IsAuthenticated` permission class).

### Health Check

**Endpoint:** `GET /api/interpretation/health/`

**Description:** Verify the Interpretation service is running.

**Example:**
```bash
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/interpretation/health/
```

**Response:**
```json
{
  "status": "ok",
  "service": "interpretation_only"
}
```

---

### Summary Endpoint

**Endpoint:** `POST /api/interpretation/summary/`

**Description:** Generate plain-language summary from model output.

**Request Body:**
```json
{
  "portfolio_summary": {
    "portfolio_aal_kes": { "ml_augmented": 607333848.44 }
  },
  "building_risk_summary": [
    { "building_id": "NBO-0316", "risk_score": 87.4 },
    { "building_id": "NBO-1042", "risk_score": 81.2 }
  ]
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/interpretation/summary/ \
  -H "Authorization: Bearer <token>" \
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

**Response:**
```json
{
  "summary": "The portfolio shows elevated flood risk under the adopted model view.",
  "interpretation_only": true,
  "source": "groq"
}
```

---

### Question Endpoint

**Endpoint:** `POST /api/interpretation/question/`

**Description:** Answer natural-language questions about model output.

**Request Body:**
```json
{
  "question": "Which building appears to be the highest risk?",
  "context": {
    "building_risk_summary": [
      { "building_id": "NBO-0316", "risk_score": 87.4 },
      { "building_id": "NBO-1042", "risk_score": 81.2 }
    ]
  }
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/interpretation/question/ \
  -H "Authorization: Bearer <token>" \
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

**Response:**
```json
{
  "answer": "Based on the supplied model output, NBO-0316 appears to be the highest-risk building.",
  "interpretation_only": true,
  "source": "groq"
}
```

---

## Usage Example (Backend Integration)

### Python/Django View Example

```python
import requests
from django.conf import settings
from rest_framework.response import Response

def get_portfolio_insights(portfolio_data):
    """Generate insights for a portfolio."""
    api_url = f"{settings.INTERPRETATION_API_BASE_URL}/api/interpretation/summary"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_user_token()}"
    }
    
    try:
        response = requests.post(
            api_url,
            json=portfolio_data,
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": "Failed to get interpretation", "detail": str(e)}


def answer_underwriter_question(question, context):
    """Answer an underwriter's question about the portfolio."""
    api_url = f"{settings.INTERPRETATION_API_BASE_URL}/api/interpretation/question"
    
    payload = {
        "question": question,
        "context": context
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_user_token()}"
    }
    
    try:
        response = requests.post(
            api_url,
            json=payload,
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": "Failed to answer question", "detail": str(e)}
```

---

## Architecture Separation

```
┌─────────────────────┐
│   Frontend App      │
└──────────┬──────────┘
           │
     ┌─────┴─────┐
     │           │
     ▼           ▼
┌──────────┐  ┌────────────────┐
│  Django  │  │  Django        │
│ Backend  │  │  Backend       │
└──────────┘  └────────────────┘
     │              │
     ├─ Calculations ├──→ Model API (port 5000+)
     │              │     - Risk scores
     │              │     - AAL calculation
     │              │     - Premiums
     │              │     - EP curves
     │              │
     └─ Explanations ───→ Interpretation API (port 5001)
                          - Summaries
                          - Q&A
                          - Narratives
                          - Insights
```

### Key Principles

1. **Separation of Concerns**: Model API handles calculations; Interpretation API handles explanations.
2. **Read-Only**: The Interpretation service never modifies data or performs calculations.
3. **Context Dependent**: Always provide full context (portfolio summary, building data, etc.) to the Interpretation API.
4. **Error Handling**: Both services may be unavailable; handle gracefully with fallback messaging.

---

## Error Handling

The proxy includes built-in error handling:

| HTTP Status | Meaning | Action |
|-------------|---------|--------|
| 502 Bad Gateway | Interpretation service unreachable | Retry or use cached insights |
| 502 Bad Gateway | Invalid JSON response | Check service logs |
| 401 Unauthorized | Missing/invalid token | Renew authentication |
| 400 Bad Request | Invalid payload | Validate request structure |

**Example Error Response:**
```json
{
  "detail": "Interpretation service is unavailable"
}
```

---

## Testing

Run the test suite:

```bash
python manage.py test backendapi.tests
```

Or test specific endpoints:

```bash
# Test health check
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/interpretation/health/

# Test summary
curl -X POST http://localhost:8000/api/interpretation/summary/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"portfolio_summary": {...}, "building_risk_summary": [...]}'

# Test question
curl -X POST http://localhost:8000/api/interpretation/question/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"question": "...", "context": {...}}'
```

---

## Troubleshooting

### Service Unavailable

```
{"detail": "Interpretation service is unavailable"}
```

**Solution:**
1. Verify the Interpretation service is running: `curl http://localhost:5001/health`
2. Check `INTERPRETATION_API_BASE_URL` in `.env` matches the service URL
3. If using ngrok, verify the URL is still active (ngrok URLs expire)

### Invalid Response

```
{
  "detail": "Interpretation service returned an invalid response",
  "upstream_status": 500
}
```

**Solution:**
1. Check the Interpretation service logs for errors
2. Verify the request payload matches the expected schema
3. Ensure all required fields are present

### Authentication Failed

```
{"detail": "Unauthorized"}
```

**Solution:**
1. Verify the JWT token is valid and not expired
2. Include the token in the `Authorization: Bearer <token>` header

---

## Performance Considerations

- **Timeout:** Default 30 seconds (configurable in `interpretation_api.py`)
- **Caching:** Consider caching summaries for frequently-accessed portfolios
- **Batch Requests:** Send multiple buildings at once to reduce API calls
- **Rate Limiting:** The Interpretation service may rate-limit requests; implement retry logic

---

## Next Steps

1. ✅ Configure `INTERPRETATION_API_BASE_URL` in `.env`
2. ✅ Start the Interpretation service
3. ✅ Test endpoints with curl or Postman
4. ✅ Integrate into frontend views
5. ✅ Add error handling and user feedback
6. ✅ Monitor performance and logs

