import numpy as np
import pytest

from gaze_model import GazeModel


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
