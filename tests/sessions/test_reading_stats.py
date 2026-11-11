from types import SimpleNamespace

import numpy as np

from app.sessions.reading_stats import REPORT_EVERY_MS, ReadingStats

FIRST_CELL = SimpleNamespace(row=0, col=0, x=0.0, y=0.0, w=0.5, h=0.5)


def make_stats():

    return ReadingStats(FIRST_CELL)


def test_a_new_session_reports_zeros_and_no_distance():

    fields = make_stats().fields()

    assert fields["frames"] == 0
    assert fields["reading_started"] is False
    assert fields["nearest_to_first_cell"] is None
    assert fields["reading_seconds"] == 0.0


def test_frames_and_missing_faces_are_counted():

    stats = make_stats()
    stats.frame(1000.0)
    stats.frame(1033.0)
    stats.no_face()

    fields = stats.fields()

    assert fields["frames"] == 2
    assert fields["no_face_frames"] == 1
    assert fields["reading_seconds"] == 0.0


def test_reading_seconds_is_the_browser_time_between_first_and_last_frame():

    stats = make_stats()
    stats.frame(1000.0)
    stats.frame(3500.0)

    assert stats.fields()["reading_seconds"] == 2.5


def test_gaze_outside_the_viewport_is_counted():

    stats = make_stats()
    stats.gaze(0.5, 0.5)
    stats.gaze(1.2, 0.5)
    stats.gaze(0.5, -0.1)

    assert stats.fields()["gaze_off_screen_frames"] == 2


def test_the_nearest_fixation_to_the_first_cell_is_kept_until_reading_starts():

    stats = make_stats()
    stats.fixation(0.5, 0.9, (1, 1))   # 0.4 below the first Cell
    stats.fixation(0.7, 0.25, None)    # 0.2 to its right
    stats.fixation(0.9, 0.9, (1, 1))

    assert stats.fields()["nearest_to_first_cell"] == 0.2

    stats.started = True
    stats.fixation(0.5, 0.25, (0, 0))  # inside, but reading has started

    assert stats.fields()["nearest_to_first_cell"] == 0.2


def test_a_steady_stare_counts_every_frame_but_only_one_cell():

    stats = make_stats()
    for _ in range(50):
        stats.fixation(0.25, 0.75, (1, 0))

    fields = stats.fields()

    assert fields["fixation_frames"] == 50
    assert fields["cells_fixated"] == 1
    assert fields["cells_fixated_before_start"] == 1


def test_a_fixation_off_every_cell_is_counted_separately():

    stats = make_stats()
    stats.fixation(0.7, 0.25, None)
    stats.fixation(0.7, 0.25, None)

    fields = stats.fields()

    assert fields["fixation_frames"] == 2
    assert fields["off_cell_frames"] == 2
    assert fields["cells_fixated"] == 0


def test_moving_between_cells_counts_each_change():

    stats = make_stats()
    for cell in [(0, 0), (0, 0), (0, 1), (0, 0)]:
        stats.fixation(0.25, 0.25, cell)

    assert stats.fields()["cells_fixated"] == 3


def test_a_fixation_on_the_first_cell_is_not_counted_as_before_start():

    stats = make_stats()
    stats.fixation(0.25, 0.25, (0, 0))

    assert stats.fields()["cells_fixated_before_start"] == 0


def test_a_report_is_due_every_few_seconds_of_browser_time():

    stats = make_stats()
    stats.frame(1000.0)

    assert not stats.report_due(1000.0 + REPORT_EVERY_MS - 1)
    assert stats.report_due(1000.0 + REPORT_EVERY_MS)
    assert not stats.report_due(1000.0 + REPORT_EVERY_MS + 1)
    assert stats.report_due(1000.0 + 2 * REPORT_EVERY_MS)


def test_no_report_is_due_before_the_first_frame():

    assert not make_stats().report_due(99999.0)


def z_with(value, index, size=24):

    z = np.zeros(size)
    z[index] = value

    return z


def test_no_feature_scale_reports_zeros():

    fields = make_stats().fields()

    assert fields["max_abs_z"] == 0.0
    assert fields["mean_max_abs_z"] == 0.0
    assert fields["frames_out_of_range"] == 0
    assert fields["worst_feature_group"] is None


def test_frames_inside_the_calibration_range_are_not_out_of_range():

    stats = make_stats()
    stats.feature_scale(z_with(2.9, 3))
    stats.feature_scale(z_with(-2.0, 16))

    fields = stats.fields()

    assert fields["frames_out_of_range"] == 0
    assert fields["worst_feature_group"] is None
    assert fields["max_abs_z"] == 2.9


def test_the_worst_feature_group_is_the_one_most_often_furthest_out():

    stats = make_stats()
    for _ in range(3):
        stats.feature_scale(z_with(-40.0, 16))   # head_position
    stats.feature_scale(z_with(5.0, 2))          # iris

    fields = stats.fields()

    assert fields["frames_out_of_range"] == 4
    assert fields["worst_feature_group"] == "head_position"
    assert fields["max_abs_z"] == 40.0


def test_the_mean_of_each_frames_largest_value_is_reported():

    stats = make_stats()
    stats.feature_scale(z_with(2.0, 0))
    stats.feature_scale(z_with(-4.0, 20))

    assert stats.fields()["mean_max_abs_z"] == 3.0


def test_only_the_group_of_the_largest_value_in_a_frame_counts():

    stats = make_stats()
    z = z_with(10.0, 6)                          # head_rotation
    z[22] = 50.0                                 # eye_centre, larger
    stats.feature_scale(z)

    assert stats.fields()["worst_feature_group"] == "eye_centre"


def test_with_the_model_columns_the_group_comes_from_the_full_vector_position():

    stats = make_stats()
    columns = [0, 1, 2, 3, 4, 5, 20, 21, 22, 23]       # what the model uses
    z = np.zeros(10)
    z[6] = 9.0                                          # column 20 of the full vector: an eye centre
    stats.feature_scale(z, columns)

    assert stats.fields()["worst_feature_group"] == "eye_centre"

    z = np.zeros(10)
    z[2] = 12.0                                         # column 2: an iris value
    stats.feature_scale(z, columns)
    stats.feature_scale(z, columns)

    assert stats.fields()["worst_feature_group"] == "iris"
