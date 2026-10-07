"""Data-loading tests (synthetic raster) and output-contract tests on produced files if present."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import config
from src.data import Raster, haversine_m, nearest_point_distance, data_quality_report
from src.pipeline import RISK_PREDICTION_COLUMNS


def test_raster_rowcol_and_sample(tiny_raster):
    row, col = tiny_raster.rowcol([-1.255], [36.755])
    assert (row[0], col[0]) == (5, 5)
    assert tiny_raster.sample([-1.255], [36.755])[0] == 1.0
    assert np.isnan(tiny_raster.sample([0.0], [0.0]))[0]          # outside -> fill


def test_haversine_known_distance():
    # one degree of latitude at the equator is ~111.2 km
    assert haversine_m(0, 36.8, 1, 36.8) == pytest.approx(111_195, rel=0.01)


def test_nearest_point_distance_picks_closest():
    d, idx = nearest_point_distance([-1.30], [36.80], [-1.0, -1.31], [36.8, 36.80])
    assert idx[0] == 1 and d[0] < 2000


def test_data_quality_report_counts_missing():
    df = pd.DataFrame({"a": [1.0, None, 3.0], "b": ["x", "y", "y"]})
    rep = data_quality_report(df).set_index("column")
    assert rep.loc["a", "missing"] == 1 and rep.loc["b", "unique"] == 2


@pytest.mark.skipif(not (config.OUTPUT_DIR / "risk_predictions.csv").exists(),
                    reason="pipeline outputs not generated yet")
def test_risk_predictions_contract():
    df = pd.read_csv(config.OUTPUT_DIR / "risk_predictions.csv")
    assert list(df.columns) == RISK_PREDICTION_COLUMNS
    assert df["is_synthetic"].all()
    assert df.groupby("building_id").size().nunique() == 1        # same scenarios for every building
    assert set(df["scenario"]) == {s["name"] for s in config.SCENARIOS}
    assert (df["damage_ratio"].between(0, 0.95)).all()
    assert np.allclose(df["expected_loss_kes"], df["damage_ratio"] * df["exposure_kes"])
    assert df["confidence"].isin(["high", "medium", "low"]).all()
    # portfolio loss must not fall as the return period lengthens
    ep = df.groupby("return_period_years")["expected_loss_kes"].sum().sort_index()
    assert np.all(np.diff(ep.values) >= 0)
