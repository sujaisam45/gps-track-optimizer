"""Before/after maps: interactive (Folium HTML) and static (Matplotlib PNG)."""
from __future__ import annotations

import folium
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .pipeline import PipelineResult  # noqa: E402

RED, GREEN, ORANGE = "#d62728", "#2ca02c", "#ff7f0e"


def _segments(df):
    for _, seg in df.groupby(["track", "segment"], sort=True):
        yield seg


def build_folium_map(res: PipelineResult, show_original_points: bool = True) -> folium.Map:
    v, f, ev = res.validated, res.final, res.evaluation
    m = folium.Map(location=[v["lat"].mean(), v["lon"].mean()], zoom_start=18,
                   max_zoom=22, tiles="OpenStreetMap")

    orig = folium.FeatureGroup("Original track (red)")
    for seg in _segments(v):
        folium.PolyLine(seg[["lat", "lon"]].values.tolist(), color=RED, weight=3, opacity=0.6).add_to(orig)
    orig.add_to(m)

    if show_original_points:
        pts = folium.FeatureGroup("Original GPS points", show=True)
        for r in v.itertuples():
            folium.CircleMarker([r.lat, r.lon], radius=1.5, color=RED, fill=True,
                                opacity=0.5, weight=0).add_to(pts)
        pts.add_to(m)

    clean = folium.FeatureGroup("Cleaned track (green)")
    for seg in _segments(f):
        folium.PolyLine(seg[["lat", "lon"]].values.tolist(), color=GREEN, weight=4).add_to(clean)
        for r in seg.itertuples():
            folium.CircleMarker([r.lat, r.lon], radius=3, color=GREEN, fill=True, weight=1).add_to(clean)
    clean.add_to(m)

    stops = folium.FeatureGroup("Stationary periods (orange)")
    for r in res.stationary[res.stationary["is_stop"]].itertuples():
        dur = (r.stop_end - r.stop_start).total_seconds()
        folium.CircleMarker([r.lat, r.lon], radius=9, color=ORANGE, fill=True, fill_opacity=0.6,
                            tooltip=f"Stop: {dur:.0f} s, {r.stop_points} points collapsed to 1").add_to(stops)
    stops.add_to(m)

    folium.Marker(v[["lat", "lon"]].iloc[0].tolist(), tooltip="Start",
                  icon=folium.Icon(color="green", icon="play")).add_to(m)
    folium.Marker(v[["lat", "lon"]].iloc[-1].tolist(), tooltip="End",
                  icon=folium.Icon(color="red", icon="stop")).add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)

    legend = f"""
    <div style="position:fixed;bottom:20px;left:20px;z-index:9999;background:white;
         padding:10px 14px;border-radius:8px;box-shadow:0 1px 6px rgba(0,0,0,.3);
         font:13px/1.5 system-ui,sans-serif;max-width:280px">
      <b>GPS track cleaning</b><br>
      <span style="color:{RED}">&#9644;</span> Original ({ev.raw_points} pts)<br>
      <span style="color:{GREEN}">&#9644;</span> Cleaned ({ev.final_points} pts)<br>
      <span style="color:{ORANGE}">&#9679;</span> Stops ({ev.stops_detected})<br>
      <hr style="margin:6px 0">
      Reduction: <b>{ev.reduction_pct:.1f}%</b><br>
      Max deviation (moving): <b>{ev.max_deviation_m:.2f} m</b><br>
      Mean deviation: {ev.mean_deviation_m:.2f} m<br>
      DP tolerance: {ev.tolerance_m} m
    </div>"""
    m.get_root().html.add_child(folium.Element(legend))
    m.fit_bounds(v[["lat", "lon"]].agg(["min", "max"]).values.tolist())
    return m


def save_static_comparison(res: PipelineResult, path: str, title: str = "") -> None:
    """Side-by-side before/after plot in local metres."""
    v, f, s, ev = res.validated, res.final, res.stationary, res.evaluation
    x0, y0 = v["x"].min(), v["y"].min()
    fig, axes = plt.subplots(1, 2, figsize=(13, 6.2), sharex=True, sharey=True)
    for ax in axes:
        ax.set_aspect("equal")
        ax.grid(alpha=0.25)
        ax.set_xlabel("east (m)")
    axes[0].set_ylabel("north (m)")

    for seg in _segments(v):
        axes[0].plot(seg.x - x0, seg.y - y0, "-", color=RED, lw=1, alpha=0.6)
        axes[0].plot(seg.x - x0, seg.y - y0, ".", color=RED, ms=2.5)
    axes[0].set_title(f"Before: {ev.raw_points} points")

    for seg in _segments(v):
        axes[1].plot(seg.x - x0, seg.y - y0, "-", color=RED, lw=0.8, alpha=0.25)
    for seg in _segments(f):
        axes[1].plot(seg.x - x0, seg.y - y0, "-o", color=GREEN, lw=1.8, ms=4)
    st = s[s["is_stop"]]
    axes[1].scatter(st.x - x0, st.y - y0, s=160, color=ORANGE, alpha=0.7, zorder=5, label="stop")
    axes[1].set_title(f"After: {ev.final_points} points  (-{ev.reduction_pct:.1f}%, "
                      f"max dev {ev.max_deviation_m:.2f} m)")
    if len(st):
        axes[1].legend(loc="best")
    if title:
        fig.suptitle(title, fontsize=13)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
