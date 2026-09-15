CALIBRATION_POINTS = [
    (0.1, 0.1),
    (0.5, 0.1),
    (0.9, 0.1),

    (0.1, 0.5),
    (0.5, 0.5),
    (0.9, 0.5),

    (0.1, 0.9),
    (0.5, 0.9),
    (0.9, 0.9)
]

def gaze_to_braille_cell(
    gaze_x,
    gaze_y,
    screen_width,
    screen_height,
    cell_width,
    line_height,
    num_rows,
    num_columns
):

    px = gaze_x * screen_width
    py = gaze_y * screen_height

    column = int(px / cell_width)

    row = int(py / line_height)

    column = min(max(column, 0), num_columns - 1)
    row = min(max(row, 0), num_rows - 1)

    return row, column