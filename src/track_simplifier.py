"""Douglas–Peucker simplification on projected (metre) coordinates.

We implement DP ourselves (iteratively, with numpy) instead of calling
`shapely.LineString.simplify` because we need the *indices* of kept points
to carry timestamps, elevation and stop metadata through. A unit test checks
that our result matches Shapely's geometry.

How DP keeps turns: it draws a straight line from the first to the last
point and finds the point furthest from it. If that distance exceeds the
tolerance, that point (a corner) is kept and both halves are processed the
same way. Points on straight stretches are always within tolerance, so they
are dropped; corners are always the furthest points, so they survive.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _perp_dist(px, py, ax, ay, bx, by):
    """Distance from points P to segment AB (not the infinite line)."""
    abx, aby = bx - ax, by - ay
    L2 = abx * abx + aby * aby
    if L2 == 0:
        return np.hypot(px - ax, py - ay)
    t = np.clip(((px - ax) * abx + (py - ay) * aby) / L2, 0, 1)
    return np.hypot(px - (ax + t * abx), py - (ay + t * aby))


def douglas_peucker_indices(x: np.ndarray, y: np.ndarray, tolerance: float,
                            force_keep: np.ndarray | None = None) -> np.ndarray:
    """Indices (sorted, chronological) kept by Douglas–Peucker.

    `force_keep` is a boolean mask of points that must survive (e.g. stops).
    The line is split at those points and each piece is simplified alone,
    which guarantees they are kept while order is preserved.
    """
    n = len(x)
    if n <= 2:
        return np.arange(n)
    anchors = {0, n - 1}
    if force_keep is not None:
        anchors |= set(np.flatnonzero(force_keep).tolist())
    anchors = sorted(anchors)

    keep = np.zeros(n, bool)
    keep[anchors] = True
    stack = list(zip(anchors[:-1], anchors[1:]))
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        d = _perp_dist(x[a + 1:b], y[a + 1:b], x[a], y[a], x[b], y[b])
        k = int(np.argmax(d))
        if d[k] > tolerance:
            m = a + 1 + k
            keep[m] = True
            stack.append((a, m))
            stack.append((m, b))
    return np.flatnonzero(keep)


def simplify_track(df: pd.DataFrame, tolerance_m: float = 0.5,
                   keep_stops: bool = True, projector=None) -> pd.DataFrame:
    """Simplify each GPX segment separately (never across segments)."""
    parts = []
    for _, seg in df.groupby(["track", "segment"], sort=True):
        seg = seg.reset_index(drop=True)
        force = seg["is_stop"].to_numpy(bool) if keep_stops and "is_stop" in seg else None
        idx = douglas_peucker_indices(seg["x"].to_numpy(), seg["y"].to_numpy(),
                                      tolerance_m, force)
        parts.append(seg.iloc[idx])
    res = pd.concat(parts, ignore_index=True) if parts else df.iloc[0:0].copy()
    if projector is not None and len(res):
        res["lat"], res["lon"] = projector.to_latlon(res["x"], res["y"])
    return res
