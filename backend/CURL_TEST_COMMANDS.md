# Curl Commands for Testing Interpretation API Integration

## 📋 Prerequisites

```bash
# Store your credentials
BACKEND_URL="http://localhost:8000"
USERNAME="your_username"
PASSWORD="your_password"
```

---

## 🔐 Step 1: Get Authentication Token

### Get JWT Token
```bash
TOKEN=$(curl -s -X POST $BACKEND_URL/auth/token/ \
  -H "Content-Type: application/json" \
  -d "{
    \"username\": \"$USERNAME\",
    \"password\": \"$PASSWORD\"
  }" | jq -r '.access')

echo "Token: $TOKEN"
```

### Store Token for Reuse
```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username":"your_username","password":"your_password"}' | jq -r '.access')

# Verify token was obtained
echo "Using token: ${TOKEN:0:20}..."
```

---

## ✅ Test 1: Health Check

### Simple Health Check (No Auth)
```bash
curl -v http://localhost:5001/health
```

### Health Check Through Proxy (With Auth)
```bash
curl -X GET http://localhost:8000/api/interpretation/health/ \
  -H "Authorization: Bearer $TOKEN"
```

### Expected Response
```json
{
  "status": "ok",
  "service": "interpretation_only"
}
```

---

## ✅ Test 2: Summary Endpoint

### Generate Summary from Portfolio Data
```bash
curl -X POST http://localhost:8000/api/interpretation/summary/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "portfolio_summary": {
      "portfolio_aal_kes": {
        "ml_augmented": 607333848.44
      }
    },
    "building_risk_summary": [
      {
        "building_id": "NBO-0316",
        "risk_score": 87.4
      },
      {
        "building_id": "NBO-1042",
        "risk_score": 81.2
      }
    ]
  }'
```

### With Pretty Print (requires jq)
```bash
curl -s -X POST http://localhost:8000/api/interpretation/summary/ \
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
  }' | jq '.'
```

### Save Response to File
```bash
curl -s -X POST http://localhost:8000/api/interpretation/summary/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "portfolio_summary": {"portfolio_aal_kes": {"ml_augmented": 607333848.44}},
    "building_risk_summary": [
      {"building_id": "NBO-0316", "risk_score": 87.4}
    ]
  }' > summary_response.json

cat summary_response.json | jq '.'
```

### Expected Response
```json
{
  "summary": "The portfolio shows elevated flood risk under the adopted model view.",
  "interpretation_only": true,
  "source": "groq"
}
```

---

## ✅ Test 3: Question Endpoint

### Ask a Question About Buildings
```bash
curl -X POST http://localhost:8000/api/interpretation/question/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Which building appears to be the highest risk?",
    "context": {
      "building_risk_summary": [
        {"building_id": "NBO-0316", "risk_score": 87.4},
        {"building_id": "NBO-1042", "risk_score": 81.2}
      ]
    }
  }'
```

### Ask About AAL
```bash
curl -s -X POST http://localhost:8000/api/interpretation/question/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is the Average Annual Loss for this portfolio?",
    "context": {
      "portfolio_summary": {
        "portfolio_aal_kes": {"ml_augmented": 607333848.44}
      }
    }
  }' | jq '.'
```

### Ask About Risk Distribution
```bash
curl -X POST http://localhost:8000/api/interpretation/question/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "How is the risk distributed across the portfolio?",
    "context": {
      "building_risk_summary": [
        {"building_id": "NBO-0316", "risk_score": 87.4, "insured_value": 5000000},
        {"building_id": "NBO-1042", "risk_score": 81.2, "insured_value": 3000000},
        {"building_id": "NBO-2001", "risk_score": 42.1, "insured_value": 2000000}
      ]
    }
  }'
```

### Expected Response
```json
{
  "answer": "Based on the supplied model output, NBO-0316 appears to be the highest-risk building.",
  "interpretation_only": true,
  "source": "groq"
}
```

---

## ❌ Test 4: Error Cases

### Missing Authentication Token
```bash
curl -X GET http://localhost:8000/api/interpretation/health/
```

**Expected Response:**
```json
{
  "detail": "Authentication credentials were not provided."
}
```

### Invalid Authentication Token
```bash
curl -X GET http://localhost:8000/api/interpretation/health/ \
  -H "Authorization: Bearer invalid_token_12345"
```

**Expected Response:**
```json
{
  "detail": "Given token not valid for any token type"
}
```

### Missing Required Fields in Summary
```bash
curl -X POST http://localhost:8000/api/interpretation/summary/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

### Missing Question in Question Endpoint
```bash
curl -X POST http://localhost:8000/api/interpretation/question/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "context": {"building_risk_summary": []}
  }'
```

### Service Unavailable (When Interpretation Service is Down)
```bash
# This will happen if the Interpretation service is not running
curl -X GET http://localhost:8000/api/interpretation/health/ \
  -H "Authorization: Bearer $TOKEN"
```

**Expected Response (502):**
```json
{
  "detail": "Interpretation service is unavailable"
}
```

---

## 🔄 Test 5: Complete Workflow

### Full End-to-End Test
```bash
#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

BACKEND_URL="http://localhost:8000"
USERNAME="your_username"
PASSWORD="your_password"

echo -e "${BLUE}1. Getting authentication token...${NC}"
TOKEN=$(curl -s -X POST $BACKEND_URL/auth/token/ \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"$USERNAME\", \"password\": \"$PASSWORD\"}" \
  | jq -r '.access')

if [ -z "$TOKEN" ] || [ "$TOKEN" == "null" ]; then
  echo -e "${RED}Failed to get token${NC}"
  exit 1
fi
echo -e "${GREEN}✓ Token obtained: ${TOKEN:0:20}...${NC}"

echo -e "\n${BLUE}2. Testing health check...${NC}"
HEALTH=$(curl -s -X GET $BACKEND_URL/api/interpretation/health/ \
  -H "Authorization: Bearer $TOKEN")
echo -e "${GREEN}✓ Health Check Response:${NC}"
echo "$HEALTH" | jq '.'

echo -e "\n${BLUE}3. Testing summary endpoint...${NC}"
SUMMARY=$(curl -s -X POST $BACKEND_URL/api/interpretation/summary/ \
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
  }')
echo -e "${GREEN}✓ Summary Response:${NC}"
echo "$SUMMARY" | jq '.'

echo -e "\n${BLUE}4. Testing question endpoint...${NC}"
QUESTION=$(curl -s -X POST $BACKEND_URL/api/interpretation/question/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Which building has the highest risk score?",
    "context": {
      "building_risk_summary": [
        {"building_id": "NBO-0316", "risk_score": 87.4},
        {"building_id": "NBO-1042", "risk_score": 81.2}
      ]
    }
  }')
echo -e "${GREEN}✓ Question Response:${NC}"
echo "$QUESTION" | jq '.'

echo -e "\n${GREEN}All tests completed!${NC}"
```

Save as `test_interpretation_api.sh` and run:
```bash
chmod +x test_interpretation_api.sh
./test_interpretation_api.sh
```

---

## 📊 Test 6: Performance & Load Testing

### Single Request with Timing
```bash
time curl -X POST http://localhost:8000/api/interpretation/summary/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "portfolio_summary": {"portfolio_aal_kes": {"ml_augmented": 607333848.44}},
    "building_risk_summary": [{"building_id": "NBO-0316", "risk_score": 87.4}]
  }' > /dev/null
```

### Multiple Requests (Stress Test)
```bash
for i in {1..10}; do
  curl -s -X POST http://localhost:8000/api/interpretation/summary/ \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "portfolio_summary": {"portfolio_aal_kes": {"ml_augmented": 607333848.44}},
      "building_risk_summary": [{"building_id": "NBO-0316", "risk_score": 87.4}]
    }' > /dev/null
  echo "Request $i completed"
done
```

### Measure Response Time with Headers
```bash
curl -w "\nTime: %{time_total}s\nHTTP Status: %{http_code}\n" \
  -X POST http://localhost:8000/api/interpretation/summary/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "portfolio_summary": {"portfolio_aal_kes": {"ml_augmented": 607333848.44}},
    "building_risk_summary": [{"building_id": "NBO-0316", "risk_score": 87.4}]
  }'
```

---

## 🔍 Test 7: Verbose & Debug Mode

### Show All Headers (Request & Response)
```bash
curl -v -X GET http://localhost:8000/api/interpretation/health/ \
  -H "Authorization: Bearer $TOKEN"
```

### Show Request Details Only
```bash
curl -v -X GET http://localhost:8000/api/interpretation/health/ \
  -H "Authorization: Bearer $TOKEN" 2>&1 | head -20
```

### Capture Full Request/Response
```bash
curl -i -X POST http://localhost:8000/api/interpretation/summary/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "portfolio_summary": {"portfolio_aal_kes": {"ml_augmented": 607333848.44}},
    "building_risk_summary": [{"building_id": "NBO-0316", "risk_score": 87.4}]
  }'
```

### Debug with curl trace
```bash
curl --trace-ascii /tmp/trace.txt \
  -X GET http://localhost:8000/api/interpretation/health/ \
  -H "Authorization: Bearer $TOKEN"

cat /tmp/trace.txt
```

---

## 🚀 Quick Test Script (Copy & Run)

```bash
#!/bin/bash
# quick_test.sh - Quick test of all endpoints

TOKEN=$(curl -s -X POST http://localhost:8000/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | jq -r '.access')

echo "Testing Health..."
curl -s http://localhost:8000/api/interpretation/health/ \
  -H "Authorization: Bearer $TOKEN" | jq '.'

echo "Testing Summary..."
curl -s -X POST http://localhost:8000/api/interpretation/summary/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"portfolio_summary":{"portfolio_aal_kes":{"ml_augmented":607333848.44}},"building_risk_summary":[{"building_id":"NBO-0316","risk_score":87.4}]}' | jq '.'

echo "Testing Question..."
curl -s -X POST http://localhost:8000/api/interpretation/question/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"Which building has the highest risk?","context":{"building_risk_summary":[{"building_id":"NBO-0316","risk_score":87.4}]}}' | jq '.'
```

---

## 📝 Using Postman Instead of Curl

### Postman Collection Setup

1. **Create New Collection** named "Interpretation API"

2. **Set Collection Variables:**
   - `base_url`: `http://localhost:8000`
   - `token`: (will be set by auth request)

3. **Add Requests:**

   **Request 1: Get Token**
   - Method: POST
   - URL: `{{base_url}}/auth/token/`
   - Body (JSON):
     ```json
     {
       "username": "your_username",
       "password": "your_password"
     }
     ```
   - Tests (Script):
     ```javascript
     var jsonData = pm.response.json();
     pm.collectionVariables.set("token", jsonData.access);
     ```

   **Request 2: Health Check**
   - Method: GET
   - URL: `{{base_url}}/api/interpretation/health/`
   - Headers: `Authorization: Bearer {{token}}`

   **Request 3: Summary**
   - Method: POST
   - URL: `{{base_url}}/api/interpretation/summary/`
   - Headers: `Authorization: Bearer {{token}}`
   - Body (JSON): [use the summary JSON from above]

   **Request 4: Question**
   - Method: POST
   - URL: `{{base_url}}/api/interpretation/question/`
   - Headers: `Authorization: Bearer {{token}}`
   - Body (JSON): [use the question JSON from above]

---

## 🐛 Troubleshooting

### Command Returns "command not found: jq"
```bash
# Install jq
sudo apt-get install jq  # Ubuntu/Debian
brew install jq           # macOS
```

### Token is Invalid
```bash
# Re-authenticate
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username":"your_username","password":"your_password"}' | jq -r '.access')

# Verify token
echo $TOKEN
```

### Connection Refused
```bash
# Make sure Django is running
python manage.py runserver

# Make sure Interpretation service is running (in another terminal)
python -m src.interpretation_api
```

### 502 Bad Gateway
```bash
# The Interpretation service might be down
curl http://localhost:5001/health

# If down, start it:
python -m src.interpretation_api
```

---

## 📋 Checklist for Complete Testing

- [ ] Obtained authentication token
- [ ] Health check passes (status: "ok")
- [ ] Summary endpoint returns summary and source
- [ ] Question endpoint returns answer
- [ ] Error handling works (missing auth returns 401)
- [ ] Timeout handling works
- [ ] Response times are acceptable
- [ ] All required fields present in responses
- [ ] Service properly logs requests

---

## 🎯 Sample Test Data by Scenario

### Scenario 1: Small Portfolio
```json
{
  "portfolio_summary": {
    "portfolio_aal_kes": {"ml_augmented": 100000}
  },
  "building_risk_summary": [
    {"building_id": "B1", "risk_score": 45.5}
  ]
}
```

### Scenario 2: Medium Portfolio
```json
{
  "portfolio_summary": {
    "portfolio_aal_kes": {"ml_augmented": 5000000}
  },
  "building_risk_summary": [
    {"building_id": "NBO-0316", "risk_score": 87.4},
    {"building_id": "NBO-1042", "risk_score": 81.2},
    {"building_id": "NBO-2001", "risk_score": 45.3}
  ]
}
```

### Scenario 3: Large Portfolio
```json
{
  "portfolio_summary": {
    "portfolio_aal_kes": {"ml_augmented": 607333848.44},
    "portfolio_total_insured_value_kes": 10000000000
  },
  "building_risk_summary": [
    {"building_id": "NBO-0316", "risk_score": 87.4, "insured_value": 500000000},
    {"building_id": "NBO-1042", "risk_score": 81.2, "insured_value": 300000000},
    {"building_id": "NBO-2001", "risk_score": 45.3, "insured_value": 200000000},
    {"building_id": "NBO-3000", "risk_score": 32.1, "insured_value": 150000000}
  ]
}
```

---

**Happy testing!** 🎉

