"""Export the synthetic demo walks (same data as the Python benchmark) to JSON
for the web page, plus Python reference metrics used to cross-check the JS port."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from src.synthetic import WalkSpec, make_walk
from src.pipeline import PipelineConfig, run_pipeline
from src.stationary_detector import StationaryConfig

PRESET = {"rtk_fix": (0.5, 1.5), "rtk_float": (0.75, 1.5), "phone": (3.0, 4.0)}
samples, ref = {}, {}
for noise, (tol, radius) in PRESET.items():
    raw, truth = make_walk(WalkSpec(noise=noise))
    t0 = raw["time"].iloc[0]
    pts = [[round((r.time - t0).total_seconds(), 3),
            None if np.isnan(r.lat) else round(r.lat, 8),
            None if np.isnan(r.lon) else round(r.lon, 8),
            round(r.ele, 2)] for r in raw.itertuples()]
    lat, lon = truth["proj"].to_latlon(truth["xy"][:, 0], truth["xy"][:, 1])
    samples[noise] = {"start": t0.isoformat(), "points": pts,
                      "truth": [[round(a, 8), round(b, 8)] for a, b in zip(lat, lon)]}
    # Reference metrics are computed on the ROUNDED data the web page uses,
    # so Python and JS see byte-identical inputs.
    import pandas as pd
    raw = pd.DataFrame({"track": 0, "segment": 0,
        "time": [t0 + pd.to_timedelta(p[0], unit="s") for p in pts],
        "lat": [np.nan if p[1] is None else p[1] for p in pts],
        "lon": [np.nan if p[2] is None else p[2] for p in pts],
        "ele": [p[3] for p in pts], "speed": np.nan})
    truth_xy = np.c_[truth["proj"].to_xy(lat.round(8), lon.round(8))]
    for t in (0.5, 0.75, 1.0, 3.0):
        for rad in (1.5, 4.0):
            cfg = PipelineConfig(tolerance_m=t, stationary=StationaryConfig(radius_m=rad))
            ev = run_pipeline(raw, cfg, {(0, 0): truth_xy}).evaluation
            ref[f"{noise}|{t}|{rad}"] = ev.as_dict()
out = Path(__file__).parent
(out / "src" / "samples.json").write_text(json.dumps(samples, separators=(",", ":")))
(out / "python_reference.json").write_text(json.dumps(ref, indent=1))
print({k: len(v["points"]) for k, v in samples.items()}, (out / "src" / "samples.json").stat().st_size)
