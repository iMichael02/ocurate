import numpy as np

class FixationDetector:

    def __init__(
        self,
        max_dispersion=0.03,
        min_duration=0.15,
        max_gap=0.5
    ):

        self.max_dispersion = max_dispersion
        self.min_duration = min_duration
        self.max_gap = max_gap

        self.samples = []

    def update(self, gaze, timestamp):

        if self.samples and (timestamp - self.samples[-1][0]) > self.max_gap:

            self.samples = []

        self.samples.append(
            (timestamp, gaze)
        )

        if len(self.samples) < 2:
            return None

        positions = np.array([
            x[1]
            for x in self.samples
        ])

        dispersion = (
            positions.max(axis=0)
            -
            positions.min(axis=0)
        )

        if np.max(dispersion) > self.max_dispersion:

            self.samples = [
                self.samples[-1]
            ]

            return None

        duration = (
            self.samples[-1][0]
            -
            self.samples[0][0]
        )

        if duration >= self.min_duration:

            center = positions.mean(axis=0)

            return {
                "position": center,
                "duration": duration
            }

        return None