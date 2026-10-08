"""
Unit tests for the deterministic flood loss engine.
Tests the core pipeline: hazard -> depth -> damage -> loss with strict invariants.
"""

import pytest
from decimal import Decimal
from flood_api.config import get_current_config
from flood_api.modules.vulnerability import interpolate_damage, damage_ratio_for_construction
from flood_api.modules.engine import (
    depth_from_hazard_score,
    loss_for_building,
    portfolio_loss_by_tier,
    calculate_aal,
    ep_curve_points,
    apply_adjustment_set_to_rows,
)
from flood_api.modules.adjustments import AdjustmentRecord, AdjustmentSet
from flood_api.modules.hazard import apply_adjustment_to_hazard_score


class TestDamageInterpolation:
    """Damage curve interpolation must remain within [0, cap]."""

    def test_interpolate_zero_depth_zero_damage(self):
        curve = [[0.0, 0.0], [1.0, 0.5], [2.0, 0.8]]
        assert interpolate_damage(0.0, curve) == 0.0

    def test_interpolate_linear_midpoint(self):
        curve = [[0.0, 0.0], [2.0, 0.8]]
        damage = interpolate_damage(1.0, curve)
        assert 0.39 < damage < 0.41, f"Expected ~0.4, got {damage}"

    def test_damage_capped_at_0_9(self):
        curve = [[0.0, 0.0], [1.0, 1.0]]
        damage = interpolate_damage(5.0, curve, cap=0.9)
        assert damage == 0.9

    def test_damage_never_negative(self):
        curve = [[0.0, 0.0], [1.0, 0.5]]
        damage = interpolate_damage(-1.0, curve)
        assert damage >= 0.0


class TestHazardScoreToDamage:
    """Hazard scores are 0-1 proxies; they map to depth and then damage."""

    def test_zero_hazard_zero_loss(self):
        config = get_current_config()
        building = {
            "construction_class": "masonry",
            "insured_value_ksh": Decimal("1000000"),
            "common_hazard": 0.0,
        }
        loss = loss_for_building(building, "common", config)
        assert loss == Decimal(0), "Zero hazard must yield zero loss"

    def test_hazard_creates_depth(self):
        depth_0_5 = depth_from_hazard_score(0.5, get_current_config())
        depth_1_0 = depth_from_hazard_score(1.0, get_current_config())
        assert depth_1_0 == 2 * depth_0_5, "Depth must scale linearly with hazard"

    def test_hazard_score_out_of_range_raises(self):
        with pytest.raises(ValueError):
            depth_from_hazard_score(1.1, get_current_config())
        with pytest.raises(ValueError):
            depth_from_hazard_score(-0.1, get_current_config())


class TestAdjustments:
    """Adjustments must never push scores above 1.0 and must be reversible."""

    def test_additive_adjustment_capped(self):
        score = 0.9
        adjusted = apply_adjustment_to_hazard_score(score, "additive", 0.3)
        assert adjusted == 1.0, "Additive adjustment must cap at 1.0"

    def test_multiplicative_adjustment_capped(self):
        score = 0.8
        adjusted = apply_adjustment_to_hazard_score(score, "multiplicative", 2.0)
        assert adjusted == 1.0, "Multiplicative adjustment must cap at 1.0"

    def test_negative_additive_adjustment(self):
        score = 0.5
        adjusted = apply_adjustment_to_hazard_score(score, "additive", -0.2)
        assert adjusted == 0.3

    def test_multiplicative_below_one(self):
        score = 0.8
        adjusted = apply_adjustment_to_hazard_score(score, "multiplicative", 0.5)
        assert adjusted == 0.4

    def test_adjustment_never_negative(self):
        score = 0.2
        adjusted = apply_adjustment_to_hazard_score(score, "additive", -0.5)
        assert adjusted >= 0.0, "Adjustment result must never be negative"


class TestEPCurveMonotonicity:
    """EP curve loss must increase with lower exceedance probability (longer return periods)."""

    def test_ep_curve_is_sorted(self):
        config = get_current_config()
        losses = {
            "common": Decimal("100000"),
            "occasional": Decimal("150000"),
            "moderate": Decimal("200000"),
            "severe": Decimal("250000"),
            "extreme": Decimal("300000"),
        }
        points = ep_curve_points(losses, config)
        
        # Points should be sorted by exceedance probability descending
        for i in range(len(points) - 1):
            assert points[i]["annual_exceedance_probability"] >= points[i + 1]["annual_exceedance_probability"]

    def test_ep_curve_loss_increases(self):
        config = get_current_config()
        losses = {
            "common": Decimal("100000"),
            "occasional": Decimal("150000"),
            "moderate": Decimal("200000"),
            "severe": Decimal("250000"),
            "extreme": Decimal("300000"),
        }
        points = ep_curve_points(losses, config)
        
        for i in range(len(points) - 1):
            # Lower exceedance probability should have higher or equal loss
            if points[i]["annual_exceedance_probability"] < points[i + 1]["annual_exceedance_probability"]:
                assert points[i]["loss_ksh"] <= points[i + 1]["loss_ksh"]


class TestAAL:
    """Average Annual Loss calculated via trapezoid integration."""

    def test_aal_zero_portfolio(self):
        config = get_current_config()
        losses = {}
        aal = calculate_aal(losses, config)
        assert aal == Decimal(0)

    def test_aal_single_tier(self):
        config = get_current_config()
        losses = {"common": Decimal("100000")}
        aal = calculate_aal(losses, config)
        assert aal >= Decimal(0)

    def test_aal_increases_with_loss(self):
        config = get_current_config()
        losses_a = {
            "common": Decimal("100000"),
            "occasional": Decimal("150000"),
        }
        losses_b = {
            "common": Decimal("200000"),
            "occasional": Decimal("300000"),
        }
        aal_a = calculate_aal(losses_a, config)
        aal_b = calculate_aal(losses_b, config)
        assert aal_b > aal_a, "Larger losses should yield larger AAL"


class TestPortfolioLoss:
    """Portfolio loss aggregates building losses correctly."""

    def test_empty_portfolio_zero_loss(self):
        config = get_current_config()
        rows = []
        loss = portfolio_loss_by_tier(rows, "common", config)
        assert loss == Decimal(0)

    def test_missing_hazard_skipped(self):
        config = get_current_config()
        rows = [
            {
                "construction_class": "masonry",
                "insured_value_ksh": Decimal("1000000"),
                "common_hazard": None,
            }
        ]
        loss = portfolio_loss_by_tier(rows, "common", config)
        assert loss == Decimal(0)

    def test_portfolio_loss_sum(self):
        config = get_current_config()
        rows = [
            {
                "construction_class": "masonry",
                "insured_value_ksh": Decimal("1000000"),
                "common_hazard": 0.5,
            },
            {
                "construction_class": "masonry",
                "insured_value_ksh": Decimal("1000000"),
                "common_hazard": 0.5,
            },
        ]
        loss = portfolio_loss_by_tier(rows, "common", config)
        assert loss > Decimal(0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
