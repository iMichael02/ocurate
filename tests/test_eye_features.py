import copy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import protocol
from eye_features import (
    normalize_iris, eye_aspect_ratio, extract_features, FEATURE_SIZE,
    IRIS_IDS, EYE_CORNER_IDS, NOSE_TIP,
)


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


GOLDEN = json.loads((Path(__file__).parent / "golden" / "eye_features.json").read_text())


def _frame_message(**overrides):
    """A valid browser frame: both eyes placed so normalize_iris/EAR don't
    divide by zero."""

    corners = {
        362: (0.3, 0.4), 263: (0.4, 0.4), 386: (0.35, 0.35), 374: (0.35, 0.45),
        133: (0.6, 0.4), 33: (0.7, 0.4), 159: (0.65, 0.35), 145: (0.65, 0.45),
    }

    message = {
        "type": "frame",
        "t": 100.0,
        "iris": [{"x": 0.35, "y": 0.4}] * 4 + [{"x": 0.65, "y": 0.4}] * 4,
        "eye_corners": [{"x": corners[i][0], "y": corners[i][1]} for i in EYE_CORNER_IDS],
        "nose": {"x": 0.5, "y": 0.6},
        "matrix": np.eye(4).tolist(),
    }
    message.update(overrides)

    return message


def _frame(**overrides):

    return protocol.Frame.model_validate(_frame_message(**overrides))


def test_landmark_ids_match_the_protocol_order():

    assert IRIS_IDS == [474, 475, 476, 477, 469, 470, 471, 472]
    assert EYE_CORNER_IDS == [362, 263, 386, 374, 133, 33, 159, 145]
    assert NOSE_TIP == 1


def test_extract_features_shape():

    features = extract_features(_frame())

    assert features.shape == (FEATURE_SIZE,)
    assert features.dtype == np.float32


def test_extract_features_vector_layout():

    features = extract_features(_frame(matrix=[[1, 2, 3, 10], [4, 5, 6, 11], [7, 8, 9, 12], [0, 0, 0, 1]]))

    assert features[6:15].tolist() == [1, 2, 3, 4, 5, 6, 7, 8, 9]    # rotation, row-major
    assert features[15:18].tolist() == [10, 11, 12]                  # translation
    assert features[18:20] == pytest.approx([0.5, 0.6])              # nose


@pytest.mark.parametrize("index", range(len(GOLDEN["cases"])))
def test_matches_vectors_recorded_from_the_old_implementation(index):

    case = GOLDEN["cases"][index]

    features = extract_features(protocol.Frame.model_validate(case["frame"]))

    np.testing.assert_array_equal(features, np.array(case["expected"], dtype=np.float32))


def test_golden_inputs_are_valid_protocol_frames():

    assert len(GOLDEN["cases"]) >= 10

    for case in GOLDEN["cases"]:
        protocol.parse_client_message(json.dumps(case["frame"]))


def test_extract_features_returns_none_without_a_frame():

    assert extract_features(None) is None


@pytest.mark.parametrize("field", ["iris", "eye_corners"])
def test_returns_none_when_a_landmark_is_missing(field):

    frame = _frame()
    frame = SimpleNamespace(**{**frame.__dict__, field: getattr(frame, field)[:-1]})

    assert extract_features(frame) is None


@pytest.mark.parametrize("field", ["iris", "eye_corners", "nose", "matrix"])
def test_returns_none_when_a_field_is_absent(field):

    frame = _frame()
    values = {k: v for k, v in frame.__dict__.items() if k != field}

    assert extract_features(SimpleNamespace(**values)) is None
    assert extract_features(SimpleNamespace(**{**values, field: None})) is None


def test_returns_none_for_a_landmark_without_coordinates():

    frame = _frame()
    iris = list(frame.iris)
    iris[2] = SimpleNamespace(x=None, y=0.5)

    assert extract_features(SimpleNamespace(**{**frame.__dict__, "iris": iris})) is None


@pytest.mark.parametrize("value", [-0.2, 1.3])
def test_returns_none_when_a_landmark_is_outside_the_camera_image(value):
    # Valid on the wire (the protocol allows -0.5 to 1.5) but unusable.

    assert extract_features(_frame(nose={"x": value, "y": 0.5})) is None
    assert extract_features(_frame(iris=[{"x": 0.35, "y": value}] * 4 + [{"x": 0.65, "y": 0.4}] * 4)) is None


def test_landmarks_on_the_image_edge_are_usable():

    assert extract_features(_frame(nose={"x": 0.0, "y": 1.0})) is not None


@pytest.mark.parametrize("matrix", [
    [[1, 0, 0, 0]] * 3,                       # 3x4
    [[1, 0, 0]] * 4,                          # 4x3
    [0.0] * 16,                               # flat
    [[1, 0, 0, 0], [0, 1, 0], [0, 0, 1, 0], [0, 0, 0, 1]],   # ragged
    [["a"] * 4] * 4,                          # not numbers
    [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, float("nan")]],
    [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, float("inf")]],
    "matrix",
    [],
])
def test_returns_none_for_a_malformed_matrix(matrix):

    frame = _frame()

    assert extract_features(SimpleNamespace(**{**frame.__dict__, "matrix": matrix})) is None


def test_does_not_modify_the_frame():

    frame = _frame()
    before = copy.deepcopy(frame.model_dump())

    extract_features(frame)

    assert frame.model_dump() == before


# --- eye centres from the browser (protocol v2) -------------------------------

from eye_features import EYE_CENTRE_MIN_CONFIDENCE, FEATURE_SIZE_V2


def _centres(left=(0.34, 0.41), right=(0.66, 0.39), confidence=0.9):

    return [
        {"x": left[0], "y": left[1], "confidence": confidence},
        {"x": right[0], "y": right[1], "confidence": confidence},
    ]


def test_v2_feature_size_extends_the_v1_vector():

    assert FEATURE_SIZE == 20
    assert FEATURE_SIZE_V2 == 24


def test_v1_extraction_ignores_eye_centres():

    with_centres = extract_features(_frame(eye_centres=_centres()))
    without = extract_features(_frame())

    np.testing.assert_array_equal(with_centres, without)
    assert with_centres.shape == (FEATURE_SIZE,)


def test_v2_vector_starts_with_the_v1_vector():

    frame = _frame(eye_centres=_centres())

    v1 = extract_features(frame)
    v2 = extract_features(frame, use_eye_centres=True)

    assert v2.shape == (FEATURE_SIZE_V2,)
    assert v2.dtype == np.float32
    np.testing.assert_array_equal(v2[:FEATURE_SIZE], v1)


def test_v2_appends_the_centre_position_normalized_per_eye():

    # Left eye spans x 0.3-0.4 (corners 362, 263), top/bottom y 0.35-0.45;
    # right eye spans x 0.6-0.7 (corners 133, 33).
    features = extract_features(_frame(eye_centres=_centres(left=(0.34, 0.41), right=(0.66, 0.39))),
                                use_eye_centres=True)

    assert features[20:24] == pytest.approx([0.4, 0.6, 0.6, 0.4], abs=1e-5)


def test_v2_low_confidence_centre_falls_back_to_the_landmark_mean():

    low = EYE_CENTRE_MIN_CONFIDENCE - 0.01
    features = extract_features(_frame(eye_centres=_centres(confidence=low)), use_eye_centres=True)

    np.testing.assert_array_equal(features[20:24], features[0:4])


def test_v2_confidence_exactly_at_the_threshold_is_used():

    features = extract_features(_frame(eye_centres=_centres(confidence=EYE_CENTRE_MIN_CONFIDENCE)),
                                use_eye_centres=True)

    assert features[20:24] == pytest.approx([0.4, 0.6, 0.6, 0.4], abs=1e-5)


def test_v2_falls_back_per_eye():

    centres = _centres()
    centres[1]["confidence"] = 0.0
    features = extract_features(_frame(eye_centres=centres), use_eye_centres=True)

    assert features[20:22] == pytest.approx([0.4, 0.6], abs=1e-5)
    np.testing.assert_array_equal(features[22:24], features[2:4])


def test_v2_without_eye_centres_falls_back_to_the_landmark_mean():

    features = extract_features(_frame(), use_eye_centres=True)

    assert features.shape == (FEATURE_SIZE_V2,)
    np.testing.assert_array_equal(features[20:24], features[0:4])


def test_v2_off_image_centre_falls_back_like_a_low_confidence_one():

    # Landmarks may lie slightly outside the image; a centre there is not trusted.
    features = extract_features(_frame(eye_centres=_centres(left=(-0.1, 0.41))), use_eye_centres=True)

    np.testing.assert_array_equal(features[20:22], features[0:2])


def test_v2_still_returns_none_for_no_face():

    assert extract_features(_frame(nose={"x": 1.2, "y": 0.5}), use_eye_centres=True) is None
    assert extract_features(None, use_eye_centres=True) is None
