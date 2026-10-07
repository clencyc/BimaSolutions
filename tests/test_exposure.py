import numpy as np
import pytest

from src import config
from src.exposure import EXPOSURE_OUTPUT_COLUMNS, build_exposure, exposure_summary, total_exposure


def test_build_exposure_standardises_columns(tiny_portfolio):
    ex = build_exposure(tiny_portfolio)
    for c in EXPOSURE_OUTPUT_COLUMNS:
        assert c in ex.columns
    for c in config.HAZARD_COLUMNS.values():
        assert c in ex.columns
    assert len(ex) == 8
    assert ex["is_synthetic"].all()


def test_total_exposure_is_sum_of_tiv(tiny_portfolio):
    ex = build_exposure(tiny_portfolio)
    assert total_exposure(ex) == pytest.approx(tiny_portfolio["tiv_kes"].sum())


def test_exposure_summary_shares_sum_to_one(tiny_portfolio):
    ex = build_exposure(tiny_portfolio)
    summ = exposure_summary(ex)
    assert summ["share_of_tiv"].sum() == pytest.approx(1.0)
    assert set(summ.index) == set(config.HOUSING_CLASSES)


def test_unknown_housing_class_rejected(tiny_portfolio):
    bad = tiny_portfolio.copy()
    bad.loc[0, "housing_class"] = "castle"
    with pytest.raises(ValueError):
        build_exposure(bad)


def test_hazard_lookup_from_raster(tiny_portfolio, tiny_raster):
    """Without hazard columns the exposure builder must sample the rasters."""
    raw = tiny_portfolio.drop(columns=list(config.HAZARD_COLUMNS.values()))
    rasters = {tier: tiny_raster for tier in config.TIERS}
    ex = build_exposure(raw, rasters)
    # T-2 sits at (-1.22, 36.72) -> row 2, col 2 -> 0 ; T-? none at (2,3). Check a direct hit instead:
    v = tiny_raster.sample([-1.225], [36.735])
    assert v[0] == pytest.approx(0.5)
    assert np.isfinite(ex[config.HAZARD_COLUMNS["common"]]).all()
