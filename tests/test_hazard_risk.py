import numpy as np
import pandas as pd
import pytest

from src import config
from src.exposure import build_exposure
from src.hazard import (augment_susceptibility, depth_from_susceptibility, hotspot_proximity_kernel,
                        infer_tier_thresholds, recall_at_matched_fpr, scenario_table,
                        severity_from_susceptibility)
from src.risk import (LONG_COLUMNS, average_annual_loss, building_summary, ep_curve,
                      rank_buildings, scenario_losses)


def test_infer_thresholds_recovers_fixture_values(tiny_portfolio):
    ex = build_exposure(tiny_portfolio)
    t = infer_tier_thresholds(ex)
    assert t["common"] == 0.0
    assert t["extreme"] == pytest.approx(0.3742, abs=1e-6)
    assert all(t[a] < t[b] for a, b in zip(config.TIERS[:-1], config.TIERS[1:]))


def test_scenario_table_thresholds_fall_as_events_get_rarer(tiny_portfolio):
    t = infer_tier_thresholds(build_exposure(tiny_portfolio))
    sc = scenario_table(t)
    assert list(sc["return_period_years"]) == sorted(sc["return_period_years"])
    assert np.all(np.diff(sc["susceptibility_threshold"].values) <= 0)
    assert np.all(np.diff(sc["max_depth_m"].values) >= 0)
    naive = scenario_table(t, mapping="naive")
    assert np.all(np.diff(naive["susceptibility_threshold"].values) >= 0)


def test_severity_and_depth_transforms():
    s = np.array([0.0, 0.2, 0.5, 1.0])
    assert np.allclose(severity_from_susceptibility(s, 0.0), s)
    assert np.allclose(severity_from_susceptibility(s, 0.5), [0, 0, 0, 1])
    assert np.allclose(depth_from_susceptibility(s, 0.0, 4.0), 4.0 * s)
    assert np.allclose(depth_from_susceptibility(s, 0.5, 4.0), [0, 0, 0, 2.0])


def test_loss_equals_damage_times_tiv(tiny_portfolio):
    ex = build_exposure(tiny_portfolio)
    sc = scenario_table(infer_tier_thresholds(ex))
    long = scenario_losses(ex, ex[config.HAZARD_COLUMNS["common"]].values, sc)
    assert list(long.columns) == LONG_COLUMNS
    assert len(long) == len(ex) * len(sc)
    m = long.merge(ex[["building_id", "tiv_kes"]], on="building_id")
    assert np.allclose(m["loss_kes"], m["damage_ratio"] * m["tiv_kes"])
    # zero susceptibility -> zero loss everywhere
    assert (long.loc[long["building_id"] == "T-0", "loss_kes"] == 0).all()


def test_ep_curve_is_monotone_in_return_period(tiny_portfolio):
    ex = build_exposure(tiny_portfolio)
    sc = scenario_table(infer_tier_thresholds(ex))
    ep = ep_curve(scenario_losses(ex, ex[config.HAZARD_COLUMNS["common"]].values, sc))
    assert np.all(np.diff(ep["portfolio_loss_kes"].values) >= 0)
    assert ep["portfolio_loss_kes"].iloc[-1] > 0


def test_average_annual_loss_trapezoid():
    # two scenarios: p=0.5 loss 100, p=0.1 loss 300 -> trapezoid 0.5*(100+300)*0.4 + tail 300*0.1
    aal = average_annual_loss([100.0, 300.0], [0.5, 0.1])
    assert aal == pytest.approx(80.0 + 30.0)
    two = average_annual_loss(np.array([[100.0, 300.0], [0.0, 0.0]]), [0.5, 0.1])
    assert two.shape == (2,) and two[1] == 0.0


def test_building_summary_and_ranking(tiny_portfolio):
    ex = build_exposure(tiny_portfolio)
    sc = scenario_table(infer_tier_thresholds(ex))
    long = scenario_losses(ex, ex[config.HAZARD_COLUMNS["common"]].values, sc)
    summ = rank_buildings(building_summary(ex, long))
    assert summ["rank_by_expected_loss"].iloc[0] == 1
    assert summ.loc[summ["building_id"] == "T-0", "risk_score"].iloc[0] == 0.0
    assert summ.loc[summ["building_id"] == "T-0", "risk_class"].iloc[0] == "negligible"
    assert summ["share_of_portfolio_aal"].sum() == pytest.approx(1.0)
    # T-6 (S=0.6) floods even in the 5-year scenario -> annual flood probability 0.2
    assert summ.loc[summ["building_id"] == "T-6", "annual_flood_probability"].iloc[0] == pytest.approx(0.2)
    # T-1 (S=0.05) floods only in the 250-year scenario -> 0.004
    assert summ.loc[summ["building_id"] == "T-1", "annual_flood_probability"].iloc[0] == pytest.approx(0.004)


def test_augmentation_gating_and_sources():
    s_proxy = np.array([0.0, 0.0, 0.3, 0.0])
    p = np.array([0.2, 0.9, 0.1, 0.0])
    k = np.array([0.0, 0.0, 0.0, 1.0])
    s_aug, src = augment_susceptibility(s_proxy, p, k, s_reference=0.4)
    assert s_aug[0] == 0.0 and src[0] == "none"            # below ML threshold: no hazard created
    assert s_aug[1] == pytest.approx(0.36) and src[1] == "ml_model"
    assert s_aug[2] == pytest.approx(0.3) and src[2] == "proxy"
    assert s_aug[3] == pytest.approx(0.4) and src[3] == "known_hotspot"
    s_nomal, _ = augment_susceptibility(s_proxy, p, k, 0.4, use_ml=False)
    assert s_nomal[1] == 0.0


def test_hotspot_kernel_cutoff():
    k = hotspot_proximity_kernel([0.0, 500.0, 2000.0], sigma_m=500.0, cutoff_m=1500.0)
    assert k[0] == pytest.approx(1.0)
    assert k[1] == pytest.approx(np.exp(-0.5))
    assert k[2] == 0.0


def test_recall_at_matched_fpr():
    y = np.array([1, 1, 0, 0, 0, 0])
    score = np.array([0.9, 0.25, 0.8, 0.3, 0.2, 0.1])
    rec, thr = recall_at_matched_fpr(y, score, 0.25)   # one negative (0.8) allowed above threshold
    assert thr == pytest.approx(0.3) and rec == pytest.approx(0.5)
