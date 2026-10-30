"""Command-line entry point.

    python main.py path/to/walk.gpx --tolerance 0.5
    python main.py --synthetic            # runs the synthetic benchmark

Outputs go to ./outputs/: cleaned GPX, metrics CSV, interactive map HTML,
static before/after PNG and a Markdown report.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.gpx_loader import load_gpx, to_gpx
from src.map_visualizer import build_folium_map, save_static_comparison
from src.pipeline import PipelineConfig, run_pipeline
from src.stationary_detector import StationaryConfig
from src.synthetic import WalkSpec, make_walk

OUT = Path("outputs")


def save_outputs(res, name: str, title: str):
    OUT.mkdir(exist_ok=True)
    (OUT / f"{name}_cleaned.gpx").write_text(to_gpx(res.final, name))
    pd.DataFrame([res.evaluation.as_dict()]).to_csv(OUT / f"{name}_metrics.csv", index=False)
    build_folium_map(res).save(str(OUT / f"{name}_map.html"))
    save_static_comparison(res, str(OUT / f"{name}_before_after.png"), title)


def run_file(path: str, cfg: PipelineConfig):
    raw = load_gpx(path)
    res = run_pipeline(raw, cfg)
    name = Path(path).stem
    save_outputs(res, name, f"{name} (from GPX file)")
    print(json.dumps({"validation": res.validation.as_dict(),
                      "evaluation": res.evaluation.as_dict()}, indent=2, default=str))


def run_synthetic_benchmark(cfg_stat: StationaryConfig):
    """Same route, three GNSS quality levels, several tolerances."""
    rows = []
    plan = [("rtk_fix", [0.25, 0.5, 1.0]), ("rtk_float", [0.5, 0.75, 1.0]),
            ("phone", [1.0, 3.0, 5.0])]
    for noise, tols in plan:
        raw, truth = make_walk(WalkSpec(noise=noise))
        tkey = {(0, 0): truth["xy"]}
        for tol in tols:
            res = run_pipeline(raw, PipelineConfig(tolerance_m=tol, stationary=cfg_stat), tkey)
            d = res.evaluation.as_dict()
            d.update(noise=noise, true_stops=truth["true_stop_count"])
            rows.append(d)
            if tol == tols[1]:
                save_outputs(res, f"synthetic_{noise}",
                             f"SYNTHETIC walk, {noise} noise, tolerance {tol} m")
    df = pd.DataFrame(rows)
    OUT.mkdir(exist_ok=True)
    df.to_csv(OUT / "synthetic_benchmark.csv", index=False)
    cols = ["noise", "tolerance_m", "raw_points", "after_stationary_points", "final_points",
            "reduction_pct", "stops_detected", "true_stops", "max_deviation_m",
            "mean_deviation_m", "truth_mean_error_m", "truth_max_error_m",
            "original_truth_mean_error_m", "size_reduction_pct", "processing_time_s"]
    print(df[cols].to_string(index=False))
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gpx", nargs="?", help="GPX file to clean")
    ap.add_argument("--synthetic", action="store_true", help="run the synthetic benchmark")
    ap.add_argument("--tolerance", type=float, default=0.5, help="Douglas–Peucker tolerance (m)")
    ap.add_argument("--stop-radius", type=float, default=1.5)
    ap.add_argument("--stop-min-duration", type=float, default=5.0)
    ap.add_argument("--stop-max-speed", type=float, default=0.25)
    a = ap.parse_args()
    sc = StationaryConfig(a.stop_radius, a.stop_min_duration, a.stop_max_speed)
    if a.synthetic or not a.gpx:
        run_synthetic_benchmark(sc)
    if a.gpx:
        run_file(a.gpx, PipelineConfig(tolerance_m=a.tolerance, stationary=sc))
