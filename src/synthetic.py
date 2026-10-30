"""Synthetic pedestrian walks with known ground truth (for testing only).

A walk follows a polyline of street corners near Place du Vieux-Marché,
Rouen. The walker moves at normal speed, slows down on one stretch (careful
walking), and stops at "crossings" for 20-45 s. Positions are sampled at a
chosen rate and corrupted with noise that is *correlated in time* (AR(1)),
which is how real GNSS error behaves: it drifts, it doesn't jump randomly.

Noise profiles (1-sigma horizontal, typical published orders of magnitude):
    rtk_fix    ~ 0.02 m   RTK fixed solution
    rtk_float  ~ 0.30 m   RTK float solution
    phone      ~ 3.0  m   consumer smartphone GNSS in a city

Results computed from this data are SYNTHETIC and must be labelled so.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .gps_preprocessing import Projector

ROUEN_EPSG = 32631
ORIGIN_LATLON = (49.44290, 1.08840)  # Place du Vieux-Marché area

NOISE_SIGMA = {"rtk_fix": 0.02, "rtk_float": 0.30, "phone": 3.0}

# Street corners (metres east, north of origin). Mixture of long straights,
# right angles and one shallow bend.
DEFAULT_ROUTE = np.array([
    [0, 0], [85, 0], [85, 60], [140, 95], [140, 170], [60, 170], [60, 230], [-20, 230],
], float)


@dataclass
class WalkSpec:
    route: np.ndarray = None
    speed_mps: float = 1.2
    slow_speed_mps: float = 0.45
    slow_leg: int = 4               # index of the leg walked slowly
    stops: tuple = ((1, 30.0), (3, 45.0), (5, 20.0))  # (corner index, seconds)
    hz: float = 1.0
    noise: str = "rtk_float"
    noise_corr_s: float = 10.0      # AR(1) correlation time
    missing_frac: float = 0.01
    n_spikes: int = 2
    seed: int = 7


def _truth_path(spec: WalkSpec):
    """Return true (t, x, y, is_stopped) sampled at spec.hz."""
    route = spec.route if spec.route is not None else DEFAULT_ROUTE
    dt = 1.0 / spec.hz
    stop_at = dict(spec.stops)
    ts, xs, ys, st = [], [], [], []
    t = 0.0
    for leg in range(len(route) - 1):
        a, b = route[leg], route[leg + 1]
        L = float(np.hypot(*(b - a)))
        v = spec.slow_speed_mps if leg == spec.slow_leg else spec.speed_mps
        n = max(int(L / v / dt), 1)
        for k in range(n):
            p = a + (b - a) * (k / n)
            ts.append(t); xs.append(p[0]); ys.append(p[1]); st.append(False)
            t += dt
        if leg + 1 in stop_at:
            for _ in range(int(stop_at[leg + 1] / dt)):
                ts.append(t); xs.append(b[0]); ys.append(b[1]); st.append(True)
                t += dt
    ts.append(t); xs.append(route[-1][0]); ys.append(route[-1][1]); st.append(False)
    return np.array(ts), np.array(xs), np.array(ys), np.array(st), route


def make_walk(spec: WalkSpec | None = None):
    """Return (raw_df, truth) where truth = {'xy': (N,2) route corners in UTM,
    'proj': Projector}. raw_df has the same columns as gpx_loader.load_gpx."""
    spec = spec or WalkSpec()
    rng = np.random.default_rng(spec.seed)
    t, x, y, stopped, route = _truth_path(spec)

    sigma = NOISE_SIGMA[spec.noise]
    phi = np.exp(-(1 / spec.hz) / spec.noise_corr_s)
    innov = sigma * np.sqrt(1 - phi ** 2)
    nx, ny = np.zeros(len(t)), np.zeros(len(t))
    nx[0], ny[0] = rng.normal(0, sigma, 2)
    for i in range(1, len(t)):
        nx[i] = phi * nx[i - 1] + rng.normal(0, innov)
        ny[i] = phi * ny[i - 1] + rng.normal(0, innov)
    # a little white measurement noise on top
    nx += rng.normal(0, sigma * 0.2, len(t))
    ny += rng.normal(0, sigma * 0.2, len(t))

    proj = Projector(ROUEN_EPSG)
    ox, oy = proj.to_xy([ORIGIN_LATLON[0]], [ORIGIN_LATLON[1]])
    X, Y = x + nx + ox[0], y + ny + oy[0]

    # spikes (multipath jumps of 25-40 m on a single fix)
    for i in rng.choice(np.arange(5, len(t) - 5), spec.n_spikes, replace=False):
        ang = rng.uniform(0, 2 * np.pi)
        X[i] += 30 * np.cos(ang)
        Y[i] += 30 * np.sin(ang)

    lat, lon = proj.to_latlon(X, Y)
    times = pd.Timestamp("2026-10-30T09:00:00Z") + pd.to_timedelta(t, unit="s")
    df = pd.DataFrame({"track": 0, "segment": 0, "time": times, "lat": lat, "lon": lon,
                       "ele": 15.0 + rng.normal(0, 0.3, len(t)), "speed": np.nan})
    miss = rng.random(len(t)) < spec.missing_frac
    miss[[0, -1]] = False
    df.loc[miss, ["lat", "lon"]] = np.nan

    truth_xy = route + np.array([ox[0], oy[0]])
    return df, {"xy": truth_xy, "proj": proj, "true_stop_count": len(spec.stops),
                "true_stop_seconds": float(sum(s for _, s in spec.stops))}
