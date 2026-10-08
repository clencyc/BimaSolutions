"""Exposure utilities for portfolios and row validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class ExposureRow:
    building_id: str
    latitude: float
    longitude: float
    neighbourhood: str
    construction_class: str
    insured_value_ksh: Decimal
    common_hazard: Optional[float] = None
    occasional_hazard: Optional[float] = None
    moderate_hazard: Optional[float] = None
    severe_hazard: Optional[float] = None
    extreme_hazard: Optional[float] = None
    ai_confidence: Optional[float] = None
    needs_review: bool = False
    source: str = "synthetic"
    extraction_notes: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "building_id": self.building_id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "neighbourhood": self.neighbourhood,
            "construction_class": self.construction_class,
            "insured_value_ksh": float(self.insured_value_ksh),
            "common_hazard": self.common_hazard,
            "occasional_hazard": self.occasional_hazard,
            "moderate_hazard": self.moderate_hazard,
            "severe_hazard": self.severe_hazard,
            "extreme_hazard": self.extreme_hazard,
            "ai_confidence": self.ai_confidence,
            "needs_review": self.needs_review,
            "source": self.source,
            "extraction_notes": self.extraction_notes,
        }


@dataclass
class Portfolio:
    portfolio_id: str
    name: str
    rows: List[ExposureRow] = field(default_factory=list)
    status: str = "pending"
    source: str = "synthetic"

    @property
    def building_count(self) -> int:
        return len(self.rows)

    @property
    def total_insured_value_ksh(self) -> Decimal:
        return sum((row.insured_value_ksh for row in self.rows), Decimal(0))


def normalize_exposure_row(raw: Dict[str, Any]) -> ExposureRow:
    """Validate and normalize a single exposure row."""
    required = [
        "building_id",
        "latitude",
        "longitude",
        "neighbourhood",
        "construction_class",
        "insured_value_ksh",
    ]
    missing = [key for key in required if key not in raw]
    if missing:
        raise ValueError(f"Missing required exposure fields: {missing}")

    insured_value = Decimal(str(raw["insured_value_ksh"]))
    if insured_value <= 0:
        raise ValueError("insured_value_ksh must be > 0")

    return ExposureRow(
        building_id=str(raw["building_id"]),
        latitude=float(raw["latitude"]),
        longitude=float(raw["longitude"]),
        neighbourhood=str(raw["neighbourhood"]),
        construction_class=str(raw["construction_class"]),
        insured_value_ksh=insured_value,
        common_hazard=_to_optional_hazard(raw.get("common_hazard")),
        occasional_hazard=_to_optional_hazard(raw.get("occasional_hazard")),
        moderate_hazard=_to_optional_hazard(raw.get("moderate_hazard")),
        severe_hazard=_to_optional_hazard(raw.get("severe_hazard")),
        extreme_hazard=_to_optional_hazard(raw.get("extreme_hazard")),
        ai_confidence=_to_optional_float(raw.get("ai_confidence")),
        needs_review=bool(raw.get("needs_review", False)),
        extraction_notes=raw.get("extraction_notes"),
        source=str(raw.get("source", "synthetic")),
    )


def _to_optional_hazard(value: Any) -> Optional[float]:
    if value is None:
        return None
    val = float(value)
    if not (0.0 <= val <= 1.0):
        raise ValueError(f"Hazard score must be within 0..1; got {val}")
    return val


def _to_optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    val = float(value)
    return val


def build_sample_portfolio() -> Portfolio:
    """Create a minimal deterministic synthetic portfolio for testing without external data."""
    rows = [
        ExposureRow(
            building_id="B-001",
            latitude=-1.289,
            longitude=36.816,
            neighbourhood="Kibera",
            construction_class="informal_iron_sheet",
            insured_value_ksh=Decimal("2000000"),
            common_hazard=0.15,
            occasional_hazard=0.28,
            moderate_hazard=0.42,
            severe_hazard=0.55,
            extreme_hazard=0.70,
            ai_confidence=0.9,
            needs_review=False,
            source="synthetic",
        ),
        ExposureRow(
            building_id="B-002",
            latitude=-1.309,
            longitude=36.781,
            neighbourhood="Kibra",
            construction_class="masonry",
            insured_value_ksh=Decimal("3500000"),
            common_hazard=0.21,
            occasional_hazard=0.33,
            moderate_hazard=0.49,
            severe_hazard=0.62,
            extreme_hazard=0.75,
            ai_confidence=0.85,
            needs_review=False,
            source="synthetic",
        ),
        ExposureRow(
            building_id="B-003",
            latitude=-1.277,
            longitude=36.822,
            neighbourhood="Westlands",
            construction_class="rcc",
            insured_value_ksh=Decimal("8000000"),
            common_hazard=0.05,
            occasional_hazard=0.12,
            moderate_hazard=0.19,
            severe_hazard=0.27,
            extreme_hazard=0.33,
            ai_confidence=0.7,
            needs_review=False,
            source="synthetic",
        ),
    ]
    return Portfolio(portfolio_id="portfolio-demo-001", name="Demo Nairobi Portfolio", rows=rows, status="confirmed", source="synthetic")
