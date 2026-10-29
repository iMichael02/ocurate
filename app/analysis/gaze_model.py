from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline


class GazeModel:

    def __init__(self):

        self.model = Pipeline([
            ("scaler", StandardScaler()),

            ("regressor",
             Ridge(alpha=1.0))
        ])

        self.is_fitted = False

    def train(self, X, y):

        self.model.fit(X, y)

        self.is_fitted = True

    def predict(self, X):

        if not self.is_fitted:
            return None

        return self.model.predict(X)