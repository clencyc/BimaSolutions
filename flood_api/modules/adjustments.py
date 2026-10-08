"""AI hazard adjustment handling and explicit application logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from flood_api.modules.hazard import apply_adjustment_to_hazard_score


@dataclass
class AdjustmentRecord:
    adjustment_id: str
    area_or_neighbourhood: str
    adjustment_type: str
    magnitude: float
    cause: str
    confidence: float
    source_reference: str
    reasoning_text: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    building_ids: Optional[List[str]] = None
    final_score_cap: float = 1.0


@dataclass
class AdjustmentSet:
    adjustment_set_id: str
    adjustments: List[AdjustmentRecord] = field(default_factory=list)
    created_by: str = "ai-layer"
    source: str = "ai_derived"

    def apply_to_score(self, original_score: float, target_area: Optional[str] = None) -> float:
        """Apply all relevant adjustments to a hazard score. Explicitly reversible by model run."""
        adjusted_score = float(original_score)
        for adjustment in self.adjustments:
            if target_area and adjustment.area_or_neighbourhood != target_area:
                continue
            adjusted_score = apply_adjustment_to_hazard_score(
                adjusted_score,
                adjustment.adjustment_type,
                adjustment.magnitude,
            )
        return max(0.0, min(1.0, adjusted_score))


class AdjustmentStore:
    def __init__(self) -> None:
        self._sets: Dict[str, AdjustmentSet] = {}

    def add_set(self, adjustment_set: AdjustmentSet) -> str:
        self._sets[adjustment_set.adjustment_set_id] = adjustment_set
        return adjustment_set.adjustment_set_id

    def get(self, adjustment_set_id: str) -> Optional[AdjustmentSet]:
        return self._sets.get(adjustment_set_id)

    def list_ids(self) -> List[str]:
        return list(self._sets.keys())


def validate_adjustment_item(item: Dict[str, Any]) -> None:
    """Strict validation for AI-supplied hazard adjustments."""
    if item.get("adjustment_type") == "additive":
        if not (-1.0 <= float(item["magnitude"]) <= 0.5):
            raise ValueError("Additive magnitude must be between -1.0 and +0.5")
    elif item.get("adjustment_type") == "multiplicative":
        if not (0.5 <= float(item["magnitude"]) <= 2.0):
            raise ValueError("Multiplicative magnitude must be between 0.5 and 2.0")
    else:
        raise ValueError("adjustment_type must be 'additive' or 'multiplicative'")

    if not (0.0 <= float(item.get("confidence", 0.0)) <= 1.0):
        raise ValueError("confidence must be in [0, 1]")

    if not item.get("source_reference"):
        raise ValueError("source_reference is required")

    if not item.get("reasoning_text"):
        raise ValueError("reasoning_text is required")
