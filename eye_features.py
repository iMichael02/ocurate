import numbers

import numpy as np

# MediaPipe Face Landmarker ids of the landmark subset the browser sends. The
# order of these lists is the order of `frame.iris` and `frame.eye_corners`
# (see protocol.py and docs/websocket-protocol.md). Only the order matters to
# this module; the ids document where each value comes from.
LEFT_IRIS = [474, 475, 476, 477]
RIGHT_IRIS = [469, 470, 471, 472]

LEFT_EYE_CORNERS = {"left": 362, "right": 263, "top": 386, "bottom": 374}
RIGHT_EYE_CORNERS = {"left": 133, "right": 33, "top": 159, "bottom": 145}

NOSE_TIP = 1

IRIS_IDS = LEFT_IRIS + RIGHT_IRIS
EYE_CORNER_IDS = [LEFT_EYE_CORNERS[k] for k in ("left", "right", "top", "bottom")] + \
                 [RIGHT_EYE_CORNERS[k] for k in ("left", "right", "top", "bottom")]

FEATURE_SIZE = 20

# Protocol version 2 appends the browser's eye centre (Timm & Barth) per eye,
# normalized like the iris: left eye (x, y), then right eye (x, y).
FEATURE_SIZE_V2 = 24

# Below this the browser's eye centre is not trusted and the landmark mean
# stands in for it. Tunable here without a frontend release.
EYE_CENTRE_MIN_CONFIDENCE = 0.5


def landmark_xy(p):

    return np.array([
        p.x,
        p.y
    ], dtype=np.float32)


def iris_center(points):

    return np.array([
        [p.x, p.y]
        for p in points
    ]).mean(axis=0)


def normalize_iris(
    iris,
    eye_left,
    eye_right,
    eye_top,
    eye_bottom
):

    eye_width = np.linalg.norm(
        eye_right - eye_left
    )

    eye_height = np.linalg.norm(
        eye_bottom - eye_top
    )

    horizontal = np.dot(
        iris - eye_left,
        eye_right - eye_left
    ) / (eye_width ** 2 + 1e-8)

    vertical = np.dot(
        iris - eye_top,
        eye_bottom - eye_top
    ) / (eye_height ** 2 + 1e-8)

    return np.array([
        horizontal,
        vertical
    ])


def eye_aspect_ratio(
    top,
    bottom,
    left,
    right
):

    vertical = np.linalg.norm(
        top - bottom
    )

    horizontal = np.linalg.norm(
        left - right
    )

    return vertical / (
        horizontal + 1e-8
    )


def _eye_features(iris_points, corner_points):
    """`corner_points` is left, right, top, bottom."""

    iris = iris_center(iris_points)

    eye_left, eye_right, eye_top, eye_bottom = (landmark_xy(p) for p in corner_points)

    norm = normalize_iris(iris, eye_left, eye_right, eye_top, eye_bottom)
    ear = eye_aspect_ratio(eye_top, eye_bottom, eye_left, eye_right)

    return norm, ear


def _usable_landmarks(points, count):
    """True if `points` holds `count` landmarks, each with finite x and y
    inside the camera image (0-1). The protocol lets landmarks lie slightly
    outside the image; those frames are unusable, same as no face."""

    if points is None or len(points) != count:
        return False

    for p in points:
        x = getattr(p, "x", None)
        y = getattr(p, "y", None)
        if not (isinstance(x, numbers.Real) and isinstance(y, numbers.Real)):
            return False
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            return False

    return True


def _pose_matrix(matrix):
    """The 4x4 transformation matrix (rows) as an array, or None if it is
    missing, not 4x4 or not finite."""

    if matrix is None:
        return None

    try:
        array = np.array(matrix, dtype=np.float64)
    except (TypeError, ValueError):
        return None

    if array.shape != (4, 4) or not np.isfinite(array).all():
        return None

    return array


def _eye_centre_features(frame, iris, corners):
    """The 4 values protocol version 2 appends: per eye, the browser's eye
    centre normalized against that eye's corners. An eye whose centre is
    missing, below EYE_CENTRE_MIN_CONFIDENCE or off the image uses the mean of
    its iris landmarks instead, so the vector keeps its size."""

    centres = getattr(frame, "eye_centres", None)

    values = []

    for eye in range(2):
        eye_iris = iris[eye * 4:eye * 4 + 4]
        eye_corners = corners[eye * 4:eye * 4 + 4]

        position = iris_center(eye_iris)

        if centres is not None and len(centres) == 2:
            centre = centres[eye]
            if (centre.confidence >= EYE_CENTRE_MIN_CONFIDENCE
                    and _usable_landmarks([centre], 1)):
                position = landmark_xy(centre)

        left, right, top, bottom = (landmark_xy(p) for p in eye_corners)
        values.append(normalize_iris(position, left, right, top, bottom))

    return np.concatenate(values)


def extract_features(frame, use_eye_centres=False):
    """Builds the eye-appearance + head-pose + face-position feature vector
    (see architecture-design.md step 3) from one browser `frame` message
    (protocol.Frame): 8 iris landmarks, 8 eye-corner landmarks, the nose tip
    and the 4x4 facial transformation matrix (row-major). Returns None
    ("no face") if any of them is missing or unusable.

    `use_eye_centres` selects the protocol version 2 vector (FEATURE_SIZE_V2):
    the version 1 vector followed by the eye centres from `frame.eye_centres`.
    The Session manager sets it from the negotiated version, so a Session never
    mixes vector sizes.
    """

    if frame is None:
        return None

    iris = getattr(frame, "iris", None)
    corners = getattr(frame, "eye_corners", None)
    nose = getattr(frame, "nose", None)

    if not _usable_landmarks(iris, 8) or not _usable_landmarks(corners, 8):
        return None

    if not _usable_landmarks([nose], 1):
        return None

    matrix = _pose_matrix(getattr(frame, "matrix", None))

    if matrix is None:
        # Head pose is part of the feature vector (see architecture-design.md
        # step 3); without it this frame isn't usable, same as no face at all.
        return None

    left_norm, left_ear = _eye_features(iris[:4], corners[:4])
    right_norm, right_ear = _eye_features(iris[4:], corners[4:])

    rotation = matrix[:3, :3].flatten()
    translation = matrix[:3, 3]

    parts = [
        left_norm,
        right_norm,
        [left_ear, right_ear],
        rotation,
        translation,
        landmark_xy(nose),
    ]

    if use_eye_centres:
        parts.append(_eye_centre_features(frame, iris, corners))

    return np.concatenate(parts).astype(np.float32)
