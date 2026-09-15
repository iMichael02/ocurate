from calibration import gaze_to_braille_cell, CALIBRATION_POINTS


def test_nine_calibration_points():

    assert len(CALIBRATION_POINTS) == 9


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
