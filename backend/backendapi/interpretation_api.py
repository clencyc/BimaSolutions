import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


logger = logging.getLogger(__name__)
INTERPRETATION_API_TIMEOUT_SECONDS = 30


def _proxy_interpretation_api(
    path: str,
    *,
    method: str = "GET",
    payload: dict | list | None = None,
    timeout: int = INTERPRETATION_API_TIMEOUT_SECONDS,
):
    """
    Proxy HTTP requests to the external Interpretation API.
    
    This is an interpretation-only service for:
    - plain-language summaries of model output
    - follow-up question answering
    - underwriting-friendly explanations
    - narrative reporting based on already-calculated results
    
    It does NOT handle calculations (risk scores, AAL, premium, etc).
    """
    body = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "BimaSolutions-Backend/1.0",
        "ngrok-skip-browser-warning": "true",
    }
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    base_url = getattr(
        settings,
        "INTERPRETATION_API_BASE_URL",
        "http://localhost:5001",
    ).rstrip("/")

    url = f"{base_url}{path}"
    request = Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )

    try:
        with urlopen(request, timeout=timeout) as upstream:
            upstream_status = upstream.status
            upstream_body = upstream.read()
    except HTTPError as exc:
        upstream_status = exc.code
        upstream_body = exc.read()
    except (URLError, TimeoutError, OSError) as exc:
        logger.warning("Interpretation API request failed: %s", exc)
        return Response(
            {"detail": "Interpretation service is unavailable"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    try:
        data = json.loads(upstream_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error(
            "Interpretation API returned non-JSON response (HTTP %s)",
            upstream_status,
        )
        return Response(
            {
                "detail": "Interpretation service returned an invalid response",
                "upstream_status": upstream_status,
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return Response(data, status=upstream_status)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def interpretation_health(request):
    """
    Check health of the Interpretation service.
    
    Returns:
        {
            "status": "ok",
            "service": "interpretation_only"
        }
    """
    return _proxy_interpretation_api("/health", method="GET")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def interpretation_summary(request):
    """
    Generate executive/underwriter summary from model output JSON.
    
    Expected payload structure:
    {
        "portfolio_summary": {
            "portfolio_aal_kes": { "ml_augmented": 607333848.44 }
        },
        "building_risk_summary": [
            { "building_id": "NBO-0316", "risk_score": 87.4 },
            { "building_id": "NBO-1042", "risk_score": 81.2 }
        ]
    }
    
    Returns:
        {
            "summary": "Plain-language interpretation of the model output",
            "interpretation_only": true,
            "source": "groq"
        }
    """
    payload = request.data if isinstance(request.data, (dict, list)) else {}
    return _proxy_interpretation_api(
        "/api/interpretation/summary",
        method="POST",
        payload=payload,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def interpretation_question(request):
    """
    Answer underwriter / natural language follow-up question based on model output.
    
    Expected payload structure:
    {
        "question": "Which building appears to be the highest risk?",
        "context": {
            "building_risk_summary": [
                { "building_id": "NBO-0316", "risk_score": 87.4 },
                { "building_id": "NBO-1042", "risk_score": 81.2 }
            ]
        }
    }
    
    Returns:
        {
            "answer": "Based on the supplied model output, NBO-0316 appears to be the highest-risk building.",
            "interpretation_only": true,
            "source": "groq"
        }
    """
    payload = request.data if isinstance(request.data, (dict, list)) else {}
    return _proxy_interpretation_api(
        "/api/interpretation/question",
        method="POST",
        payload=payload,
    )
