import cv2


class Camera:
    """Wraps a webcam (see architecture-design.md step 1)."""

    def __init__(self, index=0):

        self.capture = cv2.VideoCapture(index)

        if not self.capture.isOpened():
            raise RuntimeError(f"Could not open webcam at index {index}")

    def read(self):
        """Returns a BGR frame, or None if a frame couldn't be captured."""

        ok, frame = self.capture.read()

        if not ok:
            return None

        return frame

    def release(self):

        self.capture.release()

    def __enter__(self):

        return self

    def __exit__(self, *_exc_info):

        self.release()
