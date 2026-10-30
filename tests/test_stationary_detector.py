import numpy as np
import pytest

from src.gps_preprocessing import preprocess
from src.stationary_detector import StationaryConfig, collapse_stationary, find_stationary_groups
from src.synthetic import WalkSpec, make_walk


def test_pure_jitter_is_one_stop():
    rng = np.random.default_rng(0)
    n = 30
    x, y = rng.normal(0, 0.3, n), rng.normal(0, 0.3, n)
    t = np.arange(n, dtype=float)
    groups = find_stationary_groups(x, y, t, StationaryConfig())
    assert groups == [(0, n - 1)]


def test_slow_walking_is_not_a_stop():
    """0.45 m/s for 60 s: small steps, but steady progress -> keep it."""
    t = np.arange(60, dtype=float)
    x, y = 0.45 * t, np.zeros(60)
    assert find_stationary_groups(x, y, t, StationaryConfig()) == []


def test_very_slow_drift_rejected_by_speed_test():
    """0.3 m/s fits in a 1.5 m radius for ~10 s, but drift speed > 0.25 m/s."""
    t = np.arange(8, dtype=float)
    x, y = 0.3 * t, np.zeros(8)
    assert find_stationary_groups(x, y, t, StationaryConfig(min_duration_s=5)) == []


def test_short_pause_kept():
    t = np.arange(3, dtype=float)
    assert find_stationary_groups(np.zeros(3), np.zeros(3), t, StationaryConfig()) == []


@pytest.mark.parametrize("noise", ["rtk_fix", "rtk_float"])
@pytest.mark.parametrize("hz", [1.0, 5.0])
def test_detects_every_synthetic_stop_with_rtk(noise, hz):
    raw, truth = make_walk(WalkSpec(noise=noise, hz=hz))
    clean, proj, _ = preprocess(raw)
    out = collapse_stationary(clean, StationaryConfig(), proj)
    stops = out[out["is_stop"]]
    assert len(stops) == truth["true_stop_count"]
    # each representative point lands near a real corner
    for r in stops.itertuples():
        d = np.hypot(truth["xy"][:, 0] - r.x, truth["xy"][:, 1] - r.y).min()
        assert d < 1.0
    # metadata preserved
    assert (stops["stop_end"] > stops["stop_start"]).all()
    assert stops["stop_points"].sum() > 0.8 * truth["true_stop_seconds"] * hz


def test_phone_noise_limitation_documented():
    """With ~3 m phone noise the 1.5 m radius cannot see most stops.
    This test pins down a known limitation rather than hiding it."""
    raw, truth = make_walk(WalkSpec(noise="phone"))
    clean, proj, _ = preprocess(raw)
    out = collapse_stationary(clean, StationaryConfig(), proj)
    assert out["is_stop"].sum() < truth["true_stop_count"]
