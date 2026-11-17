"""Replays a recording through the service's own pipeline: features -> model -> smoothing -> fixation -> Cell.

The baseline config reproduces what `Session` does today. Every other option is a candidate improvement
(docs/gaze-benchmark.md) and is off in the baseline. The classes are the service's, so a gain here is a gain
there, apart from the candidate options themselves.
"""

import time
from dataclasses import dataclass, field, replace

import numpy as np

from app.analysis.calibration import Calibration
from app.analysis.cell_layout import cell_at
from app.analysis.eye_features import (
    FEATURE_SIZE, FEATURE_SIZE_V2, MODEL_FEATURE_GROUPS, extract_features, model_columns,
)
from app.analysis.fixation_detector import FixationDetector
from app.analysis.gaze_model import GazeModel
from app.analysis.gaze_smoother import GazeSmoother
from benchmark.metrics import error_cm, error_degrees, error_fraction

# Columns of the full feature vector that hold the two eye aspect ratios (see FEATURE_GROUPS).
EAR_COLUMNS = (4, 5)

# Only frames whose true gaze point has been still this long are scored: right after a saccade the smoothed
# estimate lags the eye by design, and that is not a model error.
SETTLE_SECONDS = 0.3


@dataclass(frozen=True)
class PipelineConfig:
    name: str = "baseline"
    use_eye_centres: bool = False                # protocol version 2 features
    groups: tuple = MODEL_FEATURE_GROUPS         # feature groups the model is fitted on
    alpha: float = 1.0                           # Ridge / kernel ridge strength
    degree: int = 1                              # >1: polynomial terms
    regressor: str = "ridge"                     # "ridge" or "kernel"
    clip: bool = False                           # clip predictions to the screen
    smoothing_alpha: float = 0.25                # EMA
    max_dispersion: float = 0.03                 # fixation
    min_duration: float = 0.15                   # fixation, seconds
    out_of_range: object = None                  # None, "drop" or "clamp" frames with some |z| > z_limit
    z_limit: float = 3.0
    reject_blinks: bool = False                  # drop frames with a low eye aspect ratio
    blink_ratio: float = 0.7                     # low = below this share of the calibration median

    def with_(self, **changes):
        return replace(self, **changes)


@dataclass
class ReplayResult:
    learner: str
    conditions: dict
    calibrated: bool
    failure_reason: object = None
    errors_fraction: list = field(default_factory=list)   # smoothed estimate vs truth, settled frames only
    errors_cm: list = field(default_factory=list)
    errors_degrees: list = field(default_factory=list)
    raw_errors_fraction: list = field(default_factory=list)  # before smoothing, same frames
    cell_hits: list = field(default_factory=list)         # per fixation frame: predicted Cell == true Cell
    frame_ms: list = field(default_factory=list)          # time to process one reading frame
    frames: int = 0
    no_face: int = 0
    rejected: int = 0                                     # blinks and out-of-range frames dropped


def _row(features, columns):

    return np.asarray(features, dtype=float)[columns].reshape(1, -1)


def _ear(features):

    return float(np.mean([features[c] for c in EAR_COLUMNS]))


def _clamp(model, row, limit):
    """`row` pulled back inside +-`limit` calibration deviations of the calibration mean."""

    scaler = model.model.named_steps["scaler"]
    z = np.clip((row - scaler.mean_) / scaler.scale_, -limit, limit)

    return z * scaler.scale_ + scaler.mean_


def replay(recording, config=PipelineConfig(), clock=time.perf_counter):
    """Calibrates on the recording's calibration frames, then runs its reading frames. Returns a ReplayResult."""

    result = ReplayResult(recording.learner, dict(recording.conditions), calibrated=False)
    size = FEATURE_SIZE_V2 if config.use_eye_centres else FEATURE_SIZE
    columns = model_columns(size, config.groups)

    def factory():
        return GazeModel(alpha=config.alpha, degree=config.degree, regressor=config.regressor, clip=config.clip)

    # --- calibration ---
    calibration = Calibration(model_factory=factory)
    full = [(target, extract_features(frame, use_eye_centres=config.use_eye_centres))
            for target, frame in recording.calibration]
    ears = [_ear(f) for _, f in full if f is not None]
    ear_floor = config.blink_ratio * float(np.median(ears)) if ears else 0.0

    for target, features in full:
        if features is None:
            continue
        if config.reject_blinks and _ear(features) < ear_floor:
            continue
        calibration.add_frame(target, features[columns])

    outcome = calibration.finish()

    if outcome.outcome != "ready":
        result.failure_reason = outcome.reason
        return result

    result.calibrated = True
    model = outcome.model

    # --- reading ---
    smoother = GazeSmoother(config.smoothing_alpha)
    detector = FixationDetector(config.max_dispersion, config.min_duration)
    last_truth = None
    truth_since = None        # browser time the true point last changed (set on the next frame with a face)

    for truth, frame in recording.reading:
        result.frames += 1
        t = None if frame is None else frame.t / 1000.0

        if truth != last_truth:
            last_truth, truth_since = truth, None

        started = clock()
        features = extract_features(frame, use_eye_centres=config.use_eye_centres)

        if features is None:
            result.no_face += 1
            continue

        if truth_since is None:
            truth_since = t

        if config.reject_blinks and _ear(features) < ear_floor:
            result.rejected += 1
            continue

        row = _row(features, columns)

        if config.out_of_range:
            z = model.standardize(row)[0]
            if np.abs(z).max() > config.z_limit:
                if config.out_of_range == "drop":
                    result.rejected += 1
                    continue
                row = _clamp(model, row, config.z_limit)

        raw = model.predict(row)[0]
        gaze = smoother.update(raw)
        fixation = detector.update(gaze, t)
        elapsed_ms = (clock() - started) * 1000.0
        result.frame_ms.append(elapsed_ms)

        if t - truth_since >= SETTLE_SECONDS:
            result.errors_fraction.append(float(error_fraction(gaze, truth)))
            result.errors_cm.append(float(error_cm(gaze, truth, recording.geometry)))
            result.errors_degrees.append(float(error_degrees(gaze, truth, recording.geometry)))
            result.raw_errors_fraction.append(float(error_fraction(raw, truth)))

            if fixation is not None:
                x, y = fixation["position"]
                predicted = cell_at(recording.cells, float(x), float(y))
                actual = cell_at(recording.cells, truth[0], truth[1])
                result.cell_hits.append(predicted is not None and predicted == actual)

    return result
