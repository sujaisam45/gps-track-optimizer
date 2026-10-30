import pytest

from src.pipeline import PipelineConfig, run_pipeline
from src.synthetic import WalkSpec, make_walk


@pytest.mark.parametrize("tol", [0.5, 0.75, 1.0])
def test_rtk_float_pipeline_metrics(tol):
    raw, truth = make_walk(WalkSpec(noise="rtk_float"))
    res = run_pipeline(raw, PipelineConfig(tolerance_m=tol), {(0, 0): truth["xy"]})
    ev = res.evaluation
    assert ev.raw_points > ev.validated_points >= ev.after_stationary_points >= ev.final_points
    # moving-point deviation never exceeds tolerance + small stop-centroid effect
    assert ev.max_deviation_m <= tol + 0.1
    # cleaned route stays close to the TRUE path (synthetic ground truth)
    assert ev.truth_max_error_m < 1.5
    # cleaning should not make the track less faithful to reality on average
    assert ev.truth_mean_error_m <= ev.original_truth_mean_error_m + 0.05
    # cleaned length within 2% of the TRUE route length (noise inflates raw length)
    import numpy as np
    true_len = float(np.hypot(*np.diff(truth["xy"], axis=0).T).sum())
    assert abs(ev.cleaned_length_m - true_len) / true_len < 0.02
    assert ev.original_length_m > true_len  # jitter adds fake distance
    assert ev.cleaned_gpx_bytes < ev.original_gpx_bytes


def test_stationary_step_reduces_points_before_dp():
    raw, truth = make_walk(WalkSpec(noise="rtk_float"))
    res = run_pipeline(raw)
    removed_by_stops = res.evaluation.validated_points - res.evaluation.after_stationary_points
    assert removed_by_stops >= 0.8 * truth["true_stop_seconds"]


def test_report_fields_are_numbers():
    raw, _ = make_walk(WalkSpec(noise="rtk_fix"))
    d = run_pipeline(raw).evaluation.as_dict()
    for k in ("reduction_pct", "max_deviation_m", "mean_deviation_m", "hausdorff_m",
              "processing_time_s", "size_reduction_pct"):
        assert isinstance(d[k], float)
