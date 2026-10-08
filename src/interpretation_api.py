"""Interpretation-only API.

This service is intentionally separate from the model/calculation API.
It accepts model-output JSON, then uses an LLM only to explain or summarize
results in plain language. It must not be used for calculating loss, premium,
confidence, EP curves, or any other financial or risk formula.
"""
from __future__ import annotations

import json
import os
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from flask import Flask, jsonify, request


DEFAULT_GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")


def _safe_json(value: Any) -> Any:
    if value is None:
        return {}
    if isinstance(value, (dict, list, str, int, float, bool)):
        return value
    return str(value)


def _extract_summary_signal(payload: dict[str, Any]) -> str:
    """Create a deterministic summary signal without doing model math."""
    summary = payload.get("portfolio_summary") or {}
    building_rows = payload.get("building_risk_summary") or []

    if isinstance(building_rows, dict):
        building_rows = list(building_rows.values())

    top_risk = None
    if building_rows:
        try:
            top_risk = max(building_rows, key=lambda x: float(x.get("risk_score", 0.0)))
        except Exception:
            top_risk = building_rows[0]

    aal = summary.get("portfolio_aal_kes") or {}
    ml_aal = None
    if isinstance(aal, dict):
        ml_aal = aal.get("ml_augmented") or aal.get("proxy_plus_hotspots") or aal.get("baseline_proxy")

    if top_risk:
        return (
            f"Highest-risk building: {top_risk.get('building_id', 'unknown')} with risk score "
            f"{top_risk.get('risk_score', 'n/a')}."
        )
    if ml_aal is not None:
        return f"Portfolio AAL is {ml_aal:.2f} KES in the adopted model view."
    return "The model outputs indicate elevated flood risk in the current portfolio."


def _fallback_summary(payload: dict[str, Any]) -> dict[str, Any]:
    signal = _extract_summary_signal(payload)
    return {
        "summary": signal,
        "key_findings": [
            "The summary is generated from the model output payload provided to the interpretation API.",
            "This layer is explanatory only and does not recalculate risk or premium values.",
        ],
        "interpretation_only": True,
    }


def _fallback_answer(question: str, payload: dict[str, Any]) -> str:
    ctx = json.dumps(payload, default=str)[:2500]
    return (
        f"Based on the provided model output, the answer to '{question}' should be derived from the model results already supplied. "
        f"This interpretation service does not calculate risk or pricing; it explains the provided outputs. "
        f"Context preview: {ctx}"
    )


def _call_groq(prompt: str) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured")

    model = os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)
    base_url = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1/chat/completions")
    data = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a plain-language risk interpretation assistant. "
                    "Use only the provided model output JSON. "
                    "Do not calculate numbers or invent formulas. "
                    "Explain the result clearly and concisely."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0.2,
        "max_tokens": 500,
    }

    req = urlrequest.Request(
        base_url,
        data=json.dumps(data).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urlrequest.urlopen(req, timeout=30) as resp:
        response = json.loads(resp.read().decode("utf-8"))

    content = response["choices"][0]["message"]["content"]
    return str(content).strip()


def _generate_summary(payload: dict[str, Any]) -> dict[str, Any]:
    if not os.getenv("GROQ_API_KEY"):
        return _fallback_summary(payload)

    try:
        model_payload = json.dumps(_safe_json(payload), default=str)
        prompt = (
            "Summarize the following model output in plain English for a dashboard user. "
            "Do not create new calculations. Explain only what is already visible in the JSON.\n\n"
            f"MODEL_OUTPUT_JSON:\n{model_payload}"
        )
        text = _call_groq(prompt)
        return {
            "summary": text,
            "interpretation_only": True,
            "source": "groq",
        }
    except (RuntimeError, KeyError, ValueError, urlerror.URLError) as exc:
        return {
            **_fallback_summary(payload),
            "warning": f"LLM unavailable; used fallback summary. Details: {exc}",
        }


def _answer_question(question: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not question or not str(question).strip():
        return {"error": "A non-empty question is required", "error_type": "invalid_request"}, 400

    if not os.getenv("GROQ_API_KEY"):
        return {
            "answer": _fallback_answer(question, payload),
            "interpretation_only": True,
            "source": "fallback",
        }

    try:
        model_payload = json.dumps(_safe_json(payload), default=str)
        prompt = (
            "Answer the user's question using only the provided model output JSON. "
            "Do not recalculate, do not invent numbers, and do not produce formula results. "
            "Keep the answer concise and grounded in the provided data.\n\n"
            f"QUESTION: {question}\n\nMODEL_OUTPUT_JSON:\n{model_payload}"
        )
        text = _call_groq(prompt)
        return {
            "answer": text,
            "interpretation_only": True,
            "source": "groq",
        }
    except (RuntimeError, KeyError, ValueError, urlerror.URLError) as exc:
        return {
            "answer": _fallback_answer(question, payload),
            "interpretation_only": True,
            "source": "fallback",
            "warning": f"LLM unavailable; used fallback answer. Details: {exc}",
        }


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "interpretation_only"})

    @app.post("/api/interpretation/summary")
    def summary_endpoint():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"error": "JSON body must be an object", "error_type": "invalid_request"}), 400
        return jsonify(_generate_summary(payload))

    @app.post("/api/interpretation/question")
    def question_endpoint():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"error": "JSON body must be an object", "error_type": "invalid_request"}), 400

        question = payload.get("question") or payload.get("query")
        context = payload.get("context") or payload
        return jsonify(_answer_question(str(question), context if isinstance(context, dict) else {}))

    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5001"))
    create_app().run(host="0.0.0.0", port=port, debug=False)
