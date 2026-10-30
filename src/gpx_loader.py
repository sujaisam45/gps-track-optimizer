"""Read and write GPX files as pandas DataFrames.

Each row is one GPS fix with columns:
    track, segment, time, lat, lon, ele, speed
`speed` is only filled when the GPX file provides it (m/s); otherwise NaN.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import IO, Union

import gpxpy
import gpxpy.gpx
import numpy as np
import pandas as pd

GpxSource = Union[str, Path, IO[str], IO[bytes]]

COLUMNS = ["track", "segment", "time", "lat", "lon", "ele", "speed"]


def _read_text(source: GpxSource) -> str:
    if isinstance(source, str) and source.lstrip().startswith("<"):
        return source  # raw GPX XML string
    if isinstance(source, (str, Path)):
        return Path(source).read_text(encoding="utf-8")
    data = source.read()
    return data.decode("utf-8") if isinstance(data, bytes) else data


def load_gpx(source: GpxSource) -> pd.DataFrame:
    """Load every track/segment of a GPX file into one DataFrame."""
    gpx = gpxpy.parse(_read_text(source))
    rows = []
    for t_idx, track in enumerate(gpx.tracks):
        for s_idx, seg in enumerate(track.segments):
            for p in seg.points:
                speed = p.speed
                if speed is None:
                    # Some apps store speed in an extension element.
                    for ext in p.extensions or []:
                        for el in ext.iter():
                            if el.tag.lower().endswith("speed") and el.text:
                                try:
                                    speed = float(el.text)
                                except ValueError:
                                    pass
                rows.append((t_idx, s_idx, p.time, p.latitude, p.longitude,
                             p.elevation, speed))
    # Treat standalone route points as one extra track if no tracks exist.
    if not rows:
        for r_idx, route in enumerate(gpx.routes):
            for p in route.points:
                rows.append((r_idx, 0, p.time, p.latitude, p.longitude, p.elevation, None))

    df = pd.DataFrame(rows, columns=COLUMNS)
    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    for col in ("lat", "lon", "ele", "speed"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    return df


def to_gpx(df: pd.DataFrame, name: str = "cleaned track") -> str:
    """Serialise a DataFrame (same columns as load_gpx) back to GPX XML."""
    gpx = gpxpy.gpx.GPX()
    for t_id, tdf in df.groupby("track", sort=True):
        track = gpxpy.gpx.GPXTrack(name=f"{name} {t_id}" if df["track"].nunique() > 1 else name)
        gpx.tracks.append(track)
        for _, sdf in tdf.groupby("segment", sort=True):
            seg = gpxpy.gpx.GPXTrackSegment()
            track.segments.append(seg)
            for row in sdf.itertuples(index=False):
                t = None if pd.isna(row.time) else row.time.to_pydatetime()
                ele = None if pd.isna(row.ele) else float(row.ele)
                seg.points.append(gpxpy.gpx.GPXTrackPoint(
                    float(row.lat), float(row.lon), elevation=ele, time=t))
    return gpx.to_xml()


def gpx_size_bytes(df: pd.DataFrame) -> int:
    """Size of the GPX file this DataFrame would produce (UTF-8 bytes)."""
    return len(to_gpx(df).encode("utf-8"))
