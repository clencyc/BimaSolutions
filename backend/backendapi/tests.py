import json
from unittest.mock import patch
from urllib.error import URLError

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken


class ModelApiProxyTests(APITestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="model-client",
            email="model-client@example.com",
            password="test-password",
        )
        access_token = RefreshToken.for_user(user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")

    @override_settings(
        FLOOD_MODEL_API_BASE_URL="https://model.example.test/"
    )
    @patch("backendapi.model_api.urlopen")
    def test_buildings_proxy_forwards_request_and_json_response(self, urlopen):
        payload = [{"building_id": "NBO-0316"}]
        upstream = _UpstreamResponse(payload)
        urlopen.return_value = upstream

        response = self.client.get(reverse("model-buildings"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, payload)
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://model.example.test/buildings",
        )
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 15)

    @patch("backendapi.model_api.urlopen")
    def test_custom_quote_is_forwarded_as_json_post(self, urlopen):
        request_data = {
            "tiv_kes": 1000000,
            "expected_annual_loss_kes": 25000,
            "risk_class": "medium",
            "confidence": "high",
        }
        urlopen.return_value = _UpstreamResponse({"gross_premium_kes": 50000})

        response = self.client.post(
            reverse("model-custom-quote"),
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        upstream_request = urlopen.call_args.args[0]
        self.assertEqual(upstream_request.method, "POST")
        self.assertEqual(
            json.loads(upstream_request.data.decode("utf-8")),
            request_data,
        )

    @override_settings(FLOOD_MODEL_API_BASE_URL="https://model.example.test")
    @patch("backendapi.model_api.extract_document_information")
    @patch("backendapi.model_api.urlopen")
    def test_extract_document_is_processed_in_django_then_model_is_run(
        self,
        urlopen,
        extract_rows,
    ):
        request_data = {
            "document": {
                "mime_type": "application/pdf",
                "data_base64": "cGRm",
            },
            "portfolio_name": "Client assets",
        }
        extract_rows.return_value = _extraction_result(
            [
                {
                    "building_id": "B-1",
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
            ]
        )
        urlopen.side_effect = [
            _UpstreamResponse({"portfolio_id": "portfolio-ai-123"}),
            _UpstreamResponse({"status": "confirmed"}),
            _UpstreamResponse(
                {"run_id": "run-123", "summary": {"portfolio_building_count": 1}}
            ),
        ]

        response = self.client.post(
            reverse("model-extract"),
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["extracted_rows"][0]["source"], "ai_derived")
        self.assertEqual(response.data["model_run"]["run_id"], "run-123")
        extract_rows.assert_called_once_with(None, request_data["document"])
        self.assertEqual(urlopen.call_count, 3)
        upstream_requests = [call.args[0] for call in urlopen.call_args_list]
        self.assertEqual(
            [request.full_url for request in upstream_requests],
            [
                "https://model.example.test/portfolio/rows",
                "https://model.example.test/portfolio/portfolio-ai-123/confirm",
                "https://model.example.test/model/run",
            ],
        )
        self.assertTrue(
            all(request.method == "POST" for request in upstream_requests)
        )
        self.assertEqual(
            json.loads(upstream_requests[0].data.decode("utf-8"))[0]["source"],
            "ai_derived",
        )
        self.assertEqual(
            json.loads(upstream_requests[2].data.decode("utf-8")),
            {"portfolio_id": "portfolio-ai-123"},
        )

    @patch("backendapi.model_api.extract_document_information")
    @patch("backendapi.model_api.urlopen")
    def test_extract_returns_document_data_when_model_fields_are_missing(
        self,
        urlopen,
        extract_information,
    ):
        extract_information.return_value = _extraction_result(
            [{"building_id": "B-1"}]
        )
        response = self.client.post(
            reverse("model-extract"),
            {"data": "Building B-1"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["model_run"])
        self.assertFalse(response.data["model_readiness"]["ready"])
        self.assertIn("latitude", str(response.data["model_readiness"]["issues"]))
        urlopen.assert_not_called()

    @patch("backendapi.model_api.extract_document_information")
    @patch("backendapi.model_api.urlopen")
    def test_extract_returns_general_document_data_without_exposure_rows(
        self,
        urlopen,
        extract_information,
    ):
        extract_information.return_value = _extraction_result([])
        extract_information.return_value["extracted_data"] = {
            "policy": {"coverage_type": "all-risks"}
        }

        response = self.client.post(
            reverse("model-extract"),
            {"data": "An insurance policy document"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["extracted_data"]["policy"]["coverage_type"],
            "all-risks",
        )
        self.assertIsNone(response.data["model_run"])
        self.assertFalse(response.data["model_readiness"]["ready"])
        urlopen.assert_not_called()

    @patch("backendapi.model_api.urlopen", side_effect=URLError("offline"))
    def test_unavailable_model_service_returns_gateway_error(self, _urlopen):
        response = self.client.get(reverse("model-formula"))

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(
            response.data,
            {"detail": "Flood model service is unavailable"},
        )

    def test_model_proxy_requires_jwt(self):
        self.client.credentials()

        response = self.client.get(reverse("model-buildings"))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class InterpretationApiProxyTests(APITestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="interp-client",
            email="interp-client@example.com",
            password="test-password",
        )
        access_token = RefreshToken.for_user(user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")

    @override_settings(INTERPRETATION_API_BASE_URL="https://interp.example.test")
    @patch("backendapi.interpretation_api.urlopen")
    def test_interpretation_health_proxy(self, urlopen):
        urlopen.return_value = _UpstreamResponse({"status": "ok"})

        response = self.client.get(reverse("interpretation-health"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"status": "ok"})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://interp.example.test/health")

    @override_settings(INTERPRETATION_API_BASE_URL="https://interp.example.test")
    @patch("backendapi.interpretation_api.urlopen")
    def test_interpretation_summary_proxy(self, urlopen):
        request_payload = {"portfolio_name": "Test Portfolio", "run_id": "run-1"}
        urlopen.return_value = _UpstreamResponse({"summary_text": "Risk level low."})

        response = self.client.post(
            reverse("interpretation-summary"),
            request_payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"summary_text": "Risk level low."})
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url, "https://interp.example.test/api/interpretation/summary"
        )
        self.assertEqual(
            json.loads(request.data.decode("utf-8")), request_payload
        )

    @override_settings(INTERPRETATION_API_BASE_URL="https://interp.example.test")
    @patch("backendapi.interpretation_api.urlopen")
    def test_interpretation_question_proxy(self, urlopen):
        request_payload = {"question": "What is the AAL?"}
        urlopen.return_value = _UpstreamResponse({"answer": "AAL is KES 41M."})

        response = self.client.post(
            reverse("interpretation-question"),
            request_payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"answer": "AAL is KES 41M."})
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url, "https://interp.example.test/api/interpretation/question"
        )


class UploadApiTests(APITestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="upload-client",
            email="upload-client@example.com",
            password="test-password",
        )
        access_token = RefreshToken.for_user(user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")

    @patch("backendapi.upload_api._proxy_interpretation_api")
    @patch("backendapi.upload_api.extract_document_information")
    @patch("backendapi.upload_api._proxy_model_api")
    def test_upload_file_multipart_success(
        self, mock_model_proxy, mock_extract, mock_interp_proxy
    ):
        mock_extract.return_value = _extraction_result(
            [
                {
                    "building_id": "B-100",
                    "latitude": -1.29,
                    "longitude": 36.82,
                    "neighbourhood": "Kibera",
                    "construction_class": "masonry",
                    "insured_value_ksh": 5_000_000,
                    "common_hazard": 0.2,
                    "occasional_hazard": 0.3,
                    "moderate_hazard": 0.4,
                    "severe_hazard": 0.5,
                    "extreme_hazard": 0.6,
                    "ai_confidence": 0.95,
                    "needs_review": False,
                    "extraction_notes": None,
                }
            ]
        )

        # Mock model API calls
        mock_model_proxy.side_effect = [
            _ResponseMock(200, {"portfolio_id": "p-100"}),
            _ResponseMock(200, {"status": "confirmed"}),
            _ResponseMock(
                200,
                {
                    "run_id": "run-100",
                    "portfolio_building_count": 1,
                    "portfolio_total_insured_value_ksh": 5000000.0,
                    "average_annual_loss_ksh": 250000.0,
                    "losses_per_return_period": {"common": 50000.0, "extreme": 500000.0},
                },
            ),
        ]

        # Mock interpretation API response
        mock_interp_proxy.return_value = _ResponseMock(
            200, {"summary_narrative": "Property is moderately exposed to flood hazards."}
        )

        from io import BytesIO

        file_data = BytesIO(b"Building B-100, Kibera, KES 5000000")
        file_data.name = "exposure_data.txt"

        response = self.client.post(
            reverse("api-upload"),
            {"file": file_data, "portfolio_name": "Kibera Portfolio"},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["portfolio_name"], "Kibera Portfolio")
        self.assertEqual(response.data["financial_summary"]["total_insured_value_kes"], 5000000.0)
        self.assertEqual(response.data["financial_summary"]["expected_annual_loss_kes"], 250000.0)
        self.assertIsNotNone(response.data["financial_summary"]["indicative_gross_premium_kes"])
        self.assertEqual(
            response.data["interpretation"],
            {"summary_narrative": "Property is moderately exposed to flood hazards."},
        )


class _ResponseMock:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self.data = data



class _UpstreamResponse:
    def __init__(self, payload, status_code=200):
        self.status = status_code
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return None

    def read(self):
        return self.body


def _extraction_result(model_rows):
    return {
        "document_type": "Property offer",
        "summary": "Property and insurance information",
        "extracted_data": {"property": {"construction": "reinforced concrete"}},
        "model_rows": model_rows,
    }
