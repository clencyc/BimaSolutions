"""
High-level interpretation service client for backend views.

This module provides convenience functions for calling the Interpretation API
without having to manually construct HTTP requests.
"""

import logging
from typing import Any, Dict, Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class InterpretationServiceError(Exception):
    """Raised when the Interpretation service is unavailable or returns an error."""
    pass


def get_summary(model_output: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    """
    Generate a plain-language summary from model output.
    
    Args:
        model_output: The model output containing portfolio_summary and building_risk_summary
        timeout: Request timeout in seconds
    
    Returns:
        Dict with 'summary', 'interpretation_only', and 'source' keys
        
    Raises:
        InterpretationServiceError: If the service is unavailable
    """
    base_url = getattr(settings, "INTERPRETATION_API_BASE_URL", "http://localhost:5001")
    url = f"{base_url}/api/interpretation/summary"
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "BimaSolutions-Backend/1.0",
        "ngrok-skip-browser-warning": "true",
    }
    
    try:
        response = requests.post(
            url,
            json=model_output,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        logger.error("Interpretation API request timed out after %d seconds", timeout)
        raise InterpretationServiceError("Interpretation service request timed out")
    except requests.exceptions.ConnectionError as e:
        logger.error("Failed to connect to Interpretation service at %s: %s", url, e)
        raise InterpretationServiceError("Interpretation service is unavailable")
    except requests.exceptions.HTTPError as e:
        logger.error("Interpretation API returned HTTP %d: %s", response.status_code, response.text)
        raise InterpretationServiceError(f"Interpretation service error: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error("Unexpected error calling Interpretation service: %s", e)
        raise InterpretationServiceError("Unexpected error from Interpretation service")


def answer_question(
    question: str,
    context: Dict[str, Any],
    timeout: int = 30,
) -> Dict[str, Any]:
    """
    Answer a natural-language question about model output.
    
    Args:
        question: The underwriter's question
        context: Model output context (building_risk_summary, portfolio_summary, etc.)
        timeout: Request timeout in seconds
    
    Returns:
        Dict with 'answer', 'interpretation_only', and 'source' keys
        
    Raises:
        InterpretationServiceError: If the service is unavailable
    """
    base_url = getattr(settings, "INTERPRETATION_API_BASE_URL", "http://localhost:5001")
    url = f"{base_url}/api/interpretation/question"
    
    payload = {
        "question": question,
        "context": context,
    }
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "BimaSolutions-Backend/1.0",
        "ngrok-skip-browser-warning": "true",
    }
    
    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        logger.error("Interpretation API request timed out after %d seconds", timeout)
        raise InterpretationServiceError("Interpretation service request timed out")
    except requests.exceptions.ConnectionError as e:
        logger.error("Failed to connect to Interpretation service at %s: %s", url, e)
        raise InterpretationServiceError("Interpretation service is unavailable")
    except requests.exceptions.HTTPError as e:
        logger.error("Interpretation API returned HTTP %d: %s", response.status_code, response.text)
        raise InterpretationServiceError(f"Interpretation service error: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error("Unexpected error calling Interpretation service: %s", e)
        raise InterpretationServiceError("Unexpected error from Interpretation service")


def check_health(timeout: int = 5) -> bool:
    """
    Check if the Interpretation service is healthy.
    
    Args:
        timeout: Request timeout in seconds
    
    Returns:
        True if healthy, False otherwise
    """
    base_url = getattr(settings, "INTERPRETATION_API_BASE_URL", "http://localhost:5001")
    url = f"{base_url}/health"
    
    headers = {
        "User-Agent": "BimaSolutions-Backend/1.0",
        "ngrok-skip-browser-warning": "true",
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False
