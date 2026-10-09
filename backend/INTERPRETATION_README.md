# Interpretation API Integration

## Overview

This integration connects your Django backend to the BimaSolutions **Interpretation API**, a separate service for generating plain-language insights and explanations based on model output.

### What's Included

✅ **Proxy Layer** (`interpretation_api.py`) - DRF endpoints that forward requests to the Interpretation service
✅ **Client Library** (`interpretation_service.py`) - High-level Python functions for easy integration
✅ **Comprehensive Docs** - Full integration guides, examples, and troubleshooting
✅ **Test Suite** - Pre-written tests validating all endpoints
✅ **Example Views** - Real-world usage patterns for your application

---

## Quick Start (2 minutes)

### 1. Configure the API URL

Edit `.env`:
```bash
INTERPRETATION_API_BASE_URL=http://localhost:5001
```

### 2. Start the Interpretation Service

In another terminal (from the interpretation API project):
```bash
python -m src.interpretation_api
```

### 3. Use in Your Views

```python
from backendapi.interpretation_service import get_summary

@api_view(['POST'])
def my_view(request):
    result = get_summary(request.data['model_output'])
    return Response({'summary': result['summary']})
```

---

## Architecture

```
Your Frontend
     │
     ▼
┌─────────────────────────────┐
│   Django Backend (Port 8000)│
├─────────────────────────────┤
│  Proxy Endpoints:           │
│  • /api/interpretation/...  │
└──────────┬──────────────────┘
           │
     ┌─────┴──────────────────┬──────────────┐
     │                        │              │
     │ Calculations           │ Explanations │
     ▼                        ▼              ▼
┌──────────────┐      ┌──────────────────────────────┐
│ Model API    │      │ Interpretation API (Port 5001)│
│ (Port 5000+) │      ├──────────────────────────────┤
├──────────────┤      │ • Plain-language summaries   │
│ • Risk       │      │ • Q&A answers                │
│ • AAL        │      │ • Narrative reporting        │
│ • Premium    │      │ • Underwriter insights       │
│ • EP curves  │      └──────────────────────────────┘
└──────────────┘
```

---

## Files & Documentation

### Core Integration Files
- **`backendapi/interpretation_api.py`** - DRF proxy views
- **`backendapi/interpretation_service.py`** - High-level client library
- **`backendapi/examples.py`** - Real-world usage examples

### Documentation
- **`INTERPRETATION_QUICK_START.md`** - Get up & running in 5 minutes
- **`INTERPRETATION_API_INTEGRATION.md`** - Comprehensive integration guide
- **`INTERPRETATION_README.md`** - This file

### Tests
- **`backendapi/tests.py`** - Test suite (3 tests for Interpretation API)

Run tests:
```bash
python manage.py test backendapi.tests.InterpretationApiProxyTests -v 2
```

---

## API Endpoints

All endpoints require authentication (`Authorization: Bearer <token>` header).

### 1. Health Check
```bash
GET /api/interpretation/health/
```
Verify the Interpretation service is running.

### 2. Generate Summary
```bash
POST /api/interpretation/summary/

Request:
{
  "portfolio_summary": {
    "portfolio_aal_kes": {"ml_augmented": 607333848.44}
  },
  "building_risk_summary": [
    {"building_id": "NBO-0316", "risk_score": 87.4},
    {"building_id": "NBO-1042", "risk_score": 81.2}
  ]
}

Response:
{
  "summary": "The portfolio shows elevated flood risk under the adopted model view.",
  "interpretation_only": true,
  "source": "groq"
}
```

### 3. Answer Questions
```bash
POST /api/interpretation/question/

Request:
{
  "question": "Which building has the highest risk?",
  "context": {
    "building_risk_summary": [
      {"building_id": "NBO-0316", "risk_score": 87.4},
      {"building_id": "NBO-1042", "risk_score": 81.2}
    ]
  }
}

Response:
{
  "answer": "Based on the supplied model output, NBO-0316 appears to be the highest-risk building.",
  "interpretation_only": true,
  "source": "groq"
}
```

---

## High-Level Client Library

### Functions

#### `get_summary(model_output, timeout=30)`
Generate plain-language summary from model calculations.

```python
from backendapi.interpretation_service import get_summary

result = get_summary({
    "portfolio_summary": {...},
    "building_risk_summary": [...]
})
print(result['summary'])
```

#### `answer_question(question, context, timeout=30)`
Answer underwriter questions about model output.

```python
from backendapi.interpretation_service import answer_question

result = answer_question(
    question="Which building appears to be the highest risk?",
    context={"building_risk_summary": [...]}
)
print(result['answer'])
```

#### `check_health(timeout=5)`
Check if the Interpretation service is healthy.

```python
from backendapi.interpretation_service import check_health

if check_health():
    print("Service is available")
else:
    print("Service is down")
```

### Error Handling

All client functions raise `InterpretationServiceError` on failure:

```python
from backendapi.interpretation_service import get_summary, InterpretationServiceError

try:
    result = get_summary(model_output)
except InterpretationServiceError as e:
    print(f"Service error: {e}")
    # Handle gracefully - use fallback or cached result
```

---

## Common Patterns

### Pattern 1: Summary After Model Calculation

```python
@api_view(['POST'])
def calculate_and_summarize(request):
    # Run model
    model_result = call_model_api(request.data['portfolio_id'])
    
    # Get interpretation
    try:
        interpretation = get_summary(model_result)
        return Response({
            'model_run_id': model_result['run_id'],
            'summary': interpretation['summary'],
        })
    except InterpretationServiceError:
        return Response({
            'model_run_id': model_result['run_id'],
            'summary': 'Model calculation complete. Interpretation unavailable.',
        })
```

### Pattern 2: Caching Results

```python
from django.core.cache import cache
import hashlib, json

cache_key = f"summary_{hashlib.md5(json.dumps(model_output).encode()).hexdigest()}"
cached = cache.get(cache_key)
if cached:
    return cached
    
result = get_summary(model_output)
cache.set(cache_key, result, 3600)  # Cache for 1 hour
return result
```

### Pattern 3: Graceful Degradation

```python
try:
    result = get_summary(model_output)
except InterpretationServiceError:
    # Fall back to generic message
    result = {
        'summary': 'Portfolio has been modeled. Contact support for detailed interpretation.',
        'source': 'fallback',
    }
return result
```

### Pattern 4: Batch Processing

```python
def batch_interpret(portfolios):
    results = []
    for portfolio in portfolios:
        try:
            result = get_summary(portfolio['model_output'])
            results.append({'id': portfolio['id'], 'summary': result['summary']})
        except InterpretationServiceError:
            results.append({'id': portfolio['id'], 'error': 'Service unavailable'})
    return results
```

---

## Configuration

### Environment Variables

```bash
# Default: http://localhost:5001
# Set to ngrok URL for production
INTERPRETATION_API_BASE_URL=https://xxxx-xxx-xxx-xxx.ngrok-free.app
```

### Django Settings

The setting is loaded in `backendapi/settings.py`:

```python
INTERPRETATION_API_BASE_URL = os.environ.get(
    'INTERPRETATION_API_BASE_URL',
    'http://localhost:5001'
)
```

---

## Troubleshooting

### Service Unavailable

```
{"detail": "Interpretation service is unavailable"}
```

**Check:**
1. Is the service running? `curl http://localhost:5001/health`
2. Is the URL correct? Check `.env` for `INTERPRETATION_API_BASE_URL`
3. If using ngrok, is the URL still active? (URLs expire)

### Timeout

**Solution:** Increase timeout
```python
get_summary(model_output, timeout=60)
```

### Invalid Response

**Check:** Interpretation service logs for errors
```bash
tail -f logs/interpretation_api.log
```

### Authentication Failed

**Solution:** Verify JWT token is valid and included in header
```bash
Authorization: Bearer <your_valid_token>
```

---

## Testing

### Run Full Test Suite

```bash
python manage.py test backendapi.tests.InterpretationApiProxyTests -v 2
```

### Test Individual Endpoints

```bash
# Health check
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/interpretation/health/

# Summary
curl -X POST http://localhost:8000/api/interpretation/summary/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"portfolio_summary": {...}, "building_risk_summary": [...]}'

# Question
curl -X POST http://localhost:8000/api/interpretation/question/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "...", "context": {...}}'
```

---

## Important Design Principles

### 🚫 NOT for Calculations

❌ Do NOT use the Interpretation API for:
- Risk score calculations
- AAL (Average Annual Loss) calculations
- Premium calculations
- Loss or EP curve generation
- Formula generation

✅ Use the **Model API** for these.

### ✅ FOR Plain-Language Insights

✅ DO use the Interpretation API for:
- Plain-language summaries of model output
- Follow-up question answering based on model data
- Underwriting-friendly explanations
- Narrative reporting based on calculated results

### 🔄 Always Provide Full Context

Always pass complete model output to the Interpretation API. Don't summarize or filter the data first—let the service handle it.

```python
# Good: Pass all relevant data
get_summary({
    "portfolio_summary": {...},
    "building_risk_summary": [...]
})

# Bad: Don't filter
get_summary({"summary": model_result['summary']})
```

---

## Performance Notes

- **Timeout:** Default 30 seconds (configurable)
- **Rate Limiting:** May apply; implement retry logic if needed
- **Caching:** Consider caching results for frequently-accessed portfolios
- **Batch:** Send multiple buildings at once to reduce API calls

---

## Security

- All endpoints require authentication (`IsAuthenticated` permission)
- Tokens are passed in `Authorization: Bearer <token>` header
- The proxy includes error handling to avoid leaking sensitive information
- No credentials are stored in code (use `.env` for configuration)

---

## Next Steps

1. ✅ Read [`INTERPRETATION_QUICK_START.md`](./INTERPRETATION_QUICK_START.md) for 5-minute setup
2. ✅ Review [`examples.py`](./backendapi/examples.py) for real-world patterns
3. ✅ Read [`INTERPRETATION_API_INTEGRATION.md`](./INTERPRETATION_API_INTEGRATION.md) for full details
4. ✅ Run tests: `python manage.py test backendapi.tests.InterpretationApiProxyTests`
5. ✅ Integrate into your views and frontend

---

## Support & Debugging

### Logs

Check Django logs for detailed error information:
```bash
tail -f logs/django.log
```

### Enable Debug Logging

In your Django settings:
```python
LOGGING = {
    'loggers': {
        'backendapi.interpretation_api': {
            'level': 'DEBUG',
        }
    }
}
```

### Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| Service unavailable | Check if it's running: `curl http://localhost:5001/health` |
| Timeout | Increase timeout parameter: `get_summary(..., timeout=60)` |
| Invalid request | Validate payload structure matches API schema |
| 502 Bad Gateway | Interpretation service returned invalid JSON (check logs) |
| 401 Unauthorized | Token missing or expired (include `Authorization` header) |

---

## Version Info

- **Integration Version:** 1.0
- **Interpretation API:** Compatible with [interpretation API service]
- **Django:** 6.1+
- **Python:** 3.9+

---

## License & Attribution

This integration is part of the BimaSolutions platform.

```
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```

---

## FAQ

**Q: Can I use Interpretation API for risk calculations?**
A: No. Use the Model API for calculations. Interpretation API is for explanations only.

**Q: What if the Interpretation service is down?**
A: Implement graceful degradation—return generic messages or cached results.

**Q: How do I cache results?**
A: Use Django's cache framework with a hash of the model output as the key.

**Q: Can I batch multiple portfolios?**
A: Yes, see Pattern 4 in the Common Patterns section.

**Q: How do I debug issues?**
A: Check Django logs, verify the service is running, and use curl to test endpoints directly.

---

## Thank You

For issues, questions, or feature requests, please reach out to your BimaSolutions team.

