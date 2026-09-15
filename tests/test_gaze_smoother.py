import numpy as np

from gaze_smoother import GazeSmoother


def test_first_update_passes_through_unchanged():

    smoother = GazeSmoother(alpha=0.25)

    result = smoother.update([0.5, 0.5])

    assert np.allclose(result, [0.5, 0.5])


def test_smooths_towards_new_value():

    smoother = GazeSmoother(alpha=0.5)

    smoother.update([0.0, 0.0])
    result = smoother.update([1.0, 1.0])

    assert np.allclose(result, [0.5, 0.5])
