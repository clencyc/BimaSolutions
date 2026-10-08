"""Flask API for sharing the model outputs and commercial pricing inputs."""
from __future__ import annotations

import json
from functools import lru_cache

import pandas as pd
from flask import Flask, jsonify, request

from . import config
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
        summary = _load_outputs()["summary"]
        match = summary.loc[summary["building_id"] == building_id]
        if match.empty:
            return jsonify({"error": f"Unknown building_id '{building_id}'"}), 404
        quote = commercial_quote(match.iloc[0])
        quote["building_id"] = building_id
        return jsonify(quote)

    @app.post("/quote")
    def quote_from_payload():
        payload = request.get_json(force=True, silent=False)
        if not isinstance(payload, dict):
            return jsonify({"error": "JSON object expected"}), 400

        if "building_id" in payload:
            summary = _load_outputs()["summary"]
            match = summary.loc[summary["building_id"] == payload["building_id"]]
            if match.empty:
                return jsonify({"error": f"Unknown building_id '{payload['building_id']}'"}), 404
            quote = commercial_quote(match.iloc[0])
            quote["building_id"] = payload["building_id"]
            return jsonify(quote)

        required = {"tiv_kes", "expected_annual_loss_kes", "risk_class", "confidence"}
        missing = sorted(required - set(payload))
        if missing:
            return jsonify({"error": "Missing required fields", "missing": missing}), 400

        return jsonify(commercial_quote(payload))

    @app.get("/metrics")
    def metrics():
        return jsonify(_load_outputs()["metrics"])

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
