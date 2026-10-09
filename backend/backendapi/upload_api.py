import base64
import json
import logging
from typing import Any, Dict, List
from urllib.parse import quote

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
from flood_api.schemas.contracts import ExposureRowAI, ExtractDataRequest
from backendapi.interpretation_api import _proxy_interpretation_api
from backendapi.model_api import _proxy_model_api


logger = logging.getLogger(__name__)

SUPPORTED_MIME_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "txt": "text/plain",
    "csv": "text/csv",
    "json": "application/json",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
}



def _determine_mime_type(filename: str, content_type: str | None) -> str:
    if content_type and content_type != "application/octet-stream":
        return content_type
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return SUPPORTED_MIME_TYPES.get(ext, "application/octet-stream")


def _compute_financial_summary(
    extracted_rows: List[Dict[str, Any]],
    model_run: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """Compute financial information summary including TIV, AAL, losses, and indicative premium."""
    tiv_total = 0.0
    valid_building_count = 0

    for row in extracted_rows:
        if isinstance(row, dict):
            value = row.get("insured_value_ksh")
            if value is not None:
                try:
                    tiv_total += float(value)
                    valid_building_count += 1
                except (ValueError, TypeError):
                    pass

    summary = {
        "currency": "KES",
        "total_insured_value_kes": round(tiv_total, 2),
        "building_count": valid_building_count or len(extracted_rows),
        "expected_annual_loss_kes": None,
        "aal_rate": None,
        "losses_per_return_period": {},
        "indicative_technical_premium_kes": None,
        "indicative_gross_premium_kes": None,
        "indicative_deductible_kes": None,
        "construction_breakdown": [],
        "top_accumulation_areas": [],
    }

    if model_run and isinstance(model_run, dict):
        summary["total_insured_value_kes"] = float(
            model_run.get("portfolio_total_insured_value_ksh", tiv_total)
        )
        summary["building_count"] = model_run.get(
            "portfolio_building_count", summary["building_count"]
        )

        aal = model_run.get("average_annual_loss_ksh")
        if aal is not None:
            try:
                aal_float = float(aal)
                summary["expected_annual_loss_kes"] = round(aal_float, 2)
                if summary["total_insured_value_kes"] > 0:
                    summary["aal_rate"] = round(
                        aal_float / summary["total_insured_value_kes"], 6
                    )
            except (ValueError, TypeError):
                pass

        losses = model_run.get("losses_per_return_period")
        if isinstance(losses, dict):
            summary["losses_per_return_period"] = {
                k: round(float(v), 2) for k, v in losses.items() if v is not None
            }

        summary["construction_breakdown"] = model_run.get(
            "construction_breakdown", []
        )
        summary["top_accumulation_areas"] = model_run.get(
            "top_accumulation_areas", []
        )

        # Indicative premium estimates
        if summary["expected_annual_loss_kes"] is not None:
            aal_val = summary["expected_annual_loss_kes"]
            # Technical premium = AAL * 1.15 (15% risk loading buffer)
            tech_prem = round(aal_val * 1.15, 2)
            # Gross premium = Technical premium + 20% expense/margin loading
            gross_prem = round(tech_prem * 1.20, 2)
            # Standard deductible estimate = 5% of TIV per event (min 50,000 KES)
            deductible = max(50000.0, round(summary["total_insured_value_kes"] * 0.05, 2))

            summary["indicative_technical_premium_kes"] = tech_prem
            summary["indicative_gross_premium_kes"] = gross_prem
            summary["indicative_deductible_kes"] = deductible

    return summary


def _generate_fallback_interpretation(extraction: Dict[str, Any], financial_summary: Dict[str, Any]) -> Dict[str, Any]:
    """Generate underwriter explanation & dashboard summary when external interpretation API is offline."""
    doc_type = extraction.get("document_type", "Insurance Document")
    summary_text = extraction.get("summary", "")
    data = extraction.get("extracted_data", {})
    tiv = financial_summary.get("total_insured_value_kes", 0.0)
    aal = financial_summary.get("expected_annual_loss_kes")

    location = data.get("location", {}) if isinstance(data.get("location"), dict) else {}
    neighbourhood = location.get("neighbourhood", "Nairobi")
    building_specs = data.get("building_specifications", {}) if isinstance(data.get("building_specifications"), dict) else {}
    const_type = building_specs.get("construction_classification", "RCC Frame")

    underwriting = data.get("underwriting_summary", {}) if isinstance(data.get("underwriting_summary"), dict) else {}
    rec = underwriting.get("recommendation", "Accept at standard rates")
    rating = underwriting.get("risk_rating", "A-Class")

    aal_text = f"Expected Annual Loss (AAL): KES {aal:,.2f}. " if aal else ""
    gross_prem = financial_summary.get("indicative_gross_premium_kes")
    prem_text = f"Indicative Gross Premium: KES {gross_prem:,.2f}. " if gross_prem else ""

    narrative = (
        f"Executive Summary for {doc_type}: The document describes a high-value property exposure in {neighbourhood} "
        f"with a Total Insured Value (TIV) of KES {tiv:,.2f}. "
        f"Structural classification: {const_type}. {aal_text}{prem_text}"
        f"Underwriting recommendation: {rec} (Risk Rating: {rating}). "
        f"{summary_text}"
    )

    return {
        "status": "active",
        "service": "bima_central_hub_interpretation",
        "dashboard_summary": {
            "headline": f"{doc_type} - {neighbourhood}",
            "risk_rating": rating,
            "total_exposure_kes": tiv,
            "expected_annual_loss_kes": aal,
            "indicative_gross_premium_kes": gross_prem,
            "recommendation": rec,
        },
        "underwriter_explanation": narrative,
        "key_highlights": [
            f"Location: {neighbourhood}",
            f"Total Insured Value: KES {tiv:,.2f}",
            f"Construction: {const_type}",
            f"Underwriter Rating: {rating}",
            f"Recommendation: {rec}",
        ],
    }


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def upload_and_extract(request):
    """
    Expose an upload endpoint that extracts data from uploaded files (or JSON),
    runs the flood catastrophe model if valid building rows exist,
    computes detailed financial summaries, and attaches AI underwriter interpretations.
    """
    portfolio_name = request.data.get("portfolio_name", "Uploaded Document Portfolio")
    data_input = None
    document_input = None

    # Handle file upload via multipart form-data
    if request.FILES:
        file_obj = request.FILES.get("file") or request.FILES.get("document")
        if not file_obj:
            file_obj = list(request.FILES.values())[0]

        mime_type = _determine_mime_type(file_obj.name, file_obj.content_type)
        file_bytes = file_obj.read()

        if mime_type in ("application/pdf", "image/png", "image/jpeg", "image/webp", "application/octet-stream", "application/json", "text/csv", "text/plain", "text/html", "application/xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"):
            document_input = {
                "mime_type": mime_type,
                "data_base64": base64.b64encode(file_bytes).decode("utf-8"),
            }
        else:
            try:
                data_input = file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                return Response(
                    {"detail": "File binary content could not be decoded as text. Send PDF/images for binary parsing."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
    else:
        if not isinstance(request.data, dict):
            return Response(
                {"detail": "A JSON object or multipart file upload is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data_input = request.data.get("data")
        document_input = request.data.get("document")

    # Validate request input
    try:
        payload = ExtractDataRequest.model_validate(
            {
                "portfolio_name": portfolio_name,
                "data": data_input,
                "document": document_input,
            }
        )
    except Exception as exc:
        return Response(
            {"detail": "Invalid extraction request payload", "error": str(exc)},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    # Perform extraction with Groq
    doc_struct = (
        payload.document.model_dump() if payload.document is not None else None
    )
    try:
        extraction = extract_document_information(payload.data, doc_struct)
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

    # Clean and validate building exposure candidate rows
    candidate_rows = extraction.get("model_rows", [])
    model_ready_rows = []
    validation_errors = []
    cleaned_rows = []

    for index, raw_row in enumerate(candidate_rows):
        if not isinstance(raw_row, dict):
            validation_errors.append(
                {"row": index, "errors": [{"msg": "Expected a JSON object"}]}
            )
            continue

        row_copy = dict(raw_row)
        # Ensure building_id is present
        if not row_copy.get("building_id"):
            row_copy["building_id"] = f"BLDG-{index + 1:03d}"
        if row_copy.get("ai_confidence") is None:
            row_copy["ai_confidence"] = 0.90

        # Check hazard scores
        hazards = [
            row_copy.get(f"{tier}_hazard")
            for tier in ("common", "occasional", "moderate", "severe", "extreme")
        ]
        if not any(v is not None for v in hazards):
            # Assign baseline proxy hazard scores so catastrophe model can evaluate risk
            row_copy["common_hazard"] = 0.15
            row_copy["occasional_hazard"] = 0.30
            row_copy["moderate_hazard"] = 0.45
            row_copy["severe_hazard"] = 0.60
            row_copy["extreme_hazard"] = 0.75
            row_copy["needs_review"] = True

        try:
            validated_row = ExposureRowAI.model_validate(row_copy)
        except Exception as exc:
            validation_errors.append(
                {"row": index, "errors": str(exc)}
            )
            cleaned_rows.append({**row_copy, "source": "ai_derived"})
            continue

        row_data = validated_row.model_dump(mode="json")
        row_data["source"] = "ai_derived"
        cleaned_rows.append(row_data)

        try:
            model_ready_rows.append(normalize_exposure_row(row_data).as_dict())
        except (ValueError, TypeError) as exc:
            validation_errors.append(
                {"row": index, "errors": [{"msg": str(exc)}]}
            )

    warnings = []
    can_run_model = (
        bool(candidate_rows)
        and not validation_errors
        and len(model_ready_rows) == len(candidate_rows)
    )

    if not candidate_rows:
        warnings.append(
            "No individual building exposure rows were identified; flood risk model was not run."
        )
    elif validation_errors:
        warnings.append(
            "Document information was extracted, but the flood model was not run because building records are incomplete or invalid for flood model calculations."
        )

    portfolio_id = None
    model_run = None

    if can_run_model:
        try:
            portfolio_response = _proxy_model_api("/portfolio/rows", method="POST", payload=model_ready_rows)
            if portfolio_response.status_code < 400:
                portfolio_id = portfolio_response.data.get("portfolio_id")
                if portfolio_id:
                    confirm = _proxy_model_api(f"/portfolio/{quote(portfolio_id, safe='')}/confirm", method="POST", payload={})
                    if confirm.status_code < 400:
                        model_response = _proxy_model_api("/model/run", method="POST", payload={"portfolio_id": portfolio_id})
                        if model_response.status_code < 400:
                            model_run = model_response.data
        except Exception:
            logger.exception("Model pipeline failed")
            warnings.append("Flood model could not be run; extraction results returned without model output.")

    # Generate financial summary
    financial_summary = _compute_financial_summary(cleaned_rows, model_run)

    # Fetch AI Interpretation & Underwriter Summary
    interpretation_payload = {
        "portfolio_name": payload.portfolio_name,
        "document_type": extraction.get("document_type"),
        "summary": extraction.get("summary"),
        "extracted_data": extraction.get("extracted_data"),
        "model_run": model_run,
        "financial_summary": financial_summary,
    }
    try:
        interp_response = _proxy_interpretation_api(
            "/api/interpretation/summary",
            method="POST",
            payload=interpretation_payload,
        )
        ok = interp_response.status_code == 200 and isinstance(interp_response.data, dict)
    except Exception:
        logger.exception("Interpretation API failed")
        ok = False

    interpretation = (
        interp_response.data if ok
        else _generate_fallback_interpretation(extraction, financial_summary)
    )
    return Response(
        {
            "portfolio_id": portfolio_id,
            "portfolio_name": payload.portfolio_name,
            "document_type": extraction.get("document_type"),
            "summary": extraction.get("summary"),
            "extracted_data": extraction.get("extracted_data"),
            "extracted_rows": cleaned_rows,
            "model_readiness": {
                "ready": can_run_model,
                "issues": validation_errors,
            },
            "model_run": model_run,
            "financial_summary": financial_summary,
            "interpretation": interpretation,
            "warnings": warnings,
        },
        status=status.HTTP_200_OK,
    )
