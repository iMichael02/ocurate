from sklearn.kernel_ridge import KernelRidge
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler

import numpy as np


class GazeModel:
    """Maps one feature row to a gaze point (x, y) in viewport fractions.

    The defaults are the model the service ships: standardized features into a linear `Ridge(alpha=1)`.
    The other options exist so the offline benchmark (benchmark/, docs/gaze-benchmark.md) can compare
    candidates; none of them is switched on in the service until the benchmark shows a gain on recorded
    data.

    alpha      Ridge / kernel ridge regularization strength.
    degree     2 or more adds polynomial terms of the standardized features before the regression.
    regressor  "ridge" (linear in the possibly polynomial features) or "kernel" (RBF kernel ridge).
    clip       Clip predictions to the screen, [0, 1] on both axes.
    """

    def __init__(self, alpha=1.0, degree=1, regressor="ridge", clip=False):

        steps = [("scaler", StandardScaler())]

        if degree > 1:
            steps.append(("poly", PolynomialFeatures(degree=degree, include_bias=False)))

        if regressor == "ridge":
            steps.append(("regressor", Ridge(alpha=alpha)))
        elif regressor == "kernel":
            steps.append(("regressor", KernelRidge(alpha=alpha, kernel="rbf")))
        else:
            raise ValueError(f"unknown regressor: {regressor!r}")

        self.model = Pipeline(steps)
        self.clip = clip
        self.is_fitted = False

    def train(self, X, y):

        self.model.fit(X, y)

        self.is_fitted = True

    def predict(self, X):

        if not self.is_fitted:
            return None

        prediction = self.model.predict(X)

        if self.clip:
            prediction = np.clip(prediction, 0.0, 1.0)

        return prediction

    def standardize(self, X):
        """`X` as the regressor sees it: each feature as a distance from its
        calibration mean, in calibration standard deviations. A value far from
        0 means this frame lies outside what calibration saw, so the
        prediction is an extrapolation. None before training."""

        if not self.is_fitted:
            return None

        return self.model.named_steps["scaler"].transform(X)
