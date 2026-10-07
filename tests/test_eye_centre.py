import numpy as np
import pytest

from eye_centre import CROP_WIDTH, CROP_HEIGHT, locate_eye_centre


def _eye(cx, cy, radius=4.0, dark=30.0, skin=200.0, noise=0.0, seed=0):
    """A synthetic grayscale eye crop (rows x cols = CROP_HEIGHT x CROP_WIDTH):
    a dark disc (iris + pupil) of `radius` px centred at pixel (cx, cy) on a
    bright background."""

    ys, xs = np.mgrid[0:CROP_HEIGHT, 0:CROP_WIDTH]
    distance = np.hypot(xs - cx, ys - cy)
    image = np.where(distance <= radius, dark, skin).astype(np.float64)

    # soften the edge a little, as a real camera would
    image = (image + np.roll(image, 1, axis=0) + np.roll(image, -1, axis=0)
             + np.roll(image, 1, axis=1) + np.roll(image, -1, axis=1)) / 5.0

    if noise:
        image += np.random.default_rng(seed).normal(0, noise, image.shape)

    return np.clip(image, 0, 255)


def _centre_in_pixels(result):

    x, y, _ = result
    return x * CROP_WIDTH, y * CROP_HEIGHT


def test_crop_size_is_the_documented_one():

    assert (CROP_WIDTH, CROP_HEIGHT) == (40, 20)


@pytest.mark.parametrize("cx, cy", [(20, 10), (14, 9), (27, 11), (20, 6), (12, 12)])
def test_finds_the_centre_of_a_dark_disc(cx, cy):

    x, y = _centre_in_pixels(locate_eye_centre(_eye(cx, cy)))

    assert x == pytest.approx(cx + 0.5, abs=1.0)
    assert y == pytest.approx(cy + 0.5, abs=1.0)


def test_tolerates_sensor_noise():

    x, y = _centre_in_pixels(locate_eye_centre(_eye(17, 9, noise=6.0)))

    assert x == pytest.approx(17.5, abs=1.5)
    assert y == pytest.approx(9.5, abs=1.5)


def test_result_is_normalized_to_the_crop():

    x, y, confidence = locate_eye_centre(_eye(20, 10))

    assert 0.0 <= x <= 1.0
    assert 0.0 <= y <= 1.0
    assert 0.0 <= confidence <= 1.0


def test_a_clear_disc_is_confident():

    assert locate_eye_centre(_eye(20, 10))[2] >= 0.5


def test_a_flat_crop_has_no_confidence():

    flat = np.full((CROP_HEIGHT, CROP_WIDTH), 120.0)

    assert locate_eye_centre(flat)[2] == 0.0


def test_a_uniform_noise_crop_is_not_confident():

    noise = np.random.default_rng(1).normal(120, 5, (CROP_HEIGHT, CROP_WIDTH))

    assert locate_eye_centre(noise)[2] < 0.5


def test_rejects_a_crop_of_the_wrong_shape():

    with pytest.raises(ValueError):
        locate_eye_centre(np.zeros((10, 10)))


def test_rejects_non_finite_pixels():

    crop = _eye(20, 10)
    crop[3, 3] = np.nan

    with pytest.raises(ValueError):
        locate_eye_centre(crop)


# --- vectors the browser implementation must reproduce ---------------------------

import json
from pathlib import Path

GOLDEN = json.loads((Path(__file__).parent / "golden" / "eye_centre.json").read_text())


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=[c["name"] for c in GOLDEN["cases"]])
def test_matches_the_golden_vectors(case):

    x, y, confidence = locate_eye_centre(np.array(case["crop"], dtype=np.float64))

    assert x == pytest.approx(case["expected"]["x"], abs=1e-6)
    assert y == pytest.approx(case["expected"]["y"], abs=1e-6)
    assert confidence == pytest.approx(case["expected"]["confidence"], abs=1e-3)
