import numpy as np

class GazeSmoother:

    def __init__(self, alpha=0.25):

        self.alpha = alpha
        self.previous = None

    def update(self, gaze):

        gaze = np.asarray(gaze)

        if self.previous is None:

            self.previous = gaze
            return gaze

        self.previous = (
            self.alpha * gaze
            +
            (1 - self.alpha) * self.previous
        )

        return self.previous