"""Measure what cleaning cost in accuracy, not just what it saved.

Deviation metric (documented, all in metres, per segment then aggregated):

* **point-to-polyline deviation**: for every *moving* point of the validated
  original track, the distance to the nearest place on the cleaned polyline.
  Max and mean are reported. Points inside a detected stop are measured
  separately (`stop_jitter_*`): their distance is GPS jitter around the stop
  centroid, not lost route geometry.
* **Hausdorff distance** (Shapely) between original and cleaned polylines:
  the worst mismatch in either direction.
* If a ground-truth path is supplied (synthetic data only), the same
  point-to-polyline metric is computed between ground truth and cleaned
  track. This answers "is the cleaned route close to where the person
  really walked?", which is the question that matters for navigation.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point

from .gpx_loader import gpx_size_bytes


def _line(seg: pd.DataFrame) -> LineString | None:
    xy = seg[["x", "y"]].to_numpy()
    if len(xy) < 2:
        return None
    return LineString(xy)


def _dist_to_line(xy: np.ndarray, line: LineString) -> np.ndarray:
    return np.array([line.distance(Point(p)) for p in xy])


def _length(df: pd.DataFrame) -> float:
    total = 0.0
    for _, seg in df.groupby(["track", "segment"]):
        d = np.hypot(np.diff(seg["x"].to_numpy()), np.diff(seg["y"].to_numpy()))
        total += float(d.sum())
    return total


@dataclass
class EvaluationResult:
    raw_points: int
    validated_points: int
    after_stationary_points: int
    final_points: int
    reduction_pct: float
    stops_detected: int
    points_in_stops: int
    original_length_m: float
    cleaned_length_m: float
    max_deviation_m: float
    mean_deviation_m: float
    hausdorff_m: float
    stop_jitter_max_m: float
    original_gpx_bytes: int
    cleaned_gpx_bytes: int
    size_reduction_pct: float
    processing_time_s: float
    tolerance_m: float
    truth_max_error_m: float | None = None
    truth_mean_error_m: float | None = None
    original_truth_mean_error_m: float | None = None

    def as_dict(self):
        return asdict(self)


def evaluate(raw_df: pd.DataFrame, validated: pd.DataFrame, stationary: pd.DataFrame,
             final: pd.DataFrame, processing_time_s: float, tolerance_m: float,
             truth_xy: dict | None = None) -> EvaluationResult:
    """`truth_xy` (optional): {(track, segment): (N,2) array of true positions}."""
    stop_rows = stationary[stationary.get("is_stop", False) == True]  # noqa: E712

    moving_dev, stop_dev, haus = [], [], []
    truth_err, orig_truth_err = [], []
    for key, oseg in validated.groupby(["track", "segment"]):
        fseg = final[(final["track"] == key[0]) & (final["segment"] == key[1])]
        line = _line(fseg)
        if line is None:
            continue
        # Mark original points that belong to a stop window.
        in_stop = np.zeros(len(oseg), bool)
        ss = stop_rows[(stop_rows["track"] == key[0]) & (stop_rows["segment"] == key[1])]
        ot = oseg["time"]
        for s, e in zip(ss["stop_start"], ss["stop_end"]):
            in_stop |= ((ot >= s) & (ot <= e)).to_numpy()
        d = _dist_to_line(oseg[["x", "y"]].to_numpy(), line)
        moving_dev.append(d[~in_stop])
        stop_dev.append(d[in_stop])
        oline = _line(oseg)
        if oline is not None:
            haus.append(oline.hausdorff_distance(line))
        if truth_xy is not None and key in truth_xy:
            tl = LineString(truth_xy[key])
            truth_err.append(_dist_to_line(fseg[["x", "y"]].to_numpy(), tl))
            # how far the cleaned line strays from the truth, sampled densely
            dense = np.array([line.interpolate(s).coords[0]
                              for s in np.arange(0, line.length, 0.5)])
            if len(dense):
                truth_err.append(_dist_to_line(dense, tl))
            orig_truth_err.append(_dist_to_line(oseg[["x", "y"]].to_numpy(), tl))

    cat = lambda xs: np.concatenate(xs) if xs and sum(len(a) for a in xs) else np.array([0.0])
    mdev, sdev = cat(moving_dev), cat(stop_dev)
    ob, cb = gpx_size_bytes(raw_df.dropna(subset=["lat", "lon"])), gpx_size_bytes(final)

    res = EvaluationResult(
        raw_points=len(raw_df),
        validated_points=len(validated),
        after_stationary_points=len(stationary),
        final_points=len(final),
        reduction_pct=round(100 * (1 - len(final) / max(len(raw_df), 1)), 2),
        stops_detected=int(len(stop_rows)),
        points_in_stops=int(stop_rows["stop_points"].sum()) if len(stop_rows) else 0,
        original_length_m=round(_length(validated), 2),
        cleaned_length_m=round(_length(final), 2),
        max_deviation_m=round(float(mdev.max()), 3),
        mean_deviation_m=round(float(mdev.mean()), 3),
        hausdorff_m=round(float(max(haus)) if haus else 0.0, 3),
        stop_jitter_max_m=round(float(sdev.max()), 3),
        original_gpx_bytes=ob,
        cleaned_gpx_bytes=cb,
        size_reduction_pct=round(100 * (1 - cb / max(ob, 1)), 2),
        processing_time_s=round(processing_time_s, 4),
        tolerance_m=tolerance_m,
    )
    if truth_err:
        te, ote = cat(truth_err), cat(orig_truth_err)
        res.truth_max_error_m = round(float(te.max()), 3)
        res.truth_mean_error_m = round(float(te.mean()), 3)
        res.original_truth_mean_error_m = round(float(ote.mean()), 3)
    return res
