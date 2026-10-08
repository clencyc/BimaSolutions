"""Hazard module for proxy flood scores and adjustment handling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class HazardRead:
    """Returned hazard value plus provenance metadata."""
    score: Optional[float]
    source: str
    note: str


def clamp_hazard_score(score: float) -> float:
    """Clamp hazard score to the valid 0-1 range."""
    if score is None:
        return 0.0
    return max(0.0, min(1.0, float(score)))


def lookup_raster_hazard(lat: float, lon: float, tier: str, raster_dir: Optional[str] = None) -> HazardRead:
    """
    Raster lookup stub. In the projected Nairobi model this would read a GeoTIFF.
    Since the supplied raster files are absent from the repo, we expose a deterministic stub
    and mark the result as `proxy` rather than inventing values.
    """
    if raster_dir is None:
        return HazardRead(
            score=None,
            source="proxy",
            note="Raster lookup requested but raster directory is not configured in this workspace.",
        )

    # The real implementation would query the appropriate tier raster at (lat, lon).
    # Here the function intentionally returns no value to avoid fabricating data.
    return HazardRead(
        score=None,
        source="proxy",
        note=f"Raster lookup for tier '{tier}' was requested but no raster files are available.",
    )


def apply_adjustment_to_hazard_score(score: float, adjustment_type: str, magnitude: float) -> float:
    """Apply an additive or multiplicative adjustment, then cap to 1.0."""
    if adjustment_type == "additive":
        adjusted = score + magnitude
    elif adjustment_type == "multiplicative":
        adjusted = score * magnitude
    else:
        raise ValueError(f"Unsupported adjustment type: {adjustment_type}")
    return clamp_hazard_score(adjusted)


def candidate_hotspots() -> List[Dict[str, Any]]:
    """Provide a minimal deterministic hotspot definition when the real CSV is absent."""
    return [
        {
            "hotspot_id": "HS-001",
            "name": "Kibera Drainage",
            "latitude": -1.310,
            "longitude": 36.780,
            "is_held_out": False,
        },
        {
            "hotspot_id": "HS-002",
            "name": "Mathare Market",
            "latitude": -1.286,
            "longitude": 36.832,
            "is_held_out": True,
        },
        {
            "hotspot_id": "HS-003",
            "name": "Nairobi River East",
            "latitude": -1.275,
            "longitude": 36.815,
            "is_held_out": False,
        },
    ]
