from fixation_detector import FixationDetector


def test_no_fixation_reported_before_min_duration():

    detector = FixationDetector(max_dispersion=0.03, min_duration=0.15)

    assert detector.update([0.5, 0.5], timestamp=0.0) is None
    assert detector.update([0.5, 0.5], timestamp=0.1) is None


def test_fixation_reported_once_duration_and_dispersion_conditions_met():

    detector = FixationDetector(max_dispersion=0.03, min_duration=0.15)

    detector.update([0.5, 0.5], timestamp=0.0)
    detector.update([0.51, 0.5], timestamp=0.1)
    fixation = detector.update([0.5, 0.51], timestamp=0.2)

    assert fixation is not None
    assert fixation["duration"] >= 0.15


def test_large_movement_resets_the_window():

    detector = FixationDetector(max_dispersion=0.03, min_duration=0.15)

    detector.update([0.1, 0.1], timestamp=0.0)
    result = detector.update([0.9, 0.9], timestamp=0.1)

    assert result is None
    assert len(detector.samples) == 1


def test_a_tracking_gap_does_not_produce_a_fixation_spanning_dead_time():

    detector = FixationDetector(max_dispersion=0.03, min_duration=0.15, max_gap=0.5)

    detector.update([0.5, 0.5], timestamp=0.0)

    # tracking drops out for 2 seconds, then resumes at roughly the same spot
    result = detector.update([0.5, 0.5], timestamp=2.0)

    assert result is None
    assert len(detector.samples) == 1
