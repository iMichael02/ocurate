import numpy as np
import pytest

from types import SimpleNamespace

from app.analysis.calibration import (CALIBRATION_POINTS, MIN_USABLE_POINTS, Calibration, held_out_residuals,
                                      mean_error_px, target_index)
from app.analysis.gaze_model import GazeModel


def test_calibration_points_are_a_4x4_grid_from_0_1_to_0_9_row_major():

    axis = [0.1, 0.1 + 0.8 / 3, 0.1 + 1.6 / 3, 0.9]

    assert len(CALIBRATION_POINTS) == 16

    for index, (x, y) in enumerate(CALIBRATION_POINTS):
        assert x == pytest.approx(axis[index % 4])
        assert y == pytest.approx(axis[index // 4])


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


def test_frames_that_straddle_each_target_still_recover_the_target():

    calibration = Calibration()

    # Frames straddle each position, so the model must still line up with it.
    feed(calibration, range(16), frames_per_point=4, noise=0.05)

    model = calibration.finish().model

    for x, y in CALIBRATION_POINTS:
        px, py = model.predict(np.array([[x, y]]))[0]
        assert px == pytest.approx(x, abs=0.05)
        assert py == pytest.approx(y, abs=0.05)


def test_the_model_is_fitted_on_every_frame_not_on_one_average_per_target(monkeypatch):

    seen = {}
    train = GazeModel.train

    def spy(self, X, y):
        # The first fit is the Session's model; the second only measures the held-out error.
        seen.setdefault("X", np.array(X))
        seen.setdefault("y", np.array(y))
        train(self, X, y)

    monkeypatch.setattr("app.analysis.gaze_model.GazeModel.train", spy)
    calibration = Calibration()

    feed(calibration, range(16), frames_per_point=3)
    calibration.finish()

    assert seen["X"].shape == (48, 2)
    assert seen["y"].shape == (48, 2)
    # Each frame is labelled with its own target.
    assert [tuple(row) for row in seen["y"][:3]] == [CALIBRATION_POINTS[0]] * 3


def test_a_target_with_fewer_usable_frames_contributes_fewer_rows(monkeypatch):

    seen = {}
    train = GazeModel.train

    def spy(self, X, y):
        seen.setdefault("rows", len(X))
        train(self, X, y)

    monkeypatch.setattr("app.analysis.gaze_model.GazeModel.train", spy)
    calibration = Calibration()

    feed(calibration, range(15), frames_per_point=4)
    feed(calibration, [15], frames_per_point=1)
    calibration.finish()

    assert seen["rows"] == 15 * 4 + 1


def test_a_jittery_feature_does_not_wreck_predictions_on_single_frames():
    """The reason for fitting on frames: a feature with big per-frame jitter but a tiny
    spread between targets must not be amplified when the model sees one noisy frame."""

    rng = np.random.default_rng(0)
    calibration = Calibration()

    def features(x, y):
        clean = [x, y]                                              # tracks the target
        jittery = rng.normal(0.0, 0.05, 4) + 0.01 * np.array([x, y, x, y])   # mostly noise
        return np.concatenate([clean + rng.normal(0, 0.01, 2), jittery])

    for x, y in CALIBRATION_POINTS:
        for _ in range(20):
            calibration.add_frame((x, y), features(x, y))

    model = calibration.finish().model

    errors = []
    for x, y in CALIBRATION_POINTS:
        frames = np.array([features(x, y) for _ in range(30)])
        errors.append(np.abs(model.predict(frames) - [x, y]).mean())

    assert np.mean(errors) < 0.03


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


def test_target_index_finds_the_nearest_point():

    for index, (x, y) in enumerate(CALIBRATION_POINTS):
        assert target_index(SimpleNamespace(x=x, y=y)) == index
        assert target_index(SimpleNamespace(x=x + 0.01, y=y - 0.01)) == index


def test_target_index_ignores_a_point_off_the_grid():

    assert target_index(SimpleNamespace(x=0.5, y=0.5)) is None


def test_progress_marks_earlier_targets_ok_or_skipped_and_the_rest_pending():

    calibration = Calibration()
    calibration.add_frame(CALIBRATION_POINTS[0], np.array([1.0]))
    calibration.add_frame(CALIBRATION_POINTS[2], np.array([1.0]))

    states = [(s.state, s.samples) for s in calibration.progress(2)]

    assert states[0] == ("ok", 1)
    assert states[1] == ("skipped", 0)
    assert states[2] == ("collecting", 1)
    assert all(state == ("pending", 0) for state in states[3:])


# --- held-out calibration error -------------------------------------------------

def feed_with_tail(calibration, frames_per_point, tail, tail_shift):
    """Every target gets frames whose features are its own position; the last
    `tail` frames of each are shifted right by `tail_shift`."""

    for x, y in CALIBRATION_POINTS:
        for n in range(frames_per_point):
            shift = tail_shift if n >= frames_per_point - tail else 0.0
            calibration.add_frame((x, y), np.array([x + shift, y]))


def test_the_error_is_measured_on_the_last_quarter_of_each_target_held_out(monkeypatch):

    rows = []
    train = GazeModel.train

    def spy(self, X, y):
        rows.append(len(X))
        train(self, X, y)

    monkeypatch.setattr("app.analysis.gaze_model.GazeModel.train", spy)
    calibration = Calibration()

    feed_with_tail(calibration, frames_per_point=8, tail=2, tail_shift=0.05)
    result = calibration.finish()

    # The Session's model sees every frame; the measuring model never sees the 2 held-out frames per target.
    assert rows == [16 * 8, 16 * 6]
    assert result.residuals.shape == (16 * 2, 2)
    # The held-out frames look 0.05 to the right, and only an unseen frame shows that.
    assert np.mean(result.residuals[:, 0]) == pytest.approx(0.05, abs=0.01)
    assert np.mean(np.abs(result.residuals[:, 1])) < 0.01


def test_the_held_out_error_is_larger_than_the_training_error_would_be():

    calibration = Calibration()
    feed_with_tail(calibration, frames_per_point=8, tail=2, tail_shift=0.05)
    result = calibration.finish()

    X = np.array([[x, y] for x, y in CALIBRATION_POINTS for _ in range(8)])
    X[np.tile(np.arange(8) >= 6, 16), 0] += 0.05
    y = np.repeat(np.array(CALIBRATION_POINTS), 8, axis=0)
    training_error = np.mean(np.linalg.norm(result.model.predict(X) - y, axis=1))

    assert np.mean(np.linalg.norm(result.residuals, axis=1)) > training_error


def test_measuring_the_error_does_not_change_the_sessions_model():

    with_error = Calibration()
    feed_with_tail(with_error, frames_per_point=8, tail=2, tail_shift=0.05)
    model = with_error.finish().model

    X = np.array([[x, y] for x, y in CALIBRATION_POINTS for _ in range(8)])
    X[np.tile(np.arange(8) >= 6, 16), 0] += 0.05
    y = np.repeat(np.array(CALIBRATION_POINTS), 8, axis=0)
    reference = GazeModel()
    reference.train(X, y)

    probe = np.array([[0.3, 0.7], [0.8, 0.2]])
    assert np.allclose(model.predict(probe), reference.predict(probe))


def test_a_target_with_too_few_frames_stays_in_training_and_holds_nothing_out():

    samples = {index: [np.array(point, dtype=float)] * (2 if index == 0 else 4)
               for index, point in enumerate(CALIBRATION_POINTS)}

    residuals = held_out_residuals(samples)

    assert residuals.shape == (15, 2)


def test_no_error_when_too_few_targets_can_hold_frames_out():

    calibration = Calibration()
    feed(calibration, range(16), frames_per_point=2)

    result = calibration.finish()

    assert result.outcome == "ready"
    assert result.residuals is None


def test_the_error_needs_held_out_frames_from_at_least_12_targets():

    samples = {index: [np.array(point, dtype=float)] * (3 if index < MIN_USABLE_POINTS else 2)
               for index, point in enumerate(CALIBRATION_POINTS)}

    assert held_out_residuals(samples).shape == (MIN_USABLE_POINTS, 2)

    samples[0] = samples[0][:2]

    assert held_out_residuals(samples) is None


def test_a_failed_calibration_has_no_error():

    calibration = Calibration()
    feed(calibration, range(8), frames_per_point=8)

    result = calibration.finish()

    assert result.outcome == "failed"
    assert result.residuals is None


def test_the_mean_error_in_px_scales_each_axis_by_its_own_viewport_size():

    residuals = np.array([[0.1, 0.0], [0.0, 0.1], [0.03, 0.04]])

    # 100 px across, 50 px down, and (30, 20) px -> about 36.06 px.
    assert mean_error_px(residuals, 1000, 500) == pytest.approx((100 + 50 + np.hypot(30, 20)) / 3)


def test_a_failure_while_measuring_the_error_does_not_fail_the_calibration(monkeypatch):

    train = GazeModel.train
    fits = []

    def spy(self, X, y):
        fits.append(1)
        if len(fits) == 2:
            raise np.linalg.LinAlgError("singular")
        train(self, X, y)

    monkeypatch.setattr("app.analysis.gaze_model.GazeModel.train", spy)
    calibration = Calibration()
    feed_with_tail(calibration, frames_per_point=8, tail=2, tail_shift=0.05)

    result = calibration.finish()

    assert result.outcome == "ready"
    assert result.model is not None
    assert result.residuals is None
