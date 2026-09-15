import numpy as np
import pytest

from eye_features import normalize_iris, eye_aspect_ratio, extract_features, FEATURE_SIZE


def test_normalize_iris_centered_gives_midpoint():

    eye_left = np.array([0.0, 0.0])
    eye_right = np.array([1.0, 0.0])
    eye_top = np.array([0.5, 0.0])
    eye_bottom = np.array([0.5, 1.0])

    iris = np.array([0.5, 0.5])

    horizontal, vertical = normalize_iris(iris, eye_left, eye_right, eye_top, eye_bottom)

    assert horizontal == pytest.approx(0.5)
    assert vertical == pytest.approx(0.5)


def test_eye_aspect_ratio_is_zero_when_closed():

    top = np.array([0.5, 0.0])
    bottom = np.array([0.5, 0.0])
    left = np.array([0.0, 0.0])
    right = np.array([1.0, 0.0])

    assert eye_aspect_ratio(top, bottom, left, right) == 0.0


def test_extract_features_returns_none_without_a_face():

    class EmptyResult:
        face_landmarks = []

    assert extract_features(EmptyResult()) is None


class _Landmark:
    def __init__(self, x, y, z=0.0):
        self.x = x
        self.y = y
        self.z = z


def _fake_face_result(transforms=(np.eye(4),)):

    landmarks = [_Landmark(0.5, 0.5) for _ in range(478)]

    # place both eyes' corners and irises so normalize_iris/EAR don't divide by zero
    for idx, (x, y) in {
        362: (0.3, 0.4), 263: (0.4, 0.4), 386: (0.35, 0.35), 374: (0.35, 0.45),
        133: (0.6, 0.4), 33: (0.7, 0.4), 159: (0.65, 0.35), 145: (0.65, 0.45),
        1: (0.5, 0.6),
    }.items():
        landmarks[idx] = _Landmark(x, y)

    for idx in [474, 475, 476, 477]:
        landmarks[idx] = _Landmark(0.35, 0.4)

    for idx in [469, 470, 471, 472]:
        landmarks[idx] = _Landmark(0.65, 0.4)

    class Result:
        face_landmarks = [landmarks]
        facial_transformation_matrixes = transforms

    return Result()


def test_extract_features_shape():

    features = extract_features(_fake_face_result())

    assert features.shape == (FEATURE_SIZE,)
    assert features.dtype == np.float32


def test_extract_features_returns_none_without_a_transformation_matrix():

    assert extract_features(_fake_face_result(transforms=None)) is None
