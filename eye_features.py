import numpy as np

LEFT_IRIS = [474, 475, 476, 477]
RIGHT_IRIS = [469, 470, 471, 472]

LEFT_EYE_CORNERS = {"left": 362, "right": 263, "top": 386, "bottom": 374}
RIGHT_EYE_CORNERS = {"left": 133, "right": 33, "top": 159, "bottom": 145}

NOSE_TIP = 1

FEATURE_SIZE = 20


def landmark_xy(landmarks, index):

    p = landmarks[index]

    return np.array([
        p.x,
        p.y
    ], dtype=np.float32)


def iris_center(landmarks, indices):

    points = np.array([
        [landmarks[i].x, landmarks[i].y]
        for i in indices
    ])

    return points.mean(axis=0)


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


def _eye_features(landmarks, iris_indices, corners):

    iris = iris_center(landmarks, iris_indices)

    eye_left = landmark_xy(landmarks, corners["left"])
    eye_right = landmark_xy(landmarks, corners["right"])
    eye_top = landmark_xy(landmarks, corners["top"])
    eye_bottom = landmark_xy(landmarks, corners["bottom"])

    norm = normalize_iris(iris, eye_left, eye_right, eye_top, eye_bottom)
    ear = eye_aspect_ratio(eye_top, eye_bottom, eye_left, eye_right)

    return norm, ear


def extract_features(face_landmarker_result):
    """Builds the eye-appearance + head-pose + face-position feature vector
    (see architecture-design.md step 3) from a single MediaPipe
    FaceLandmarker result. Returns None if no face was detected.
    """

    if not face_landmarker_result or not face_landmarker_result.face_landmarks:
        return None

    transforms = getattr(face_landmarker_result, "facial_transformation_matrixes", None)

    if not transforms:
        # Head pose is part of the feature vector (see architecture-design.md
        # step 3); without it this frame isn't usable, same as no face at all.
        return None

    landmarks = face_landmarker_result.face_landmarks[0]

    left_norm, left_ear = _eye_features(landmarks, LEFT_IRIS, LEFT_EYE_CORNERS)
    right_norm, right_ear = _eye_features(landmarks, RIGHT_IRIS, RIGHT_EYE_CORNERS)

    nose = landmark_xy(landmarks, NOSE_TIP)

    matrix = np.array(transforms[0]).reshape(4, 4)
    rotation = matrix[:3, :3].flatten()
    translation = matrix[:3, 3]

    return np.concatenate([
        left_norm,
        right_norm,
        [left_ear, right_ear],
        rotation,
        translation,
        nose,
    ]).astype(np.float32)
