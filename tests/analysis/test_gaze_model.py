import numpy as np
import pytest

from app.analysis.gaze_model import GazeModel


def test_predict_returns_none_before_training():

    model = GazeModel()

    assert model.predict(np.zeros((1, 4))) is None


def test_train_then_predict_recovers_a_linear_relationship():

    model = GazeModel()

    X = np.array([[0.0], [1.0], [2.0], [3.0]])
    y = np.array([[0.0, 1.0], [1.0, 1.0], [2.0, 1.0], [3.0, 1.0]])

    model.train(X, y)

    prediction = model.predict(np.array([[1.5]]))

    assert prediction[0][0] == pytest.approx(1.5, abs=0.2)
    assert prediction[0][1] == pytest.approx(1.0, abs=0.2)


def test_standardize_returns_none_before_training():

    assert GazeModel().standardize(np.zeros((1, 2))) is None


def test_standardize_measures_distance_from_the_calibration_mean_in_calibration_deviations():

    model = GazeModel()
    X = np.array([[0.0, 10.0], [2.0, 10.0], [4.0, 10.5], [6.0, 10.5]])
    model.train(X, np.zeros((4, 2)))

    z = model.standardize(np.array([[3.0, 10.25], [3.0 + 2 * X[:, 0].std(), 10.25 + 3 * X[:, 1].std()]]))

    assert z[0] == pytest.approx([0.0, 0.0])
    assert z[1] == pytest.approx([2.0, 3.0])


def test_a_feature_that_barely_moved_in_calibration_gives_a_huge_value_for_a_small_shift():
    """The failure this exists to expose: a still head in calibration, a slightly different seat later."""

    model = GazeModel()
    X = np.array([[0.0, 5.000], [1.0, 5.001], [2.0, 4.999], [3.0, 5.000]])
    model.train(X, np.zeros((4, 2)))

    z = model.standardize(np.array([[1.5, 5.05]]))

    assert abs(z[0][1]) > 30
