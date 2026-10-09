import os
from urllib.parse import urljoin

import requests
import streamlit as st

from api_client import APIError, _error_message, request_json


DEFAULT_INTERPRETATION_API_URL = "https://9520-102-206-113-162.ngrok-free.app"
INTERPRETATION_TIMEOUT = 45


def get_interpretation_base_url():
    base_url = (
        st.secrets.get("INTERPRETATION_API_BASE_URL")
        or os.getenv("INTERPRETATION_API_BASE_URL")
        or DEFAULT_INTERPRETATION_API_URL
    )
    return str(base_url).rstrip("/")


def interpretation_request(method, path, payload=None):
    url = urljoin(f"{get_interpretation_base_url()}/", path.lstrip("/"))
    headers = {
        "Accept": "application/json",
        "ngrok-skip-browser-warning": "true",
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"

    try:
        response = requests.request(
            method,
            url,
            headers=headers,
            json=payload,
            timeout=INTERPRETATION_TIMEOUT,
        )
    except requests.Timeout as exc:
        raise APIError(
            "The interpretation service request timed out. Please try again."
        ) from exc
    except requests.RequestException as exc:
        raise APIError(f"Could not reach the interpretation service: {exc}") from exc

    if not response.ok:
        message, details = _error_message(response)
        raise APIError(
            f"Interpretation service returned HTTP {response.status_code}: {message}",
            status_code=response.status_code,
            details=details,
        )
    if response.status_code == 204 or not response.content:
        return None

    try:
        return response.json()
    except ValueError as exc:
        raise APIError(
            "The interpretation service returned a non-JSON response."
        ) from exc


def check_interpretation_health():
    return interpretation_request("GET", "/health")


def request_interpretation_summary(model_output):
    return interpretation_request(
        "POST",
        "/api/interpretation/summary",
        {"model_output": model_output},
    )


def ask_interpretation_question(model_output, question):
    return interpretation_request(
        "POST",
        "/api/interpretation/question",
        {"model_output": model_output, "question": question},
    )


def request_uploaded_document_summary(token, portfolio_summary, building_risk_summary):
    return request_json(
        "POST",
        "/api/interpretation/summary/",
        token=token,
        json={
            "portfolio_summary": portfolio_summary,
            "building_risk_summary": building_risk_summary,
        },
    )


def ask_uploaded_document_question(token, context, question):
    return request_json(
        "POST",
        "/api/interpretation/question/",
        token=token,
        json={"question": question, "context": context},
    )
