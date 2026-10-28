import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from gaze_model import GazeModel

GRID_SIDE = 4
GRID_MIN = 0.1
GRID_MAX = 0.9
MIN_USABLE_POINTS = 12

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


class Calibration:
    """Collects tagged frames for one calibration attempt and fits the gaze
    model from the mean features per target. A frame with features None (no
    face) counts for nothing."""

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
                X.append(np.mean(samples, axis=0))
                y.append(CALIBRATION_POINTS[index])
            points.append(TargetStatus(index, "ok" if samples else "skipped", len(samples)))

        usable = [p.index for p in points if p.state == "ok"]

        if len(usable) < MIN_USABLE_POINTS:
            return CalibrationResult(points, "failed", "too_few_points", None)

        rows = {index // GRID_SIDE for index in usable}
        columns = {index % GRID_SIDE for index in usable}

        if len(rows) < GRID_SIDE or len(columns) < GRID_SIDE:
            return CalibrationResult(points, "failed", "missing_row_or_column", None)

        model = GazeModel()
        model.train(np.array(X), np.array(y))

        return CalibrationResult(points, "ready", None, model)
