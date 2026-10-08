"""Flask API for sharing the model outputs and commercial pricing inputs."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

import pandas as pd
from flask import Flask, jsonify, request

from . import config
from .data import haversine_m
from .pricing import DEFAULT_ASSUMPTIONS, commercial_quote, pricing_formula


@lru_cache(maxsize=1)
def _load_outputs() -> dict[str, object]:
    out = config.OUTPUT_DIR
    summary = pd.read_csv(out / "building_risk_summary.csv")
    portfolio = json.loads((out / "portfolio_summary.json").read_text())
    metrics = json.loads((out / "model_metrics.json").read_text())
    return {"summary": summary, "portfolio": portfolio, "metrics": metrics}


def create_app() -> Flask:
    app = Flask(__name__)

    def _nearest_building_by_point(latitude: float, longitude: float) -> dict:
        summary = _load_outputs()["summary"]
        distances = haversine_m(
            latitude,
            longitude,
            summary["latitude"].values,
            summary["longitude"].values,
        )
        idx = int(distances.argmin())
        row = summary.iloc[idx]
        quote = commercial_quote(row)
        quote["building_id"] = row["building_id"]
        quote["matched_portfolio_building_id"] = row["building_id"]
        quote["match_distance_m"] = float(distances[idx])
        quote["matched_latitude"] = float(row["latitude"])
        quote["matched_longitude"] = float(row["longitude"])
        return quote

    def _geocode_nominatim(query: str) -> dict:
        base_url = os.getenv("GEOCODER_BASE_URL", "https://nominatim.openstreetmap.org").rstrip("/")
        user_agent = os.getenv("GEOCODER_USER_AGENT", "bimasolutions-flood-model/1.0")
        params = urlparse.urlencode({"q": query, "format": "jsonv2", "limit": 1})
        url = f"{base_url}/search?{params}"
        req = urlrequest.Request(url, headers={"User-Agent": user_agent})

        with urlrequest.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        if not payload:
            raise ValueError("No geocoding match found")

        item = payload[0]
        return {
            "latitude": float(item["lat"]),
            "longitude": float(item["lon"]),
            "display_name": item.get("display_name", query),
        }

    def _resolve_name_location(payload: dict) -> dict:
        if payload.get("latitude") is not None and payload.get("longitude") is not None:
            return {
                "latitude": float(payload["latitude"]),
                "longitude": float(payload["longitude"]),
                "display_name": payload.get("building_name") or payload.get("name") or payload.get("building_label"),
                "provider": "payload_coordinates",
            }

        building_name = payload.get("building_name") or payload.get("name") or payload.get("building_label")
        if not building_name:
            raise ValueError("building_name is required for name-based quote mode")

        default_locality = os.getenv("GEOCODER_DEFAULT_LOCALITY", "Nairobi")
        default_country = os.getenv("GEOCODER_DEFAULT_COUNTRY", "Kenya")
        locality = payload.get("locality") or payload.get("city") or default_locality
        country = payload.get("country") or default_country

        building_name = str(building_name).strip()
        query_candidates = []
        if locality or country:
            parts = [building_name]
            if locality:
                parts.append(str(locality).strip())
            if country:
                parts.append(str(country).strip())
            query_candidates.append(", ".join([p for p in parts if p]))
        query_candidates.append(building_name)

        provider = os.getenv("GEOCODER_PROVIDER", "nominatim").lower()
        if provider != "nominatim":
            raise ValueError(f"Unsupported GEOCODER_PROVIDER '{provider}'")

        last_error: Exception | None = None
        for query in query_candidates:
            try:
                geocoded = _geocode_nominatim(query)
                geocoded["provider"] = provider
                geocoded["query"] = query
                geocoded["query_candidates"] = query_candidates
                return geocoded
            except ValueError as exc:
                last_error = exc
                continue

        raise ValueError(f"No geocoding match found for query candidates: {query_candidates}") from last_error

    def _quote_from_payload(payload: dict) -> dict:
        """Build a quote from either a stored building or a manually entered building name."""
        building_label = payload.get("building_name") or payload.get("name") or payload.get("building_label")

        # Prefer the stored portfolio row when a known building_id is supplied.
        if "building_id" in payload:
            summary = _load_outputs()["summary"]
            match = summary.loc[summary["building_id"] == payload["building_id"]]
            if match.empty:
                return {
                    "error": f"Unknown building_id '{payload['building_id']}'",
                    "error_type": "not_found",
                }
            quote = commercial_quote(match.iloc[0])
            quote["building_id"] = payload["building_id"]
            if building_label:
                quote["building_name"] = building_label
            quote["quote_source"] = "portfolio_building_id"
            return quote

        if building_label or (payload.get("latitude") is not None and payload.get("longitude") is not None):
            required = {"tiv_kes", "expected_annual_loss_kes", "risk_class", "confidence"}
            missing = sorted(required - set(payload))

            if not missing:
                quote = commercial_quote(payload)
                if building_label:
                    quote["building_name"] = building_label
                quote["quote_source"] = "manual_inputs"
                return quote

            try:
                resolved = _resolve_name_location(payload)
                quote = _nearest_building_by_point(resolved["latitude"], resolved["longitude"])
                if building_label:
                    quote["building_name"] = building_label
                quote["geocode_provider"] = resolved["provider"]
                quote["input_latitude"] = resolved["latitude"]
                quote["input_longitude"] = resolved["longitude"]
                quote["geocode_display_name"] = resolved.get("display_name")
                if resolved.get("query"):
                    quote["geocode_query"] = resolved["query"]
                quote["quote_source"] = "name_or_coordinates_nearest_portfolio"
                return quote
            except (ValueError, urlerror.URLError) as exc:
                return {
                    "error": f"Unable to resolve building location: {exc}",
                    "error_type": "invalid_request",
                    "hint": "Provide building_name (+ locality/country) or provide latitude and longitude",
                }

        required = {"tiv_kes", "expected_annual_loss_kes", "risk_class", "confidence"}
        missing = sorted(required - set(payload))
        if missing:
            return {
                "error": "Missing required fields for manual quote",
                "error_type": "invalid_request",
                "missing": missing,
                "hint": "Provide building_id, or building_name, or manual pricing inputs (tiv_kes, expected_annual_loss_kes, risk_class, confidence)",
            }

        quote = commercial_quote(payload)
        if building_label:
            quote["building_name"] = building_label
        quote["quote_source"] = "manual_inputs"
        return quote

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/formula")
    def formula():
        return jsonify({
            "pricing_formula": pricing_formula(),
            "assumptions": DEFAULT_ASSUMPTIONS.resolved(),
        })

    @app.get("/portfolio-summary")
    def portfolio_summary():
        artifacts = _load_outputs()
        return jsonify(artifacts["portfolio"])

    @app.get("/buildings")
    def buildings():
        summary = _load_outputs()["summary"]
        cols = [
            "building_id", "housing_class", "tiv_kes", "expected_annual_loss_kes",
            "aal_rate", "risk_score", "risk_class", "confidence",
        ]
        return jsonify(summary[cols].to_dict(orient="records"))

    @app.get("/quote/<building_id>")
    def quote_by_building(building_id: str):
        quote = _quote_from_payload({"building_id": building_id})
        if "error" not in quote:
            return jsonify(quote)

        # Fallback: if not found as an internal portfolio id, treat the path
        # value as a building name for browser-friendly testing.
        fallback = _quote_from_payload({"building_name": building_id})
        if "error" not in fallback:
            fallback["path_interpreted_as"] = "building_name"
            return jsonify(fallback)

        # Preserve not-found for true id misses; return fallback error details
        # when name-resolution fails.
        if quote.get("error_type") == "not_found":
            status = 400 if fallback.get("error_type") == "invalid_request" else 404
            return jsonify(fallback), status
        return jsonify(quote), 400

    @app.get("/quote-by-name")
    def quote_by_name():
        building_name = request.args.get("building_name") or request.args.get("name")
        city = request.args.get("city")
        country = request.args.get("country")
        latitude = request.args.get("latitude")
        longitude = request.args.get("longitude")

        payload: dict[str, object] = {}
        if building_name:
            payload["building_name"] = building_name
        if city:
            payload["city"] = city
        if country:
            payload["country"] = country
        if latitude is not None and longitude is not None:
            payload["latitude"] = latitude
            payload["longitude"] = longitude

        if not payload:
            return jsonify({
                "error": "Provide query params: building_name (or name), optionally city/country; or latitude and longitude",
                "error_type": "invalid_request",
            }), 400

        quote = _quote_from_payload(payload)
        if "error" in quote:
            error_type = quote.get("error_type", "invalid_request")
            status = 404 if error_type == "not_found" else 400
            return jsonify(quote), status
        return jsonify(quote)

    @app.post("/quote")
    def quote_from_payload():
        payload = request.get_json(force=True, silent=False)
        if not isinstance(payload, dict):
            return jsonify({"error": "JSON object expected"}), 400

        quote = _quote_from_payload(payload)
        if "error" in quote:
            error_type = quote.get("error_type", "invalid_request")
            status = 404 if error_type == "not_found" else 400
            return jsonify(quote), status
        return jsonify(quote)

    @app.get("/metrics")
    def metrics():
        return jsonify(_load_outputs()["metrics"])

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
