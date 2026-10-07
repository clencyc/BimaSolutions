from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import requests


class APIClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("BACKEND_API_BASE_URL", "http://localhost:5001")
        self.mock_mode = os.getenv("MOCK_MODE", "true").lower() in {"1", "true", "yes"}
        self.mock_dir = Path(__file__).resolve().parent.parent / "mock_data"

    def _load_mock(self, filename: str) -> Any:
        file_path = self.mock_dir / filename
        with file_path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def _validate_response(self, payload: Any, key: str | None = None, required: list[str] | None = None) -> Any:
        if payload is None:
            raise ValueError(f"{key or 'response'} was empty")
        if key is not None and not isinstance(payload, dict):
            raise ValueError(f"{key} response was not an object")
        if required and isinstance(payload, dict):
            missing = [field for field in required if field not in payload]
            if missing:
                raise ValueError(f"Missing required fields: {missing}")
        return payload

    def login(self, email: str, password: str) -> Dict[str, Any]:
        payload = {"email": email, "password": password}
        if self.mock_mode:
            data = self._load_mock("auth_login.json")
            user = data.get("user", {})
            if not user.get("email"):
                raise ValueError("Mock login user missing email")
            return {"status": "success", "token": data.get("token"), "user": user}
        # TODO-BACKEND-API: /api/auth/login
        response = requests.post(f"{self.base_url}/api/auth/login", json=payload, timeout=10)
        response.raise_for_status()
        data = self._validate_response(response.json(), "login", ["user"])
        return data

    def get_dashboard_summary(self) -> Dict[str, Any]:
        if self.mock_mode:
            return self._validate_response(self._load_mock("dashboard_summary.json"), "summary")
        # TODO-BACKEND-API: /api/dashboard/summary
        response = requests.get(f"{self.base_url}/api/dashboard/summary", timeout=10)
        response.raise_for_status()
        return self._validate_response(response.json(), "summary")

    def get_ep_curve(self) -> Dict[str, Any]:
        if self.mock_mode:
            return self._validate_response(self._load_mock("ep_curve.json"), "ep_curve")
        # TODO-BACKEND-API: /api/ep-curve
        response = requests.get(f"{self.base_url}/api/ep-curve", timeout=10)
        response.raise_for_status()
        return self._validate_response(response.json(), "ep_curve")

    def get_hotspots(self) -> Dict[str, Any]:
        if self.mock_mode:
            return self._validate_response(self._load_mock("hotspots.json"), "hotspots")
        # TODO-BACKEND-API: /api/hotspots
        response = requests.get(f"{self.base_url}/api/hotspots", timeout=10)
        response.raise_for_status()
        return self._validate_response(response.json(), "hotspots")

    def get_drainage_reports(self) -> Dict[str, Any]:
        if self.mock_mode:
            return self._validate_response(self._load_mock("drainage_reports.json"), "drainage")
        # TODO-BACKEND-API: /api/drainage-reports
        response = requests.get(f"{self.base_url}/api/drainage-reports", timeout=10)
        response.raise_for_status()
        return self._validate_response(response.json(), "drainage")

    def get_reports(self) -> Dict[str, Any]:
        if self.mock_mode:
            return self._validate_response(self._load_mock("reports.json"), "reports")
        # TODO-BACKEND-API: /api/reports
        response = requests.get(f"{self.base_url}/api/reports", timeout=10)
        response.raise_for_status()
        return self._validate_response(response.json(), "reports")

    def generate_report(self, title: str, audience: str, return_periods: List[str], sections: List[str], report_format: str) -> Dict[str, Any]:
        payload = {
            "title": title,
            "audience": audience,
            "return_periods": return_periods,
            "sections": sections,
            "format": report_format,
        }
        if self.mock_mode:
            generated = self._load_mock("reports.json").get("generated", {})
            return {
                "status": "completed",
                "report_id": generated.get("report_id", "mock-report"),
                "title": title,
                "audience": audience,
                "briefing": generated.get("briefing", "SAMPLE DATA briefing"),
                "content_html": generated.get("content_html", "<p>Sample report created.</p>"),
                "download_url": generated.get("download_url", "/reports/download"),
            }
        # TODO-BACKEND-API: /api/reports/generate
        response = requests.post(f"{self.base_url}/api/reports/generate", json=payload, timeout=10)
        response.raise_for_status()
        return self._validate_response(response.json(), "report", ["report_id", "status"])

    def get_insights(self) -> Dict[str, Any]:
        if self.mock_mode:
            return self._validate_response(self._load_mock("insights.json"), "insights")
        # TODO-BACKEND-API: /api/insights
        response = requests.get(f"{self.base_url}/api/insights", timeout=10)
        response.raise_for_status()
        return self._validate_response(response.json(), "insights")


api_client = APIClient()
