import math

import pytest

from benchmark import run
from benchmark.candidates import BASELINE
from benchmark.pipeline import PipelineConfig
from benchmark.recording import from_json, load_directory, save, to_json
from benchmark.synthetic import generate_cohort, generate_learner


def test_synthetic_learners_are_deterministic_for_a_seed_and_differ_between_seeds():

    a = to_json(generate_learner("x", seed=3))
    b = to_json(generate_learner("x", seed=3))
    c = to_json(generate_learner("x", seed=4))

    assert a == b
    assert a != c


def test_synthetic_recordings_are_marked_so_reports_cannot_mix_them_with_real_ones():

    assert generate_learner("x").synthetic


def test_recording_round_trips_through_json_and_files(tmp_path):

    recording = generate_learner("round-trip", {"lighting": "dim"}, seed=2)
    save(recording, tmp_path / "a.json")

    loaded = load_directory(tmp_path)[0]

    assert to_json(loaded) == to_json(from_json(to_json(recording)))
    assert loaded.learner == "round-trip"
    assert loaded.conditions["lighting"] == "dim"
    assert len(loaded.reading) == len(recording.reading)


def test_unknown_recording_format_is_refused():

    data = to_json(generate_learner("x"))
    data["format"] = 99

    with pytest.raises(ValueError):
        from_json(data)


def test_split_is_stable_and_never_puts_a_learner_on_both_sides():

    recordings = generate_cohort(2)

    dev, test = run.split_learners(recordings)
    dev_again, test_again = run.split_learners(list(reversed(recordings)))

    assert {r.learner for r in dev}.isdisjoint({r.learner for r in test})
    assert len(dev) + len(test) == len(recordings)
    assert {r.learner for r in test} == {r.learner for r in test_again}
    assert {r.learner for r in dev} == {r.learner for r in dev_again}


def test_adding_a_learner_does_not_move_the_others_across_the_split():

    recordings = generate_cohort(2)
    before = {r.learner for r in run.split_learners(recordings)[1]}

    extra = generate_learner("a-new-learner")
    after = {r.learner for r in run.split_learners(recordings + [extra])[1]}

    assert before <= after


def _entry(cell_accuracy, groups=None, calibration=1.0, frame_ms=1.0):

    def aggregate(accuracy, learners=10):
        return {"cell_accuracy": accuracy, "calibration_success": calibration, "frame_ms_median": frame_ms,
                "learners": learners}

    return {"overall": aggregate(cell_accuracy),
            "groups": {name: aggregate(a, n) for name, (a, n) in (groups or {}).items()}}


def test_a_clear_gain_with_no_subgroup_worse_is_adopted():

    baseline = _entry(0.70, {"lighting=dim": (0.5, 5)})
    candidate = _entry(0.80, {"lighting=dim": (0.6, 5)})

    assert run.compare(baseline, candidate)["adopt"]


def test_a_gain_below_the_threshold_is_not_adopted():

    decision = run.compare(_entry(0.70), _entry(0.71))

    assert not decision["adopt"]
    assert any("gain" in r for r in decision["reasons"])


def test_a_gain_that_hurts_one_subgroup_is_not_adopted():

    baseline = _entry(0.70, {"glasses=yes": (0.6, 5)})
    candidate = _entry(0.85, {"glasses=yes": (0.4, 5)})

    decision = run.compare(baseline, candidate)

    assert not decision["adopt"]
    assert "glasses=yes" in decision["reasons"][0]


def test_a_tiny_subgroup_cannot_veto():

    baseline = _entry(0.70, {"glasses=yes": (0.6, 2)})
    candidate = _entry(0.85, {"glasses=yes": (0.1, 2)})

    assert run.compare(baseline, candidate)["adopt"]


def test_a_drop_in_calibration_success_or_a_slow_frame_blocks_adoption():

    assert not run.compare(_entry(0.7), _entry(0.9, calibration=0.9))["adopt"]
    assert not run.compare(_entry(0.7), _entry(0.9, frame_ms=40.0))["adopt"]


def test_report_on_a_small_synthetic_cohort_labels_itself_and_covers_the_candidates():

    recordings = generate_cohort(1)[:6]
    candidates = {"alpha-10": BASELINE.with_(alpha=10.0), "v2": PipelineConfig(use_eye_centres=True)}

    data = run.report(recordings, candidates)
    text = run.format_report(data)

    assert data["synthetic"]
    assert set(data["candidates"]) == {"alpha-10", "v2"}
    assert text.startswith("SYNTHETIC DATA")
    assert "not a decision" in text
    assert not math.isnan(data["baseline"]["overall"]["calibration_success"])


def test_cli_needs_two_recordings(tmp_path, capsys):

    save(generate_learner("only-one"), tmp_path / "one.json")

    assert run.main(["--data", str(tmp_path)]) == 1


def test_several_sessions_of_one_learner_count_as_one_learner_and_stay_on_one_side_of_the_split():

    from dataclasses import replace

    sessions = [replace(generate_learner("same", seed=s), learner="same") for s in range(4)]
    others = generate_cohort(1)

    dev, test = run.split_learners(sessions + others)
    results = run.evaluate(sessions, BASELINE)

    assert {r.learner for r in dev}.isdisjoint({r.learner for r in test})
    assert len({r.learner for r in sessions if r in dev}) <= 1 and len({r.learner for r in sessions if r in test}) <= 1
    assert run.aggregate(results)["learners"] == 1


def test_with_no_held_out_learner_the_decision_says_it_cannot_decide():

    nothing = {"overall": {"cell_accuracy": math.nan, "calibration_success": math.nan, "frame_ms_median": math.nan},
               "groups": {}}

    decision = run.compare(nothing, nothing)

    assert not decision["adopt"]
    assert "cannot decide" in decision["reasons"][0]
