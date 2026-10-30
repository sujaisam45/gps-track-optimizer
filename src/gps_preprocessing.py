"""Validation, metric projection and speed estimation.

All distance work happens in a projected UTM coordinate system (metres).
Latitude/longitude are degrees, so a "0.5 m" tolerance would be meaningless
without this step.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from pyproj import Transformer


def utm_epsg_for(lat: float, lon: float) -> int:
    """EPSG code of the WGS84/UTM zone containing (lat, lon). Rouen -> 32631."""
    zone = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


@dataclass
class Projector:
    """Converts between WGS84 lat/lon and a local UTM grid in metres."""
    epsg: int
    _fwd: Transformer = field(init=False, repr=False)
    _inv: Transformer = field(init=False, repr=False)

    def __post_init__(self):
        self._fwd = Transformer.from_crs(4326, self.epsg, always_xy=True)
        self._inv = Transformer.from_crs(self.epsg, 4326, always_xy=True)

    @classmethod
    def for_points(cls, lat, lon) -> "Projector":
        return cls(utm_epsg_for(float(np.nanmedian(lat)), float(np.nanmedian(lon))))

    def to_xy(self, lat, lon):
        x, y = self._fwd.transform(np.asarray(lon, float), np.asarray(lat, float))
        return np.asarray(x), np.asarray(y)

    def to_latlon(self, x, y):
        lon, lat = self._inv.transform(np.asarray(x, float), np.asarray(y, float))
        return np.asarray(lat), np.asarray(lon)


@dataclass
class ValidationReport:
    input_points: int = 0
    missing_coords: int = 0
    invalid_coords: int = 0
    missing_time: int = 0
    duplicates: int = 0
    speed_outliers: int = 0
    output_points: int = 0

    def as_dict(self):
        return self.__dict__.copy()


def add_motion_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add step distance (m), time step (s) and speed (m/s) per segment.

    Speed comes from the GPX file when present, otherwise from distance/time.
    """
    df = df.copy()
    key = ["track", "segment"]
    dx = df.groupby(key)["x"].diff()
    dy = df.groupby(key)["y"].diff()
    df["step_m"] = np.hypot(dx, dy).fillna(0.0)
    dt = df.groupby(key)["time"].diff().dt.total_seconds()
    df["dt_s"] = dt.fillna(0.0)
    est = df["step_m"] / dt.where(dt > 0)
    df["speed_est"] = est
    if "speed" not in df:
        df["speed"] = np.nan
    df["speed"] = df["speed"].fillna(df["speed_est"]).fillna(0.0)
    return df


def preprocess(df: pd.DataFrame, max_speed_mps: float = 4.0,
               projector: Projector | None = None):
    """Validate a raw GPX DataFrame and project it to metres.

    Steps:
      1. drop rows with missing / impossible coordinates
      2. drop rows with missing timestamps (needed for speed and ordering)
      3. sort by time inside each segment and drop exact duplicates
      4. project to UTM (x, y in metres)
      5. remove single-point jumps faster than `max_speed_mps`
         (4 m/s ~ 14 km/h, generous for a pedestrian)

    Returns (clean_df, projector, ValidationReport).
    """
    rep = ValidationReport(input_points=len(df))
    df = df.copy()

    miss = df["lat"].isna() | df["lon"].isna()
    rep.missing_coords = int(miss.sum())
    df = df[~miss]

    bad = (df["lat"].abs() > 90) | (df["lon"].abs() > 180) | ((df["lat"] == 0) & (df["lon"] == 0))
    rep.invalid_coords = int(bad.sum())
    df = df[~bad]

    no_t = df["time"].isna()
    rep.missing_time = int(no_t.sum())
    df = df[~no_t]

    df = df.sort_values(["track", "segment", "time"], kind="stable")
    dup = df.duplicated(subset=["track", "segment", "time"], keep="first") | \
        df.duplicated(subset=["track", "segment", "lat", "lon", "time"], keep="first")
    rep.duplicates = int(dup.sum())
    df = df[~dup].reset_index(drop=True)

    if projector is None:
        projector = Projector.for_points(df["lat"], df["lon"])
    df["x"], df["y"] = projector.to_xy(df["lat"], df["lon"])

    # Outlier removal: a spike is a point that is reached AND left at an
    # impossible speed. Iterate because removing one spike changes neighbours.
    removed = 0
    for _ in range(5):
        df = add_motion_columns(df)
        nxt_speed = df.groupby(["track", "segment"])["speed_est"].shift(-1)
        spike = (df["speed_est"] > max_speed_mps) & (nxt_speed > max_speed_mps)
        if not spike.any():
            break
        removed += int(spike.sum())
        df = df[~spike].reset_index(drop=True)
    rep.speed_outliers = removed
    df = add_motion_columns(df)
    rep.output_points = len(df)
    return df, projector, rep
