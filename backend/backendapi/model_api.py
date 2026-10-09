import json
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.conf import settings
from pydantic import ValidationError
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from flood_api.extraction import (
    ExtractionConfigurationError,
    ExtractionServiceError,
    extract_document_information,
)
from flood_api.modules.exposure import normalize_exposure_row
from flood_api.schemas.contracts import ExtractDataRequest, ExposureRowAI


logger = logging.getLogger(__name__)
MODEL_API_TIMEOUT_SECONDS = 15


def _proxy_model_api(
    path,
    *,
    method="GET",
    payload=None,
    timeout=MODEL_API_TIMEOUT_SECONDS,
):
    body = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "BimaSolutions-Backend/1.0",
        "ngrok-skip-browser-warning": "true",
    }
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(
        f"{settings.FLOOD_MODEL_API_BASE_URL.rstrip('/')}{path}",
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
        logger.warning("Flood model API request failed: %s", exc)
        return Response(
            {"detail": "Flood model service is unavailable"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    try:
        data = json.loads(upstream_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error(
            "Flood model API returned non-JSON response (HTTP %s)",
            upstream_status,
        )
        return Response(
            {
                "detail": "Flood model service returned an invalid response",
                "upstream_status": upstream_status,
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return Response(data, status=upstream_status)


def _get(path):
    return _proxy_model_api(path)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def model_health(request):
    return _get("/health")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def model_buildings(request):
    return _get("/buildings")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def model_portfolio_summary(request):
    return _get("/portfolio-summary")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def model_metrics(request):
    return _get("/metrics")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def model_formula(request):
    return _get("/formula")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def model_building_quote(request, building_id):
    return _get(f"/quote/{quote(building_id, safe='')}")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def model_custom_quote(request):
    if not isinstance(request.data, dict):
        return Response(
            {"detail": "A JSON object is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return _proxy_model_api("/quote", method="POST", payload=request.data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def model_extract_data(request):
    if not isinstance(request.data, dict):
        return Response(
            {"detail": "A JSON object is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        payload = ExtractDataRequest.model_validate(request.data)
    except ValidationError as exc:
        return Response(
            {
                "detail": "Invalid extraction request",
                "errors": exc.errors(include_url=False, include_input=False),
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    document = (
        payload.document.model_dump()
        if payload.document is not None
        else None
    )
    try:
        extraction = extract_document_information(payload.data, document)
    except ValueError as exc:
        return Response(
            {"detail": str(exc)},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    except ExtractionConfigurationError as exc:
        return Response(
            {"detail": str(exc)},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except ExtractionServiceError as exc:
        return Response(
            {"detail": str(exc)},
            status=exc.status_code,
        )

    candidate_rows = extraction["model_rows"]
    extracted_rows = [
        {**row, "source": "ai_derived"}
        if isinstance(row, dict)
        else row
        for row in candidate_rows
    ]
    model_ready_rows = []
    validation_errors = []
    for index, raw_row in enumerate(candidate_rows):
        if not isinstance(raw_row, dict):
            validation_errors.append(
                {"row": index, "errors": [{"msg": "Expected a JSON object"}]}
            )
            continue
        try:
            validated_row = ExposureRowAI.model_validate(raw_row)
        except ValidationError as exc:
            validation_errors.append(
                {
                    "row": index,
                    "errors": exc.errors(
                        include_url=False,
                        include_input=False,
                    ),
                }
            )
            continue

        row_data = validated_row.model_dump(mode="json")
        hazards = [
            row_data.get(f"{tier}_hazard")
            for tier in ("common", "occasional", "moderate", "severe", "extreme")
        ]
        if not any(value is not None for value in hazards):
            validation_errors.append(
                {
                    "row": index,
                    "errors": [
                        {
                            "loc": ["hazard"],
                            "msg": "At least one hazard tier is required to run the model",
                        }
                    ],
                }
            )
            continue
        if any(value is None for value in hazards):
            row_data["needs_review"] = True
        row_data["source"] = "ai_derived"
        try:
            model_ready_rows.append(normalize_exposure_row(row_data).as_dict())
        except (ValueError, TypeError) as exc:
            validation_errors.append(
                {"row": index, "errors": [{"msg": str(exc)}]}
            )

    warnings = []
    if not candidate_rows:
        warnings.append(
            "No individual building exposure rows were identified; "
            "the flood model was not run."
        )
    elif validation_errors:
        warnings.append(
            "Document information was extracted, but the flood model was not "
            "run because one or more building records are missing or have "
            "invalid required model inputs."
        )
    elif len(model_ready_rows) != len(candidate_rows):
        warnings.append(
            "The flood model was not run because not all extracted building "
            "records could be prepared as model inputs."
        )

    portfolio_id = None
    model_run = None
    can_run_model = (
        bool(candidate_rows)
        and not validation_errors
        and len(model_ready_rows) == len(candidate_rows)
    )
    if can_run_model:
        portfolio_response = _proxy_model_api(
            "/portfolio/rows",
            method="POST",
            payload=model_ready_rows,
        )
        if portfolio_response.status_code >= 400:
            return portfolio_response
        portfolio_id = portfolio_response.data.get("portfolio_id")
        if not portfolio_id:
            logger.error("Flood model API returned no portfolio ID for extracted rows")
            return Response(
                {"detail": "Flood model service returned an invalid portfolio response"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        confirm_response = _proxy_model_api(
            f"/portfolio/{quote(portfolio_id, safe='')}/confirm",
            method="POST",
            payload={},
        )
        if confirm_response.status_code >= 400:
            return confirm_response

        model_response = _proxy_model_api(
            "/model/run",
            method="POST",
            payload={"portfolio_id": portfolio_id},
        )
        if model_response.status_code >= 400:
            return model_response
        model_run = model_response.data

    if any(
        row.get(f"{tier}_hazard") is None
        for row in model_ready_rows
        for tier in ("common", "occasional", "moderate", "severe", "extreme")
    ):
        warnings.append(
            "Missing hazard tiers are treated as zero contribution; "
            "losses and average annual loss may be understated."
        )

    return Response(
        {
            "portfolio_id": portfolio_id,
            "portfolio_name": payload.portfolio_name,
            "document_type": extraction["document_type"],
            "summary": extraction["summary"],
            "extracted_data": extraction["extracted_data"],
            "extracted_rows": extracted_rows,
            "model_readiness": {
                "ready": can_run_model,
                "issues": validation_errors,
            },
            "model_run": model_run,
            "warnings": warnings,
        },
        status=status.HTTP_200_OK,
    )
