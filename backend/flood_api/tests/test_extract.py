"""Tests for extracting inputs and running them through the flood model."""

import base64
import json
from io import BytesIO
from urllib.error import HTTPError
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from flood_api.api import app
from flood_api.extraction import (
    ExtractionServiceError,
    _groq_input_text,
    extract_document_information,
    extract_exposure_rows,
)


client = TestClient(app)


def _valid_exposure_row():
    return {
        "building_id": "B-EXTRACT-1",
        "latitude": -1.29,
        "longitude": 36.82,
        "neighbourhood": "Kibera",
        "construction_class": "masonry",
        "insured_value_ksh": 1_000_000,
        "common_hazard": 0.2,
        "occasional_hazard": 0.3,
        "moderate_hazard": 0.4,
        "severe_hazard": 0.5,
        "extreme_hazard": 0.6,
        "ai_confidence": 0.9,
        "needs_review": False,
        "extraction_notes": None,
    }


@patch("flood_api.api.extract_exposure_rows")
def test_extract_converts_rows_and_returns_model_run(extract_rows):
    extract_rows.return_value = [_valid_exposure_row()]

    response = client.post(
        "/extract",
        json={"data": "Building B-EXTRACT-1 insured for KES 1,000,000"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["extracted_rows"][0]["building_id"] == "B-EXTRACT-1"
    assert result["model_run"]["summary"]["portfolio_building_count"] == 1
    assert float(result["model_run"]["summary"]["average_annual_loss_ksh"]) > 0
    assert result["model_run"]["provenance"]["portfolio_source"] == "ai_derived"


@patch("flood_api.api.extract_exposure_rows")
def test_extract_passes_document_to_extractor(extract_rows):
    extract_rows.return_value = [_valid_exposure_row()]
    document = {
        "mime_type": "application/pdf",
        "data_base64": base64.b64encode(b"example PDF").decode("ascii"),
    }

    response = client.post("/extract", json={"document": document})

    assert response.status_code == 200
    extract_rows.assert_called_once_with(None, document)


@patch("flood_api.api.extract_exposure_rows")
def test_extract_rejects_incomplete_model_rows(extract_rows):
    row = _valid_exposure_row()
    del row["latitude"]
    extract_rows.return_value = [row]

    response = client.post("/extract", json={"data": "incomplete asset"})

    assert response.status_code == 422
    assert response.json()["detail"]["message"] == (
        "Extracted rows do not satisfy the model input contract"
    )


@patch("flood_api.api.extract_exposure_rows")
def test_extract_rejects_rows_without_hazard_inputs(extract_rows):
    row = _valid_exposure_row()
    for field in (
        "common_hazard",
        "occasional_hazard",
        "moderate_hazard",
        "severe_hazard",
        "extreme_hazard",
    ):
        row[field] = None
    extract_rows.return_value = [row]

    response = client.post("/extract", json={"data": "asset without hazard data"})

    assert response.status_code == 422
    assert "At least one hazard tier is required" in str(response.json())


def test_extract_requires_exactly_one_input():
    response = client.post("/extract", json={"data": "text", "document": {}})

    assert response.status_code == 422


def test_extract_reports_missing_groq_configuration():
    with patch.dict("os.environ", {}, clear=True):
        response = client.post("/extract", json={"data": "some asset"})

    assert response.status_code == 503
    assert response.json()["detail"] == "GROQ_API_KEY is not configured"


@patch(
    "flood_api.api.extract_exposure_rows",
    side_effect=ExtractionServiceError(
        "Groq extraction service is temporarily unavailable; retry shortly",
        status_code=503,
    ),
)
def test_extract_returns_retryable_status_for_groq_outage(extract_rows):
    response = client.post("/extract", json={"data": "some asset"})

    assert response.status_code == 503
    assert "retry shortly" in response.json()["detail"]


def test_groq_extractor_sends_data_and_parses_rows():
    body = {
        "choices": [
            {"message": {"content": '{"rows": [{"building_id": "B-1"}]}'}}
        ]
    }
    with (
        patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}),
        patch(
            "flood_api.extraction.urlopen",
            return_value=_UpstreamResponse(body),
        ) as urlopen,
    ):
        rows = extract_exposure_rows({"assets": [{"id": "B-1"}]})

    assert rows == [{"building_id": "B-1"}]
    request = urlopen.call_args.args[0]
    assert request.get_header("Authorization") == "Bearer test-key"
    assert request.full_url == "https://api.groq.com/openai/v1/chat/completions"
    body = json.loads(request.data.decode("utf-8"))
    assert body["model"] == "llama-3.3-70b-versatile"
    assert body["response_format"] == {"type": "json_object"}
    assert '"id": "B-1"' in body["messages"][1]["content"]


def test_document_extractor_returns_document_specific_information():
    result = {
        "document_type": "Commercial property insurance offer",
        "summary": "A property offer with coverage and risk details.",
        "extracted_data": {
            "property": {"gross_floor_area_m2": 24500},
            "coverage": {"flood": "available upon request"},
        },
        "model_rows": [],
    }
    body = {
        "choices": [{"message": {"content": json.dumps(result)}}]
    }
    with (
        patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}),
        patch(
            "flood_api.extraction.PdfReader",
            return_value=Mock(
                is_encrypted=False,
                pages=[Mock(extract_text=Mock(return_value="PDF sample text"))],
            ),
        ),
        patch(
            "flood_api.extraction.urlopen",
            return_value=_UpstreamResponse(body),
        ) as urlopen,
    ):
        extracted = extract_document_information(
            None,
            {
                "mime_type": "application/pdf",
                "data_base64": base64.b64encode(b"sample").decode("ascii"),
            },
        )

    assert extracted == result
    request_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    prompt = request_body["messages"][0]["content"]
    assert "general-purpose document extraction" in prompt
    assert "general risk descriptions into numeric scores" in prompt
    assert "PDF sample text" in request_body["messages"][1]["content"]


def test_groq_upstream_503_is_marked_retryable():
    error = HTTPError(
        "https://api.groq.com/",
        503,
        "Unavailable",
        hdrs=None,
        fp=BytesIO(b""),
    )
    with (
        patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}),
        patch("flood_api.extraction.urlopen", side_effect=error),
    ):
        try:
            extract_exposure_rows("some asset")
        except ExtractionServiceError as exc:
            assert exc.status_code == 503
            assert "retry shortly" in str(exc)
        else:
            raise AssertionError("Groq HTTP 503 should be retryable")


def test_groq_document_data_is_validated():
    try:
        _groq_input_text(
            None, document={"mime_type": "application/pdf", "data_base64": "%%%"}
        )
    except ValueError as exc:
        assert "valid base64" in str(exc)
    else:
        raise AssertionError("Invalid base64 document must be rejected")


def test_groq_rejects_image_documents_with_actionable_error():
    try:
        _groq_input_text(
            None,
            document={
                "mime_type": "image/png",
                "data_base64": base64.b64encode(b"image").decode("ascii"),
            },
        )
    except ValueError as exc:
        assert "PDF, DOCX and XLSX documents only" in str(exc)
    else:
        raise AssertionError("Groq text extraction should reject images")


class _UpstreamResponse:
    def __init__(self, payload):
        import json

        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return None

    def read(self):
        return self.body
