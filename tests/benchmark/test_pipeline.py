import numpy as np
import pytest

from app.analysis.calibration import CALIBRATION_POINTS, Calibration
from app.analysis.eye_features import extract_features, model_columns, FEATURE_SIZE
from app.analysis.gaze_model import GazeModel
from benchmark.pipeline import PipelineConfig, replay
from benchmark.synthetic import generate_learner

# One small learner shared by the tests (seconds to replay).
RECORDING = generate_learner("pipeline-test", seed=1)


def test_baseline_replay_calibrates_and_scores_settled_frames():

    result = replay(RECORDING)

    assert result.calibrated
    assert result.frames == len(RECORDING.reading)
    assert result.errors_fraction and len(result.errors_fraction) == len(result.errors_degrees)
    assert all(e >= 0 for e in result.errors_fraction)
    assert result.cell_hits                       # the simulated Learner dwells long enough to fixate


def test_baseline_model_is_exactly_the_one_the_service_fits():
    """The benchmark must measure the shipped model, so the baseline fit must equal a plain Calibration."""

    columns = model_columns(FEATURE_SIZE)
    shipped = Calibration()
    for target, frame in RECORDING.calibration:
        features = extract_features(frame)
        if features is not None:
            shipped.add_frame(target, features[columns])
    model = shipped.finish().model

    benchmark_model = GazeModel()
    X, y = [], []
    for target, frame in RECORDING.calibration:
        features = extract_features(frame)
        if features is not None:
            X.append(features[columns])
            y.append(target)
    benchmark_model.train(np.array(X), np.array(y))

    probe = np.array(X[:5])
    assert np.allclose(model.predict(probe), benchmark_model.predict(probe))


def test_calibration_that_fails_the_service_rule_is_reported_not_scored():

    recording = generate_learner("pipeline-test", seed=1)
    keep = [(t, f) for t, f in recording.calibration if t != CALIBRATION_POINTS[0]]   # one target never seen... 15 of 16
    keep = [(t, f) for t, f in keep if t not in CALIBRATION_POINTS[1:5]]              # a whole row missing too
    recording.calibration = keep

    result = replay(recording)

    assert not result.calibrated
    assert result.failure_reason in ("too_few_points", "missing_row_or_column")
    assert result.errors_fraction == []


def test_frames_without_a_face_are_counted_and_skipped():

    recording = generate_learner("pipeline-test", seed=1)
    recording.reading = [(truth, None) for truth, _ in recording.reading[:20]] + recording.reading[20:]

    result = replay(recording)

    assert result.no_face >= 20


def test_each_candidate_switch_changes_the_model_it_builds():

    polynomial = replay(RECORDING, PipelineConfig(degree=2))
    baseline = replay(RECORDING)

    assert polynomial.errors_fraction != baseline.errors_fraction


def test_v2_config_uses_the_eye_centres_and_still_runs():

    result = replay(RECORDING, PipelineConfig(use_eye_centres=True))

    assert result.calibrated


def test_dropping_out_of_range_frames_never_scores_them():

    config = PipelineConfig(out_of_range="drop", z_limit=0.01)      # nearly every frame is "out of range"

    result = replay(RECORDING, config)

    assert result.rejected > 0
    assert len(result.errors_fraction) < len(replay(RECORDING).errors_fraction)


def test_blink_rejection_drops_frames_in_calibration_and_reading():

    result = replay(RECORDING, PipelineConfig(reject_blinks=True))

    assert result.calibrated
    assert result.rejected > 0


def test_clipping_keeps_predictions_on_the_screen():

    model = GazeModel(clip=True)
    model.train(np.array([[0.0], [1.0]]), np.array([[0.0, 0.0], [1.0, 1.0]]))

    assert model.predict(np.array([[5.0]]))[0].tolist() == [1.0, 1.0]
    assert model.predict(np.array([[-5.0]]))[0].tolist() == [0.0, 0.0]


def test_the_shipped_model_does_not_clip():

    model = GazeModel()
    model.train(np.array([[0.0], [1.0]]), np.array([[0.0, 0.0], [1.0, 1.0]]))

    assert model.predict(np.array([[5.0]]))[0][0] > 1.0


def test_unknown_regressor_is_refused():

    with pytest.raises(ValueError):
        GazeModel(regressor="forest")


def test_polynomial_and_kernel_models_keep_standardize_working():

    X = np.random.default_rng(0).normal(size=(40, 3))
    y = np.random.default_rng(1).uniform(size=(40, 2))

    for model in (GazeModel(degree=2), GazeModel(regressor="kernel")):
        model.train(X, y)
        assert model.standardize(X).shape == X.shape
