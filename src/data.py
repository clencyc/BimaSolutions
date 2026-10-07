"""Data loading and GeoTIFF sampling for the Nairobi starter kit.

The hazard rasters are plain single-band float32 GeoTIFFs in EPSG:4326 with a
north-up affine transform, so they can be read with Pillow + NumPy.  This
avoids a heavy GDAL/rasterio dependency.  The lookup is validated in the
notebook against the scores pre-attached to ``exposure_nairobi_with_hazard.csv``
(agreement to ~1e-16).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

from . import config

Image.MAX_IMAGE_PIXELS = None

# GeoTIFF tag ids
_TAG_PIXEL_SCALE = 33550
_TAG_TIEPOINT = 33922

REQUIRED_EXPOSURE_COLUMNS = [
    "loc_id", "lat", "lon", "housing_class", "floor_area_m2",
    "cost_per_m2_kes", "tiv_kes", "synthetic", "source",
]
REQUIRED_HOTSPOT_COLUMNS = ["name", "lat", "lon"]


@dataclass
class Raster:
    """A north-up raster with an affine geotransform (EPSG:4326)."""

    values: np.ndarray      # 2-D array [row, col]
    x_origin: float         # longitude of the top-left corner
    y_origin: float         # latitude of the top-left corner
    x_res: float            # degrees per pixel (east)
    y_res: float            # degrees per pixel (south, positive number)

    @property
    def shape(self) -> tuple[int, int]:
        return self.values.shape

    def pixel_size_m(self, lat_deg: float = -1.27) -> float:
        """Approximate ground size of one pixel in metres at a given latitude."""
        # ~110.6 km per degree of latitude; longitude pixels are ~cos(lat) narrower
        # but at 1.3 degrees south the difference is < 0.1%.
        return float(self.y_res * 110_574.0)

    def rowcol(self, lat, lon) -> tuple[np.ndarray, np.ndarray]:
        """Convert WGS84 coordinates to integer (row, col) indices."""
        col = np.floor((np.asarray(lon, dtype=float) - self.x_origin) / self.x_res).astype(int)
        row = np.floor((self.y_origin - np.asarray(lat, dtype=float)) / self.y_res).astype(int)
        return row, col

    def sample(self, lat, lon, fill: float = np.nan) -> np.ndarray:
        """Nearest-pixel lookup. Points outside the raster return ``fill``."""
        row, col = self.rowcol(lat, lon)
        ok = (row >= 0) & (row < self.shape[0]) & (col >= 0) & (col < self.shape[1])
        out = np.full(row.shape, fill, dtype=float)
        out[ok] = self.values[row[ok], col[ok]]
        return out


def read_geotiff(path: Path) -> Raster:
    """Read a single-band north-up GeoTIFF into a :class:`Raster`."""
    with Image.open(path) as im:
        tags = im.tag_v2
        if _TAG_PIXEL_SCALE not in tags or _TAG_TIEPOINT not in tags:
            raise ValueError(f"{path} lacks GeoTIFF georeferencing tags")
        sx, sy, _ = tags[_TAG_PIXEL_SCALE]
        tie = tags[_TAG_TIEPOINT]
        values = np.array(im, dtype=np.float32)
    # tie = (i, j, k, x, y, z) for the raster point (i, j)
    i, j, _, x, y, _ = tie[:6]
    x_origin = float(x - i * sx)
    y_origin = float(y + j * sy)
    return Raster(values=values, x_origin=x_origin, y_origin=y_origin,
                  x_res=float(sx), y_res=float(sy))


def load_hazard_rasters(data_dir: Path = config.DATA_DIR) -> dict[str, Raster]:
    """Load the five proxy rasters keyed by tier name."""
    return {tier: read_geotiff(data_dir / config.RASTER_TEMPLATE.format(tier=tier))
            for tier in config.TIERS}


def _validate(df: pd.DataFrame, required: list[str], name: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{name} is missing required columns: {missing}")


def load_exposure(path: Path = config.EXPOSURE_WITH_HAZARD_FILE) -> pd.DataFrame:
    """Load the synthetic exposure portfolio (with or without hazard columns)."""
    df = pd.read_csv(path)
    _validate(df, REQUIRED_EXPOSURE_COLUMNS, path.name)
    if not df["loc_id"].is_unique:
        raise ValueError("loc_id must be unique")
    return df


def load_hotspots(path: Path = config.HOTSPOTS_FILE) -> pd.DataFrame:
    """Load the 24 geocoded government flood hotspots."""
    df = pd.read_csv(path)
    _validate(df, REQUIRED_HOTSPOT_COLUMNS, path.name)
    return df


def data_quality_report(df: pd.DataFrame) -> pd.DataFrame:
    """Per-column summary: dtype, missing count, unique count, min, max."""
    rows = []
    for col in df.columns:
        s = df[col]
        rows.append({
            "column": col,
            "dtype": str(s.dtype),
            "missing": int(s.isna().sum()),
            "unique": int(s.nunique()),
            "min": s.min() if pd.api.types.is_numeric_dtype(s) else None,
            "max": s.max() if pd.api.types.is_numeric_dtype(s) else None,
        })
    return pd.DataFrame(rows)


def haversine_m(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Great-circle distance in metres between arrays of WGS84 points."""
    lat1, lon1, lat2, lon2 = map(np.radians, (np.asarray(lat1, float), np.asarray(lon1, float),
                                              np.asarray(lat2, float), np.asarray(lon2, float)))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6_371_000.0 * 2 * np.arcsin(np.sqrt(a))


def nearest_point_distance(lat, lon, ref_lat, ref_lon) -> tuple[np.ndarray, np.ndarray]:
    """Distance (m) and index of the nearest reference point for each query point."""
    lat = np.asarray(lat, float)[:, None]
    lon = np.asarray(lon, float)[:, None]
    d = haversine_m(lat, lon, np.asarray(ref_lat, float)[None, :], np.asarray(ref_lon, float)[None, :])
    idx = d.argmin(axis=1)
    return d[np.arange(len(idx)), idx], idx
