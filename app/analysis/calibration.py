import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.analysis.gaze_model import GazeModel

GRID_SIDE = 4
GRID_MIN = 0.1
GRID_MAX = 0.9
MIN_USABLE_POINTS = 12
# Held-out calibration error: each target with at least this many frames
# gives up the last quarter of them (at least one) for evaluation.
MIN_FRAMES_TO_HOLD_OUT = 3
HOLD_OUT_FRACTION = 0.25

_STEP = (GRID_MAX - GRID_MIN) / (GRID_SIDE - 1)

# Row-major: index = row * GRID_SIDE + column.
CALIBRATION_POINTS = [
    (GRID_MIN + column * _STEP, GRID_MIN + row * _STEP)
    for row in range(GRID_SIDE)
    for column in range(GRID_SIDE)
]


def target_index(target, tolerance=0.05):
    """Index of the calibration point nearest to `target` (an object with x
    and y), or None if none lies within `tolerance` on both axes."""

    best = min(range(len(CALIBRATION_POINTS)),
               key=lambda i: abs(CALIBRATION_POINTS[i][0] - target.x) + abs(CALIBRATION_POINTS[i][1] - target.y))
    x, y = CALIBRATION_POINTS[best]

    if abs(x - target.x) > tolerance or abs(y - target.y) > tolerance:
        return None

    return best


@dataclass(frozen=True)
class TargetStatus:
    index: int
    state: str
    samples: int


@dataclass(frozen=True)
class CalibrationResult:
    points: list
    outcome: str
    reason: Optional[str]
    model: Optional[GazeModel]
    # Held-out prediction errors (predicted minus target), one (dx, dy) row
    # per held-out frame, viewport-normalized. None when not ready, or when
    # too few targets had frames to spare (see held_out_residuals).
    residuals: Optional[np.ndarray] = None


def held_out_residuals(samples):
    """Errors of a model that did not see the frames it is judged on.

    `samples` maps a target index to its feature vectors in arrival order.
    From every target with at least MIN_FRAMES_TO_HOLD_OUT frames the last
    quarter (at least one frame) is held out as one block; consecutive frames
    are nearly identical, so holding out scattered single frames would leak
    their neighbours into training and flatter the figure. Every target stays
    in training, so no target has to be extrapolated to. A separate model is
    fitted on the remaining frames and predicts the held-out ones. Returns
    None if fewer than MIN_USABLE_POINTS targets could hold frames out."""

    X_train, y_train, X_test, y_test = [], [], [], []

    for index, frames in samples.items():
        target = CALIBRATION_POINTS[index]
        held = max(1, int(len(frames) * HOLD_OUT_FRACTION)) if len(frames) >= MIN_FRAMES_TO_HOLD_OUT else 0
        split = len(frames) - held
        X_train.extend(frames[:split])
        y_train.extend([target] * split)
        X_test.extend(frames[split:])
        y_test.extend([target] * held)

    if len({tuple(target) for target in y_test}) < MIN_USABLE_POINTS:
        return None

    model = GazeModel()
    model.train(np.array(X_train), np.array(y_train))

    return model.predict(np.array(X_test)) - np.array(y_test)


def mean_error_px(residuals, width, height):
    """Mean Euclidean length of `residuals` (viewport-normalized) in CSS px,
    each axis scaled by its own viewport size so a wide window is not
    measured as if it were square."""

    scaled = np.asarray(residuals, dtype=float) * np.array([width, height], dtype=float)

    return float(np.mean(np.linalg.norm(scaled, axis=1)))


class Calibration:
    """Collects tagged frames for one calibration attempt and fits the gaze
    model on every usable frame, each labelled with its target, and reports
    a held-out estimate of its error (held_out_residuals). (Fitting on
    one average per target would teach the model clean inputs, and it would
    then amplify the frame-to-frame jitter of single frames at reading time.)
    A frame with features None (no face) counts for nothing."""

    def __init__(self):

        self.restart()

    def restart(self):
        """Starts a new attempt from empty samples."""

        self._samples = {index: [] for index in range(len(CALIBRATION_POINTS))}

    def progress(self, current_index):
        """Per-target status while the attempt is running: targets before
        `current_index` are ok or skipped, the current one is collecting, the
        rest are pending."""

        statuses = []

        for index, samples in self._samples.items():
            if index < current_index:
                state = "ok" if samples else "skipped"
            elif index == current_index:
                state = "collecting"
            else:
                state = "pending"
            statuses.append(TargetStatus(index, state, len(samples)))

        return statuses

    def add_frame(self, target, features):

        if features is None:
            return

        for index, point in enumerate(CALIBRATION_POINTS):
            if math.isclose(target[0], point[0], abs_tol=1e-6) and math.isclose(target[1], point[1], abs_tol=1e-6):
                self._samples[index].append(features)
                return

    def finish(self):

        points = []
        X = []
        y = []

        for index, samples in self._samples.items():
            if samples:
                X.extend(samples)
                y.extend([CALIBRATION_POINTS[index]] * len(samples))
            points.append(TargetStatus(index, "ok" if samples else "skipped", len(samples)))

        usable = [p.index for p in points if p.state == "ok"]

        if len(usable) < MIN_USABLE_POINTS:
            return CalibrationResult(points, "failed", "too_few_points", None)

        rows = {index // GRID_SIDE for index in usable}
        columns = {index % GRID_SIDE for index in usable}

        if len(rows) < GRID_SIDE or len(columns) < GRID_SIDE:
            return CalibrationResult(points, "failed", "missing_row_or_column", None)

        # The Session's model is fitted on every frame; the held-out model only measures.
        model = GazeModel()
        model.train(np.array(X), np.array(y))

        # The figure is optional: if measuring it fails, the calibration still succeeds without it.
        try:
            residuals = held_out_residuals(self._samples)
        except (ValueError, np.linalg.LinAlgError):
            residuals = None

        return CalibrationResult(points, "ready", None, model, residuals)
