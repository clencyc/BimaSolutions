# Interpretation API Integration - Quick Start

## 5-Minute Setup

### 1. Configure Environment

Add to your `.env` file:

```bash
# For local development
INTERPRETATION_API_BASE_URL=http://localhost:5001

# For production with ngrok
INTERPRETATION_API_BASE_URL=https://xxxx-xxx-xxx-xxx.ngrok-free.app
```

### 2. Start the Interpretation Service

From the interpretation API project directory:

```bash
source .venv/bin/activate
python -m src.interpretation_api
```

### 3. Test the Integration

Use curl to verify the proxy is working:

```bash
# Get an auth token first
TOKEN=$(curl -X POST http://localhost:8000/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username":"your_user","password":"your_pass"}' | jq -r '.access')

# Test health check
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/interpretation/health/

# Test summary
curl -X POST http://localhost:8000/api/interpretation/summary/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "portfolio_summary": {
      "portfolio_aal_kes": {"ml_augmented": 607333848.44}
    },
    "building_risk_summary": [
      {"building_id": "NBO-0316", "risk_score": 87.4},
      {"building_id": "NBO-1042", "risk_score": 81.2}
    ]
  }'
```

---

## Using the High-Level Client

In your views, use the convenience functions:

```python
from backendapi.interpretation_service import get_summary, answer_question

@api_view(['POST'])
def my_view(request):
    # Get a summary
    summary = get_summary(request.data['model_output'])
    return Response({'summary': summary['summary']})
    
    # Answer a question
    answer = answer_question(
        question="Which building has the highest risk?",
        context=request.data['context']
    )
    return Response({'answer': answer['answer']})
```

---

## Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/interpretation/health/` | Health check |
| POST | `/api/interpretation/summary/` | Generate summary from model output |
| POST | `/api/interpretation/question/` | Answer questions about model output |

---

## Troubleshooting

### "Interpretation service is unavailable"

```bash
# Check if the service is running
curl http://localhost:5001/health

# Check the configured URL
grep INTERPRETATION_API_BASE_URL .env

# If using ngrok, verify the URL is still active (URLs expire after 2 hours)
ngrok http 5001  # Get a new URL
```

### Timeout errors

Increase the timeout in your `.env` or code:

```python
from backendapi.interpretation_service import get_summary
result = get_summary(model_output, timeout=60)  # 60 seconds
```

---

## Next Steps

1. ✅ See [`INTERPRETATION_API_INTEGRATION.md`](./INTERPRETATION_API_INTEGRATION.md) for full documentation
2. ✅ See [`examples.py`](./backendapi/examples.py) for integration patterns
3. ✅ Run tests: `python manage.py test backendapi.tests.InterpretationApiProxyTests`
4. ✅ Check logs: `tail -f logs/django.log`

---

## Key Differences: Model API vs Interpretation API

| Function | Model API | Interpretation API |
|----------|-----------|-------------------|
| Risk Score Calculation | ✅ | ❌ |
| AAL Calculation | ✅ | ❌ |
| Premium Calculation | ✅ | ❌ |
| Plain-Language Summary | ❌ | ✅ |
| Q&A | ❌ | ✅ |
| Narrative Reporting | ❌ | ✅ |

**Important:** Always use the Model API for calculations, and use the Interpretation API only for explanations and insights.

