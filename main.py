import time

import cv2
import numpy as np

from calibration import CALIBRATION_POINTS, gaze_to_braille_cell
from camera import Camera
from eye_features import extract_features
from face_tracker import FaceTracker
from fixation_detector import FixationDetector
from gaze_model import GazeModel
from gaze_smoother import GazeSmoother
from passage import build_default_passage
from reading_session import ReadingSession
from braille_render import render_calibration_frame, render_passage_frame, render_result_frame, cell_geometry

WINDOW_NAME = "Ocurate"
CANVAS_WIDTH = 1000
CANVAS_HEIGHT = 400
MODEL_PATH = "models/face_landmarker.task"
CALIBRATION_DWELL_SECONDS = 1.5
QUIT_KEYS = {ord("q"), 27}


def _quit_requested():

    return cv2.waitKey(1) & 0xFF in QUIT_KEYS


def run_calibration(camera, face_tracker):

    X = []
    y = []

    for point in CALIBRATION_POINTS:

        samples = []
        deadline = time.monotonic() + CALIBRATION_DWELL_SECONDS

        while time.monotonic() < deadline:

            frame = camera.read()
            if frame is None:
                continue

            result = face_tracker.process(frame)
            features = extract_features(result)

            if features is not None:
                samples.append(features)

            cv2.imshow(WINDOW_NAME, render_calibration_frame(CANVAS_WIDTH, CANVAS_HEIGHT, point))

            if _quit_requested():
                return None, None

        if samples:
            X.append(np.mean(samples, axis=0))
            y.append(point)
        else:
            print(f"Warning: no face detected during calibration point {point}, skipping.")

    if len(X) < 2:
        print("Calibration failed: not enough usable calibration points.")
        return None, None

    return np.array(X), np.array(y)


def run_reading(camera, face_tracker, gaze_model, passage):

    smoother = GazeSmoother()
    fixation_detector = FixationDetector()
    session = ReadingSession(passage)

    canvas_width, canvas_height = CANVAS_WIDTH, CANVAS_HEIGHT
    cell_width, line_height = cell_geometry(canvas_width, canvas_height, passage)

    start = time.monotonic()

    while not session.is_complete():

        frame = camera.read()
        if frame is None:
            continue

        result = face_tracker.process(frame)
        features = extract_features(result)

        highlight = None

        if features is not None:

            gaze = gaze_model.predict(features.reshape(1, -1))[0]
            gaze = smoother.update(gaze)

            now = time.monotonic() - start
            fixation = fixation_detector.update(gaze, now)

            if fixation is not None:

                row, column = gaze_to_braille_cell(
                    gaze_x=fixation["position"][0],
                    gaze_y=fixation["position"][1],
                    screen_width=canvas_width,
                    screen_height=canvas_height,
                    cell_width=cell_width,
                    line_height=line_height,
                    num_rows=passage.num_rows,
                    num_columns=passage.num_columns,
                )

                session.register_fixation(row, column, now)
                highlight = (row, column)

        cv2.imshow(WINDOW_NAME, render_passage_frame(canvas_width, canvas_height, passage, highlight_cell=highlight))

        if _quit_requested():
            return None

    return session.result()


def main():

    passage = build_default_passage()
    face_tracker = FaceTracker(MODEL_PATH)
    gaze_model = GazeModel()

    cv2.namedWindow(WINDOW_NAME)

    with Camera() as camera:

        X, y = run_calibration(camera, face_tracker)

        if X is None:
            cv2.destroyAllWindows()
            return

        gaze_model.train(X, y)

        result = run_reading(camera, face_tracker, gaze_model, passage)

        if result is not None:
            cv2.imshow(WINDOW_NAME, render_result_frame(CANVAS_WIDTH, CANVAS_HEIGHT, result))
            cv2.waitKey(0)

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
