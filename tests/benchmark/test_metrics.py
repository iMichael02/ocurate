import math

import numpy as np
import pytest

from benchmark.metrics import Geometry, error_cm, error_degrees, error_fraction, share, summarize

GEOMETRY = Geometry(screen_width_cm=40.0, screen_height_cm=20.0, distance_cm=60.0)


def test_error_fraction_is_the_euclidean_distance_in_viewport_fractions():

    assert error_fraction([0.5, 0.5], [0.8, 0.9]) == pytest.approx(0.5)


def test_error_cm_scales_each_axis_by_the_screen_size():

    assert error_cm([0.0, 0.0], [0.1, 0.0], GEOMETRY) == pytest.approx(4.0)
    assert error_cm([0.0, 0.0], [0.0, 0.1], GEOMETRY) == pytest.approx(2.0)


def test_error_degrees_is_the_visual_angle_at_the_viewing_distance():

    # 60 cm to the side at 60 cm away is 45 degrees.
    wide = Geometry(screen_width_cm=60.0, screen_height_cm=60.0, distance_cm=60.0)

    assert error_degrees([0.0, 0.0], [1.0, 0.0], wide) == pytest.approx(45.0)
    assert error_degrees([0.3, 0.3], [0.3, 0.3], wide) == pytest.approx(0.0)


def test_errors_work_on_many_rows_at_once():

    predicted = np.array([[0.0, 0.0], [0.5, 0.5]])
    truth = np.array([[0.3, 0.4], [0.5, 0.5]])

    assert error_fraction(predicted, truth) == pytest.approx([0.5, 0.0])


def test_summarize_gives_mean_median_p90_and_count():

    s = summarize([1.0, 2.0, 3.0, 4.0, 10.0])

    assert s["mean"] == pytest.approx(4.0)
    assert s["median"] == pytest.approx(3.0)
    assert s["p90"] == pytest.approx(np.percentile([1, 2, 3, 4, 10], 90))
    assert s["n"] == 5


def test_summarize_and_share_of_nothing_are_nan_not_an_error():

    assert math.isnan(summarize([])["mean"])
    assert summarize([])["n"] == 0
    assert math.isnan(share([]))


def test_share_is_the_fraction_of_true():

    assert share([True, False, True, True]) == pytest.approx(0.75)
