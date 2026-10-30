"""End-to-end cleaning pipeline: validate -> collapse stops -> Douglas–Peucker."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import pandas as pd

from .accuracy_evaluator import EvaluationResult, evaluate
from .gps_preprocessing import Projector, ValidationReport, preprocess
from .stationary_detector import StationaryConfig, collapse_stationary
from .track_simplifier import simplify_track


@dataclass
class PipelineConfig:
    tolerance_m: float = 0.5
    max_speed_mps: float = 4.0
    keep_stops: bool = True
    stationary: StationaryConfig = field(default_factory=StationaryConfig)


@dataclass
class PipelineResult:
    raw: pd.DataFrame
    validated: pd.DataFrame
    stationary: pd.DataFrame
    final: pd.DataFrame
    projector: Projector
    validation: ValidationReport
    evaluation: EvaluationResult


def run_pipeline(raw: pd.DataFrame, cfg: PipelineConfig | None = None,
                 truth_xy: dict | None = None) -> PipelineResult:
    cfg = cfg or PipelineConfig()
    t0 = time.perf_counter()
    validated, proj, vrep = preprocess(raw, max_speed_mps=cfg.max_speed_mps)
    stat = collapse_stationary(validated, cfg.stationary, projector=proj)
    final = simplify_track(stat, cfg.tolerance_m, keep_stops=cfg.keep_stops, projector=proj)
    elapsed = time.perf_counter() - t0
    ev = evaluate(raw, validated, stat, final, elapsed, cfg.tolerance_m, truth_xy)
    return PipelineResult(raw, validated, stat, final, proj, vrep, ev)
