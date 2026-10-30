import numpy as np
import pandas as pd
from shapely.geometry import LineString

from src.track_simplifier import douglas_peucker_indices, simplify_track


def test_straight_line_collapses_to_endpoints():
    x = np.linspace(0, 100, 101)
    idx = douglas_peucker_indices(x, np.zeros_like(x), 0.5)
    assert idx.tolist() == [0, 100]


def test_right_angle_corner_kept():
    x = np.r_[np.linspace(0, 50, 51), np.full(50, 50.0)]
    y = np.r_[np.zeros(51), np.linspace(1, 50, 50)]
    idx = douglas_peucker_indices(x, y, 0.5)
    assert idx.tolist() == [0, 50, 100]


def test_matches_shapely_geometry():
    rng = np.random.default_rng(3)
    x = np.cumsum(rng.normal(1, 0.5, 300))
    y = np.cumsum(rng.normal(0, 0.8, 300))
    for tol in (0.5, 0.75, 1.0):
        ours = douglas_peucker_indices(x, y, tol)
        shp = LineString(np.c_[x, y]).simplify(tol, preserve_topology=False)
        assert np.allclose(np.c_[x, y][ours], np.asarray(shp.coords))


def test_order_and_forced_points_preserved():
    x = np.linspace(0, 30, 31)
    force = np.zeros(31, bool)
    force[12] = True
    idx = douglas_peucker_indices(x, np.zeros(31), 0.5, force)
    assert idx.tolist() == [0, 12, 30]
    assert (np.diff(idx) > 0).all()


def test_never_simplifies_across_segments():
    df = pd.DataFrame({
        "track": 0, "segment": [0] * 5 + [1] * 5,
        "x": np.r_[np.arange(5.0), np.arange(5.0)], "y": 0.0,
        "is_stop": False,
    })
    out = simplify_track(df, 0.5)
    assert out.groupby("segment").size().tolist() == [2, 2]


def test_deviation_bounded_by_tolerance():
    rng = np.random.default_rng(5)
    x = np.linspace(0, 200, 400)
    y = 3 * np.sin(x / 15) + rng.normal(0, 0.2, 400)
    line = np.c_[x, y]
    for tol in (0.5, 0.75, 1.0):
        idx = douglas_peucker_indices(x, y, tol)
        simp = LineString(line[idx])
        from shapely.geometry import Point
        dmax = max(simp.distance(Point(p)) for p in line)
        assert dmax <= tol + 1e-9
