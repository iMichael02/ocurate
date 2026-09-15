import time

import cv2
import mediapipe as mp

from mediapipe.tasks import python
from mediapipe.tasks.python import vision


class FaceTracker:

    def __init__(self, model_path):

        base_options = python.BaseOptions(
            model_asset_path=model_path
        )

        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_facial_transformation_matrixes=True
        )

        self.detector = vision.FaceLandmarker.create_from_options(
            options
        )

        self._start_time = time.monotonic()
        self._last_timestamp_ms = -1

    def process(self, frame):

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=rgb
        )

        # detect_for_video requires strictly increasing timestamps; derive
        # them from wall-clock time rather than assuming a fixed frame rate.
        timestamp_ms = int((time.monotonic() - self._start_time) * 1000)
        timestamp_ms = max(timestamp_ms, self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms

        result = self.detector.detect_for_video(
            mp_image,
            timestamp_ms
        )

        if not result.face_landmarks:
            return None

        return result