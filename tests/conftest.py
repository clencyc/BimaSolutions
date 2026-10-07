"""Small synthetic fixtures. These are NOT derived from Dataset/ and never mix with it."""
import numpy as np
import pandas as pd
import pytest

from src.data import Raster


@pytest.fixture
def tiny_portfolio() -> pd.DataFrame:
    """Eight synthetic buildings (classes cycled) with nested tier scores built from S."""
    s = np.array([0.0, 0.05, 0.10, 0.20, 0.30, 0.45, 0.60, 0.90])
    thresholds = {"common": 0.0, "occasional": 0.0862, "moderate": 0.1729,
                  "severe": 0.2805, "extreme": 0.3742}
    classes = ["informal_iron_sheet", "semi_permanent", "permanent_masonry", "concrete_rcc"] * 2
    area = np.array([10, 40, 100, 500, 12, 50, 120, 800])
    cost = np.array([8000, 12000, 50000, 70000, 9000, 11000, 45000, 60000])
    df = pd.DataFrame({
        "loc_id": [f"T-{i}" for i in range(8)],
        "lat": -1.20 - 0.01 * np.arange(8),
        "lon": 36.70 + 0.01 * np.arange(8),
        "housing_class": classes,
        "floor_area_m2": area,
        "cost_per_m2_kes": cost,
        "tiv_kes": (10.0 * area * cost),
        "synthetic": [True] * 8,
        "source": ["unit-test fixture"] * 8,
    })
    for tier, t in thresholds.items():
        df[f"hazard_score_{tier}"] = np.clip((s - t) / (1 - t), 0, 1)
    return df


@pytest.fixture
def tiny_raster() -> Raster:
    """A 10x10 raster covering lon 36.70-36.80, lat -1.20 to -1.30 (0.01 deg pixels)."""
    vals = np.zeros((10, 10), dtype=np.float32)
    vals[2, 3] = 0.5      # row 2 -> lat -1.225 ; col 3 -> lon 36.735
    vals[5, 5] = 1.0
    return Raster(values=vals, x_origin=36.70, y_origin=-1.20, x_res=0.01, y_res=0.01)
