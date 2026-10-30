import numpy as np
import pandas as pd

from src.gpx_loader import load_gpx, to_gpx
from src.gps_preprocessing import preprocess
from src.synthetic import WalkSpec, make_walk

GPX_TWO_SEGMENTS = """<?xml version="1.0"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
 <trk><trkseg>
  <trkpt lat="49.4429" lon="1.0884"><ele>15</ele><time>2026-10-30T09:00:00Z</time></trkpt>
  <trkpt lat="49.44291" lon="1.08842"><time>2026-10-30T09:00:01Z</time></trkpt>
  <trkpt lat="49.44291" lon="1.08842"><time>2026-10-30T09:00:01Z</time></trkpt>
 </trkseg><trkseg>
  <trkpt lat="49.4430" lon="1.0886"><time>2026-10-30T09:05:00Z</time></trkpt>
  <trkpt lat="49.44302" lon="1.08861"><time>2026-10-30T09:05:01Z</time></trkpt>
 </trkseg></trk>
</gpx>"""


def test_loads_segments_and_columns():
    df = load_gpx(GPX_TWO_SEGMENTS)
    assert list(df.columns) == ["track", "segment", "time", "lat", "lon", "ele", "speed"]
    assert len(df) == 5
    assert sorted(df["segment"].unique()) == [0, 1]
    assert str(df["time"].dt.tz) == "UTC"


def test_preprocess_removes_duplicates_and_computes_speed():
    clean, proj, rep = preprocess(load_gpx(GPX_TWO_SEGMENTS))
    assert rep.duplicates == 1
    assert len(clean) == 4
    assert proj.epsg == 32631  # Rouen -> UTM 31N
    # speed estimated from distance / time, never across segments
    first_of_seg = clean.groupby("segment").head(1)
    assert (first_of_seg["step_m"] == 0).all()
    assert (clean["speed"] >= 0).all()


def test_missing_coords_and_spikes_removed():
    raw, _ = make_walk(WalkSpec(noise="rtk_fix", missing_frac=0.05, n_spikes=3, seed=1))
    clean, _, rep = preprocess(raw)
    assert rep.missing_coords == int(raw["lat"].isna().sum()) > 0
    assert rep.speed_outliers >= 3
    assert clean["speed_est"].max() < 4.0


def test_gpx_roundtrip():
    raw, _ = make_walk(WalkSpec(noise="rtk_fix", missing_frac=0, n_spikes=0))
    back = load_gpx(to_gpx(raw))
    assert len(back) == len(raw)
    assert np.allclose(back["lat"], raw["lat"], atol=1e-7)
