"""Counters that explain a reading Session that shows no progress.

Reading only starts on a fixation on the first Cell, and until then the service
sends nothing, so "no progress" looks the same whether the face was lost, the
gaze estimate was off screen, no fixation formed, or fixations landed on other
Cells. These counters tell those cases apart.

Counts, one rounded distance and one summary number about how far the features
are from calibration (the largest standardized value, and the name of the part
of the vector it came from): no landmarks, features or gaze coordinates (see
docs/adr/0003 and app/log_setup.py).
"""

from collections import Counter

import numpy as np

from app.analysis.cell_layout import distance_to_rect
from app.analysis.eye_features import feature_group

REPORT_EVERY_MS = 5000
# A standardized feature further than this from the calibration mean is outside what calibration saw.
OUT_OF_RANGE_Z = 3.0


class ReadingStats:

    def __init__(self, first_cell):
        """`first_cell` is the browser-reported rectangle of Cell (0, 0)."""

        self._first_cell = first_cell

        self.frames = 0
        self.no_face_frames = 0
        self.gaze_off_screen_frames = 0
        # The detector reports a fixation on every frame of a steady stare, so these count frames.
        self.fixation_frames = 0
        self.off_cell_frames = 0
        # Each time the fixated Cell changes, and how many of those came before reading started.
        self.cells_fixated = 0
        self.cells_fixated_before_start = 0
        self.nearest_to_first_cell = None
        self.started = False

        # How far the frame's features are from what calibration saw (see feature_scale).
        self.scaled_frames = 0
        self.frames_out_of_range = 0
        self.max_abs_z = 0.0

        self._sum_frame_max_z = 0.0
        self._worst_groups = Counter()
        self._last_cell = None

        self._first_t = None
        self._last_t = None
        self._last_report_t = None

    def frame(self, t):

        self.frames += 1

        if self._first_t is None:
            self._first_t = t
            self._last_report_t = t

        self._last_t = t

    def no_face(self):

        self.no_face_frames += 1

    def feature_scale(self, z, columns=None):
        """`z` is one frame's features in calibration standard deviations
        (`GazeModel.standardize`). Keeps the largest |z| of the frame, and
        which part of the feature vector it came from. `columns` says which
        positions of the full feature vector `z` holds (the model's columns);
        without it `z` is taken to be the whole vector."""

        magnitudes = np.abs(np.asarray(z, dtype=float))
        worst = int(magnitudes.argmax())
        frame_max = float(magnitudes[worst])

        self.scaled_frames += 1
        self._sum_frame_max_z += frame_max
        self.max_abs_z = max(self.max_abs_z, frame_max)

        if frame_max > OUT_OF_RANGE_Z:
            self.frames_out_of_range += 1
            self._worst_groups[feature_group(worst if columns is None else columns[worst])] += 1

    def gaze(self, x, y):

        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            self.gaze_off_screen_frames += 1

    def fixation(self, x, y, cell):
        """A fixation the detector reported at gaze (x, y), on `cell` (None when on no Cell)."""

        self.fixation_frames += 1

        if not self.started:
            distance = distance_to_rect(self._first_cell, x, y)

            if self.nearest_to_first_cell is None or distance < self.nearest_to_first_cell:
                self.nearest_to_first_cell = distance

        if cell is None:
            self.off_cell_frames += 1
            return

        if cell != self._last_cell:
            self.cells_fixated += 1

            if not self.started and cell != (0, 0):
                self.cells_fixated_before_start += 1

        self._last_cell = cell

    def report_due(self, t):

        if self._last_report_t is None or t - self._last_report_t < REPORT_EVERY_MS:
            return False

        self._last_report_t = t

        return True

    def fields(self):
        """Log fields. `nearest_to_first_cell` is how far (0-1 of the viewport)
        the closest fixation got to Cell (0, 0) before reading started."""

        seconds = 0.0 if self._first_t is None else (self._last_t - self._first_t) / 1000.0
        nearest = self.nearest_to_first_cell
        scaled = self.scaled_frames
        worst_group = self._worst_groups.most_common(1)[0][0] if self._worst_groups else None

        return {
            "reading_started": self.started,
            "reading_seconds": round(seconds, 1),
            "frames": self.frames,
            "no_face_frames": self.no_face_frames,
            "gaze_off_screen_frames": self.gaze_off_screen_frames,
            "fixation_frames": self.fixation_frames,
            "off_cell_frames": self.off_cell_frames,
            "cells_fixated": self.cells_fixated,
            "cells_fixated_before_start": self.cells_fixated_before_start,
            "nearest_to_first_cell": None if nearest is None else round(nearest, 3),
            "frames_out_of_range": self.frames_out_of_range,
            "max_abs_z": round(self.max_abs_z, 1),
            "mean_max_abs_z": round(self._sum_frame_max_z / scaled, 1) if scaled else 0.0,
            "worst_feature_group": worst_group,
        }
