"""A simulated Learner, for developing and testing the benchmark. NOT a measure of real accuracy.

The numbers it produces say nothing about the shipped model on real faces: the eye model below is a guess.
It exists so the harness, metrics and candidate switches can be exercised end to end before recordings
exist, and so tests have deterministic input. Recordings made with `synthetic=True` are marked so a report
can never mix them with real ones.

Model of one Learner: the iris position inside each eye is a mildly non-linear function of the gaze point
plus a pull from head rotation, observed through camera noise. Conditions change the noise, the head
movement and the number of bad eye-centre readings.
"""

import hashlib
import math

import numpy as np

from app.analysis.calibration import CALIBRATION_POINTS
from app.schemas import protocol
from benchmark.metrics import Geometry
from benchmark.recording import Recording

FPS = 30.0
CALIBRATION_FRAMES_PER_POINT = 30
GEOMETRY = Geometry(screen_width_cm=34.4, screen_height_cm=19.4, distance_cm=60.0)

# Image-space landmark noise (fraction of the image width) and its factors per condition value.
BASE_NOISE = 0.0006
NOISE = {
    "lighting": {"good": 1.0, "dim": 3.0},
    "webcam": {"hd": 1.0, "low": 2.0},
    "glasses": {"no": 1.0, "yes": 1.8},
}
EYE_WIDTH = {"near": 0.10, "far": 0.06}               # eye width in the image
HEAD_MOVEMENT = {"still": 0.001, "moving": 0.008}      # random-walk step of the head angles, radians
CENTRE_OUTLIERS = {"no": 0.01, "yes": 0.15}           # share of bad eye-centre readings

DEFAULT_CONDITIONS = {"lighting": "good", "glasses": "no", "distance": "near", "webcam": "hd", "head": "still"}

PASSAGE_ROWS, PASSAGE_COLUMNS = 3, 14


def passage_cells():
    """The Cell Layout of the default Passage as a browser would measure it, filling the middle of the screen."""

    width, height = 0.84 / PASSAGE_COLUMNS, 0.15
    return [
        protocol.CellRect(row=row, col=col, x=0.08 + col * width, y=0.25 + row * (height + 0.02), w=width, h=height)
        for row in range(PASSAGE_ROWS)
        for col in range(PASSAGE_COLUMNS)
    ]


def _rng(learner, seed):

    digest = hashlib.sha256(f"{learner}:{seed}".encode()).digest()

    return np.random.default_rng(int.from_bytes(digest[:8], "big"))


def _rotation(yaw, pitch, roll):

    cy, sy, cp, sp, cr, sr = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch), math.cos(roll), math.sin(roll)
    rz = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])

    return rz @ ry @ rx


class _Learner:
    """Fixed traits of one simulated Learner plus the moving head."""

    def __init__(self, rng, conditions):

        self.rng = rng
        self.conditions = conditions
        self.noise = (BASE_NOISE * NOISE["lighting"][conditions["lighting"]] * NOISE["webcam"][conditions["webcam"]]
                      * NOISE["glasses"][conditions["glasses"]])
        self.eye_width = EYE_WIDTH[conditions["distance"]]
        self.head_step = HEAD_MOVEMENT[conditions["head"]]
        self.outliers = CENTRE_OUTLIERS[conditions["glasses"]]

        # How far the iris travels across the eye for a full screen of gaze, per eye.
        self.gain = rng.uniform(0.30, 0.55, size=(2, 2))
        self.offset = rng.normal(0.0, 0.02, size=(2, 2))
        self.curve = rng.normal(0.0, 0.05, size=(2, 2))
        self.head_pull = rng.uniform(0.3, 0.7, size=2)       # how much head yaw/pitch shifts the iris
        self.angles = np.zeros(3)
        self.shift = np.zeros(3)
        self.blink_left = 0

    def _step_head(self):

        self.angles += self.rng.normal(0.0, self.head_step, 3)
        self.angles *= 0.995
        self.shift += self.rng.normal(0.0, self.head_step * 2, 3)
        self.shift *= 0.995

    def frame(self, gaze, t_ms, target=None, with_centres=True):
        """One protocol Frame for a Learner looking at `gaze`, or None (no face) now and then."""

        rng = self.rng
        self._step_head()

        if rng.random() < 0.01:
            return None

        if self.blink_left == 0 and rng.random() < 0.012:
            self.blink_left = 3
        blinking = self.blink_left > 0
        self.blink_left = max(0, self.blink_left - 1)

        centred = np.asarray(gaze) - 0.5
        yaw, pitch = self.angles[0], self.angles[1]
        iris, corners, centres = [], [], []

        for eye in range(2):
            x0 = (0.40 if eye == 0 else 0.55) + self.shift[0] * 0.1
            y0 = 0.42 + self.shift[1] * 0.1
            width = self.eye_width * (1.0 + self.shift[2] * 0.1)
            openness = 0.05 if blinking else rng.normal(0.32, 0.01)
            height = width * openness

            h = 0.5 + self.gain[eye, 0] * centred[0] + self.offset[eye, 0] + self.curve[eye, 0] * centred[0] ** 2
            v = 0.5 + self.gain[eye, 1] * centred[1] + self.offset[eye, 1] + self.curve[eye, 1] * centred[1] ** 2
            h += self.head_pull[0] * yaw
            v += self.head_pull[1] * pitch
            if blinking:
                v -= 0.25

            cx, cy = x0 + h * width, y0 + v * height
            radius = 0.06 * width
            for dx, dy in ((-radius, 0), (radius, 0), (0, -radius), (0, radius)):
                iris.append(self._landmark(cx + dx, cy + dy))

            for dx, dy in ((0, height / 2), (width, height / 2), (width / 2, 0), (width / 2, height)):
                corners.append(self._landmark(x0 + dx, y0 + dy))

            bad = rng.random() < self.outliers
            offset = rng.normal(0.0, width * (0.12 if bad else 0.02), 2)
            centres.append(protocol.EyeCentre(
                x=float(np.clip(cx + offset[0], 0, 1)), y=float(np.clip(cy + offset[1], 0, 1)),
                confidence=float(rng.uniform(0.3, 0.6) if bad else rng.uniform(0.6, 0.95))))

        nose = self._landmark(0.5 + self.shift[0] * 0.1, 0.55 + self.shift[1] * 0.1)
        matrix = np.eye(4)
        matrix[:3, :3] = _rotation(*self.angles)
        matrix[:3, 3] = self.shift * 10.0

        return protocol.Frame(
            type="frame", t=t_ms, iris=iris, eye_corners=corners, nose=nose, matrix=matrix.tolist(),
            target=None if target is None else protocol.Point(x=target[0], y=target[1]),
            eye_centres=centres if with_centres else None)

    def _landmark(self, x, y):

        x, y = (np.clip(np.array([x, y]) + self.rng.normal(0.0, self.noise, 2), 0.0, 1.0))

        return protocol.Landmark(x=float(x), y=float(y))


def generate_learner(learner, conditions=None, seed=0, dwell_frames=(9, 15)):
    """A synthetic Recording of `learner`: 16 targets with 30 frames each, then a read of the default Passage."""

    conditions = {**DEFAULT_CONDITIONS, **(conditions or {})}
    rng = _rng(learner, seed)
    person = _Learner(rng, conditions)
    step_ms = 1000.0 / FPS
    jitter = 0.004                                   # fixational eye movement of the true gaze, viewport fraction

    t = 0.0
    calibration = []
    for target in CALIBRATION_POINTS:
        for _ in range(CALIBRATION_FRAMES_PER_POINT):
            gaze = np.asarray(target) + rng.normal(0.0, jitter, 2)
            calibration.append((target, person.frame(gaze, t, target=target)))
            t += step_ms

    t += 2000.0
    cells = passage_cells()
    reading = []
    for cell in cells:
        truth = (cell.x + cell.w / 2, cell.y + cell.h / 2)
        for _ in range(int(rng.integers(dwell_frames[0], dwell_frames[1] + 1))):
            gaze = np.asarray(truth) + rng.normal(0.0, jitter, 2)
            reading.append((truth, person.frame(gaze, t)))
            t += step_ms

    return Recording(learner=learner, geometry=GEOMETRY, cells=cells, calibration=calibration, reading=reading,
                     conditions=conditions, synthetic=True)


def generate_cohort(learners_per_condition=4, seed=0):
    """Learners spread over the conditions: the default set-up and one change at a time."""

    variants = [("baseline", {})]
    for key, values in (("lighting", ["dim"]), ("glasses", ["yes"]), ("distance", ["far"]),
                        ("webcam", ["low"]), ("head", ["moving"])):
        variants += [(f"{key}-{value}", {key: value}) for value in values]

    return [
        generate_learner(f"{label}-{n}", conditions, seed=seed)
        for label, conditions in variants
        for n in range(learners_per_condition)
    ]
