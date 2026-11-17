"""Accuracy metrics for the gaze benchmark (docs/gaze-benchmark.md). Defined before any result was looked at.

Primary:   Cell accuracy, the share of fixation frames whose predicted Braille Cell is the Cell the
           Learner was looking at. This is what decides Reading Speed and the secondary metrics.
Secondary: point-of-gaze error, the Euclidean distance between the estimated and true gaze point, in
           viewport fractions (x and y each 0 to 1), in centimetres, and in degrees of visual angle.
"""

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Geometry:
    """The physical set-up of a recording, needed to turn screen fractions into cm and degrees."""

    screen_width_cm: float
    screen_height_cm: float
    distance_cm: float


def error_fraction(predicted, truth):
    """Euclidean distance between rows of (x, y) in viewport fractions."""

    return np.linalg.norm(np.asarray(predicted, dtype=float) - np.asarray(truth, dtype=float), axis=-1)


def error_cm(predicted, truth, geometry):

    delta = np.asarray(predicted, dtype=float) - np.asarray(truth, dtype=float)
    scale = np.array([geometry.screen_width_cm, geometry.screen_height_cm])

    return np.linalg.norm(delta * scale, axis=-1)


def error_degrees(predicted, truth, geometry):
    """Visual angle of the on-screen error seen from `geometry.distance_cm`."""

    return np.degrees(np.arctan2(error_cm(predicted, truth, geometry), geometry.distance_cm))


def summarize(values):
    """Mean, median and 90th percentile of `values`; NaN for an empty list."""

    values = np.asarray(values, dtype=float)

    if values.size == 0:
        return {"mean": math.nan, "median": math.nan, "p90": math.nan, "n": 0}

    return {
        "mean": float(values.mean()),
        "median": float(np.median(values)),
        "p90": float(np.percentile(values, 90)),
        "n": int(values.size),
    }


def share(hits):
    """The share of True in `hits`; NaN for an empty list."""

    hits = list(hits)

    return sum(hits) / len(hits) if hits else math.nan
