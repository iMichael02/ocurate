import numpy as np
import pytest

from calibration import Calibration, CALIBRATION_POINTS, gaze_to_braille_cell


def test_calibration_points_are_a_4x4_grid_from_0_1_to_0_9_row_major():

    axis = [0.1, 0.1 + 0.8 / 3, 0.1 + 1.6 / 3, 0.9]

    assert len(CALIBRATION_POINTS) == 16

    for index, (x, y) in enumerate(CALIBRATION_POINTS):
        assert x == pytest.approx(axis[index % 4])
        assert y == pytest.approx(axis[index // 4])


def test_maps_gaze_to_expected_cell():

    row, column = gaze_to_braille_cell(
        gaze_x=0.5,
        gaze_y=0.5,
        screen_width=500,
        screen_height=300,
        cell_width=100,
        line_height=100,
        num_rows=3,
        num_columns=5,
    )

    assert (row, column) == (1, 2)


def test_clamps_column_at_right_edge():

    row, column = gaze_to_braille_cell(
        gaze_x=1.0,
        gaze_y=0.0,
        screen_width=500,
        screen_height=300,
        cell_width=100,
        line_height=100,
        num_rows=3,
        num_columns=5,
    )

    assert column == 4


def test_clamps_row_at_bottom_edge():

    row, column = gaze_to_braille_cell(
        gaze_x=0.0,
        gaze_y=1.0,
        screen_width=500,
        screen_height=300,
        cell_width=100,
        line_height=100,
        num_rows=3,
        num_columns=5,
    )

    assert row == 2


def test_clamps_negative_gaze_to_first_cell():

    row, column = gaze_to_braille_cell(
        gaze_x=-0.5,
        gaze_y=-0.5,
        screen_width=500,
        screen_height=300,
        cell_width=100,
        line_height=100,
        num_rows=3,
        num_columns=5,
    )

    assert (row, column) == (0, 0)


def feed(calibration, indices, frames_per_point=3, noise=0.0):
    """Gives each target in `indices` frames whose features are the target's
    own position, alternately shifted by +noise and -noise (so the mean per
    target is the position itself)."""

    for index in indices:
        x, y = CALIBRATION_POINTS[index]
        for n in range(frames_per_point):
            shift = noise if n % 2 == 0 else -noise
            calibration.add_frame((x, y), np.array([x + shift, y - shift]))


def test_all_targets_seen_is_ready_with_per_target_status():

    calibration = Calibration()

    feed(calibration, range(16), frames_per_point=3)

    result = calibration.finish()

    assert result.outcome == "ready"
    assert result.reason is None
    assert [p.index for p in result.points] == list(range(16))
    assert all(p.state == "ok" and p.samples == 3 for p in result.points)
    assert result.model is not None


def test_a_target_is_the_mean_of_its_frames():

    calibration = Calibration()

    # Frames straddle each position, so only the mean lines up with it.
    feed(calibration, range(16), frames_per_point=4, noise=0.05)

    model = calibration.finish().model

    for x, y in CALIBRATION_POINTS:
        px, py = model.predict(np.array([[x, y]]))[0]
        assert px == pytest.approx(x, abs=0.05)
        assert py == pytest.approx(y, abs=0.05)


def test_frames_without_a_face_do_not_count():

    calibration = Calibration()

    feed(calibration, range(16), frames_per_point=2)
    for _ in range(5):
        calibration.add_frame(CALIBRATION_POINTS[0], None)

    assert calibration.finish().points[0].samples == 2


def test_a_target_with_no_usable_frames_is_skipped():

    calibration = Calibration()

    feed(calibration, [i for i in range(16) if i != 5])
    calibration.add_frame(CALIBRATION_POINTS[5], None)

    point = calibration.finish().points[5]

    assert (point.state, point.samples) == ("skipped", 0)


def test_twelve_usable_targets_is_ready_eleven_is_too_few():

    # Drop 4 targets that leave every row and column covered: a 12-point
    # result is ready, dropping one more gives 11 and fails.
    twelve = [i for i in range(16) if i not in (0, 5, 10, 15)]
    eleven = [i for i in twelve if i != 1]

    ready = Calibration()
    feed(ready, twelve)
    assert ready.finish().outcome == "ready"

    failed = Calibration()
    feed(failed, eleven)
    result = failed.finish()
    assert (result.outcome, result.reason) == ("failed", "too_few_points")


def test_a_missing_full_row_fails_even_with_twelve_usable_targets():

    calibration = Calibration()
    feed(calibration, range(4, 16))  # row 0 never seen: 12 usable

    result = calibration.finish()

    assert (result.outcome, result.reason) == ("failed", "missing_row_or_column")


def test_a_missing_full_column_fails_even_with_twelve_usable_targets():

    calibration = Calibration()
    feed(calibration, [i for i in range(16) if i % 4 != 2])  # column 2 never seen

    result = calibration.finish()

    assert (result.outcome, result.reason) == ("failed", "missing_row_or_column")


def test_no_model_is_fitted_on_a_failed_calibration():

    calibration = Calibration()
    feed(calibration, range(4))

    result = calibration.finish()

    assert result.outcome == "failed"
    assert result.model is None
    assert [p.samples for p in result.points[:4]] == [3, 3, 3, 3]


def test_restart_discards_the_failed_attempts_samples():

    calibration = Calibration()
    feed(calibration, range(4))
    assert calibration.finish().outcome == "failed"

    calibration.restart()

    assert all(p.samples == 0 and p.state == "skipped" for p in calibration.finish().points)

    feed(calibration, range(16), frames_per_point=2)
    result = calibration.finish()
    assert result.outcome == "ready"
    assert all(p.samples == 2 for p in result.points)
