"""Streamlit dashboard:  streamlit run app.py"""
import io

import pandas as pd
import streamlit as st

from src.gpx_loader import load_gpx, to_gpx
from src.map_visualizer import build_folium_map
from src.pipeline import PipelineConfig, run_pipeline
from src.stationary_detector import StationaryConfig
from src.synthetic import WalkSpec, make_walk

st.set_page_config(page_title="GPS Track Optimizer", page_icon="🧭", layout="wide")
st.title("GPS Track Optimizer")
st.caption("Collapse stationary GPS jitter and simplify pedestrian tracks with "
           "Douglas–Peucker, then measure what it cost in accuracy.")

with st.sidebar:
    st.header("1. Input")
    source = st.radio("Track source", ["Upload GPX", "Synthetic demo walk"])
    raw, truth, label = None, None, ""
    if source == "Upload GPX":
        up = st.file_uploader("GPX file", type=["gpx"])
        if up is not None:
            raw = load_gpx(io.StringIO(up.getvalue().decode("utf-8")))
            label = f"REAL track: {up.name}"
    else:
        noise = st.selectbox("Simulated GNSS quality", ["rtk_float", "rtk_fix", "phone"])
        hz = st.select_slider("Sampling rate (Hz)", [1.0, 2.0, 5.0], value=1.0)
        raw, truth = make_walk(WalkSpec(noise=noise, hz=hz))
        label = f"SYNTHETIC walk ({noise}, {hz:g} Hz) — not real data"

    st.header("2. Stop detection")
    radius = st.slider("Stop radius (m)", 0.5, 5.0, 1.5, 0.1,
                       help="All points of a stop must stay within this distance of its centre.")
    min_dur = st.slider("Minimum stop duration (s)", 2.0, 30.0, 5.0, 1.0)
    max_v = st.slider("Max drift speed inside a stop (m/s)", 0.05, 0.6, 0.25, 0.05)

    st.header("3. Simplification")
    tol = st.select_slider("Douglas–Peucker tolerance (m)", [0.25, 0.5, 0.75, 1.0, 2.0, 3.0, 5.0], value=0.5)
    keep_stops = st.checkbox("Always keep stop points", True)

if raw is None:
    st.info("Upload a GPX file or pick the synthetic demo walk in the sidebar.")
    st.stop()

cfg = PipelineConfig(tolerance_m=tol, keep_stops=keep_stops,
                     stationary=StationaryConfig(radius, min_dur, max_v))
res = run_pipeline(raw, cfg, {(0, 0): truth["xy"]} if truth else None)
ev, vr = res.evaluation, res.validation

st.subheader(label)
c = st.columns(5)
c[0].metric("Original points", f"{ev.raw_points:,}")
c[1].metric("Cleaned points", f"{ev.final_points:,}", f"-{ev.reduction_pct:.1f}%", delta_color="inverse")
c[2].metric("Max deviation (moving)", f"{ev.max_deviation_m:.2f} m")
c[3].metric("Stops detected", ev.stops_detected)
c[4].metric("Processing time", f"{ev.processing_time_s * 1000:.0f} ms")

map_html = build_folium_map(res).get_root().render()  # built from numeric coordinates only
if hasattr(st, "iframe"):
    st.iframe(map_html, height=560)
else:  # Streamlit < 1.52
    import streamlit.components.v1 as components
    components.html(map_html, height=560)

left, right = st.columns(2)
with left:
    st.markdown("**Point count at each stage**")
    st.bar_chart(pd.DataFrame({"points": [ev.raw_points, ev.validated_points,
                                          ev.after_stationary_points, ev.final_points]},
                              index=["1 raw", "2 validated", "3 stops collapsed", "4 simplified"]))
with right:
    st.markdown("**Accuracy & size**")
    rows = {
        "Mean deviation, moving points (m)": ev.mean_deviation_m,
        "Hausdorff distance (m)": ev.hausdorff_m,
        "Jitter inside stops, max (m)": ev.stop_jitter_max_m,
        "Original length (m)": ev.original_length_m,
        "Cleaned length (m)": ev.cleaned_length_m,
        "GPX size before (KB)": round(ev.original_gpx_bytes / 1024, 1),
        "GPX size after (KB)": round(ev.cleaned_gpx_bytes / 1024, 1),
    }
    if ev.truth_mean_error_m is not None:
        rows["Mean error vs TRUE path, before (m)"] = ev.original_truth_mean_error_m
        rows["Mean error vs TRUE path, after (m)"] = ev.truth_mean_error_m
    st.dataframe(pd.DataFrame({"value": rows}), width="stretch")

with st.expander("Validation details"):
    st.json(vr.as_dict())

st.markdown("**Downloads**")
d = st.columns(3)
d[0].download_button("Cleaned GPX", to_gpx(res.final), "cleaned.gpx", "application/gpx+xml")
d[1].download_button("Metrics CSV", pd.DataFrame([ev.as_dict()]).to_csv(index=False),
                     "metrics.csv", "text/csv")
d[2].download_button("Interactive map (HTML)", map_html,
                     "map.html", "text/html")
