import os
from urllib.parse import urljoin

import requests
import streamlit as st


DEFAULT_TIMEOUT = 15
MODEL_PREFIX = "/api/model/"


class APIError(Exception):
    def __init__(self, message, status_code=None, details=None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class AuthenticationError(APIError):
    pass


def get_base_url():
    base_url = st.secrets.get("API_BASE_URL") or os.getenv("API_BASE_URL", "")
    return base_url.rstrip("/")


def build_url(path):
    base_url = get_base_url()
    if not base_url:
        raise APIError(
            "API_BASE_URL is not configured. Set it in .streamlit/secrets.toml or as an environment variable."
        )

    return urljoin(f"{base_url}/", path.lstrip("/"))


def _error_message(response):
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or response.reason, None

    if isinstance(payload, dict):
        for key in ("detail", "message", "error", "non_field_errors"):
            value = payload.get(key)
            if value:
                return value if isinstance(value, str) else str(value), payload

    return f"Request failed with status {response.status_code}.", payload


def request_json(
    method,
    path,
    token=None,
    params=None,
    json=None,
    timeout=DEFAULT_TIMEOUT,
    data=None,
    files=None,
):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.request(
            method,
            build_url(path),
            headers=headers,
            params=params,
            json=json,
            data=data,
            files=files,
            timeout=timeout,
        )
    except requests.Timeout as exc:
        raise APIError("The API request timed out. Please try again.") from exc
    except requests.RequestException as exc:
        raise APIError(f"Could not reach the API: {exc}") from exc

    if response.status_code in (401, 403):
        message, details = _error_message(response)
        raise AuthenticationError(message, status_code=response.status_code, details=details)

    if not response.ok:
        message, details = _error_message(response)
        raise APIError(message, status_code=response.status_code, details=details)

    if response.status_code == 204 or not response.content:
        return None

    try:
        return response.json()
    except ValueError as exc:
        raise APIError("The API returned a non-JSON response.") from exc


def upload_document(token, filename, content, portfolio_name):
    return request_json(
        "POST",
        "/api/upload/",
        token=token,
        data={"portfolio_name": portfolio_name},
        files={"file": (filename, content)},
        timeout=120,
    )


def login(email, password):
    return request_json("POST", "/auth/login/", json={"email": email, "password": password})


def model_get(endpoint, token, params=None):
    return request_json("GET", f"{MODEL_PREFIX}{endpoint.strip('/')}/", token=token, params=params)


def model_post(endpoint, token, payload):
    return request_json("POST", f"{MODEL_PREFIX}{endpoint.strip('/')}/", token=token, json=payload)


def get_model_health(token):
    return model_get("health", token)


def get_buildings(token, params=None):
    return model_get("buildings", token, params=params)


def get_portfolio_summary(token):
    return model_get("portfolio-summary", token)


def get_metrics(token):
    return model_get("metrics", token)


def get_formula(token):
    return model_get("formula", token)


def get_building_quote(token, building_id):
    return model_get(f"quote/{building_id}", token)


def create_quote(token, payload):
    return model_post("quote", token, payload)
