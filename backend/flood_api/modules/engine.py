"""
Core deterministic flood loss engine.
Pure functions: same inputs and config give identical outputs.
Handles hazard -> depth -> vulnerability -> damage -> loss pipeline.
"""

from typing import Dict, List, Tuple
from decimal import Decimal
from scipy.interpolate import interp1d
import numpy as np


def interpolate_damage(depth_m: float, curve_pairs: List[Tuple[float, float]]) -> float:
    """
    Interpolate damage ratio from depth-damage curve.
    Returns damage ratio (0.0-1.0, capped at 0.9).

    Args:
        depth_m: Flood depth in metres.
        curve_pairs: List of [depth, damage_ratio] pairs.

    Returns:
        Damage ratio (0.0-0.9).
    """
    if not curve_pairs or len(curve_pairs) < 2:
        raise ValueError("Curve must have at least 2 points")

    depths = np.array([p[0] for p in curve_pairs])
    damages = np.array([p[1] for p in curve_pairs])

    f = interp1d(depths, damages, kind="linear", fill_value="extrapolate")
    damage = float(f(depth_m))

    return min(max(0.0, damage), 0.9)


def calculate_depth_from_hazard(hazard_score: float, max_depth_m: float) -> float:
    """
    Convert hazard score (0-1) to depth in metres.
    Hazard score is a proxy susceptibility, not measured depth.

    Args:
        hazard_score: Susceptibility score (0.0-1.0).
        max_depth_m: Maximum depth assumption.

    Returns:
        Depth in metres.
    """
    if not (0.0 <= hazard_score <= 1.0):
        raise ValueError(f"Hazard score must be 0-1, got {hazard_score}")
    return hazard_score * max_depth_m


def calculate_loss_for_building(
    damage_ratio: float, insured_value_ksh: Decimal
) -> Decimal:
    """
    Calculate loss for a single building.
    Loss = damage_ratio × insured_value.

    Args:
        damage_ratio: Damage ratio (0.0-0.9).
        insured_value_ksh: Insured value in KSH.

    Returns:
        Loss in KSH.
    """
    if not (0.0 <= damage_ratio <= 1.0):
        raise ValueError(f"Damage ratio must be 0-1, got {damage_ratio}")
    return Decimal(str(damage_ratio)) * insured_value_ksh


def portfolio_loss_per_tier(
    buildings: List[Dict],
    tier_key: str,
    config: Dict,
) -> Decimal:
    """
    Calculate portfolio loss for a single return period tier.
    Sums losses across all buildings after applying damage curves.

    Args:
        buildings: List of building dicts with hazard scores and insured values.
        tier_key: Hazard tier key (common, occasional, etc.).
        config: Config dict with max_depth_m, damage curves, cap.

    Returns:
        Total portfolio loss for this tier in KSH.
    """
    total_loss = Decimal(0)
    max_depth_m = config["hazard"]["max_depth_m"]
    damage_cap = config["vulnerability"]["damage_cap"]

    for building in buildings:
        hazard_score = building.get(f"{tier_key}_hazard")
        if hazard_score is None:
            continue

        depth = calculate_depth_from_hazard(hazard_score, max_depth_m)
        construction_class = building["construction_class"]
        curve_pairs = config["vulnerability"]["construction_classes"][
            construction_class
        ]["depth_damage_curve"]["pairs"]
        damage = interpolate_damage(depth, curve_pairs)
        damage = min(damage, damage_cap)

        loss = calculate_loss_for_building(damage, building["insured_value_ksh"])
        total_loss += loss

    return total_loss


def calculate_annual_average_loss(
    losses_per_period: Dict[str, Tuple[int, Decimal]],
) -> Decimal:
    """
    Calculate AAL using trapezoid integration over return periods.
    Assumes losses are sorted by return period and represents
    the integral of loss vs. exceedance probability.

    Args:
        losses_per_period: Dict keyed by tier name, values are (return_period, loss_ksh).

    Returns:
        Annual average loss in KSH.
    """
    if not losses_per_period:
        return Decimal(0)

    sorted_items = sorted(
        losses_per_period.items(), key=lambda x: x[1][0]
    )

    return_periods = np.array([rp for _, (rp, _) in sorted_items])
    exceedance_probs = 1.0 / return_periods
    losses_float = np.array(
        [float(loss) for _, (_, loss) in sorted_items]
    )

    aal = np.trapz(losses_float, exceedance_probs)
    return Decimal(str(max(0.0, aal)))


def validate_damage_bounds(damage_ratio: float) -> None:
    """Ensure damage ratio is within [0, 1] (capping applied separately)."""
    if not (0.0 <= damage_ratio <= 1.0):
        raise ValueError(f"Damage ratio {damage_ratio} outside [0, 1]")


def validate_ep_curve_monotonicity(ep_points: List[Tuple[float, float]]) -> None:
    """Verify EP curve is monotonically non-decreasing (loss increases with prob)."""
    sorted_points = sorted(ep_points, key=lambda x: x[0])
    for i in range(len(sorted_points) - 1):
        if sorted_points[i][1] > sorted_points[i + 1][1]:
            raise ValueError(
                f"EP curve not monotonic: loss decreased from "
                f"{sorted_points[i][1]} to {sorted_points[i + 1][1]}"
            )


def apply_adjustment_to_score(
    original_score: float,
    adjustment_type: str,
    magnitude: float,
) -> float:
    """
    Apply an adjustment (additive or multiplicative) to a hazard score.
    Result is always capped at 1.0.

    Args:
        original_score: Original hazard score (0-1).
        adjustment_type: 'additive' or 'multiplicative'.
        magnitude: Adjustment magnitude.

    Returns:
        Adjusted score (0-1), capped at 1.0.
    """
    if adjustment_type == "additive":
        adjusted = original_score + magnitude
    elif adjustment_type == "multiplicative":
        adjusted = original_score * magnitude
    else:
        raise ValueError(f"Unknown adjustment type: {adjustment_type}")

    return min(max(0.0, adjusted), 1.0)
