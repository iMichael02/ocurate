from passage import Passage
from braille_render import cell_geometry, render_calibration_frame, render_passage_frame, render_result_frame


def test_cell_geometry_divides_canvas_by_grid():

    passage = Passage(["the fox", "runs by"])

    cell_width, line_height = cell_geometry(700, 200, passage)

    assert cell_width == 100
    assert line_height == 100


def test_render_calibration_frame_shape():

    frame = render_calibration_frame(200, 100, (0.5, 0.5))

    assert frame.shape == (100, 200, 3)


def test_render_passage_frame_shape():

    passage = Passage(["ab"])

    frame = render_passage_frame(200, 100, passage)

    assert frame.shape == (100, 200, 3)


def test_render_result_frame_shape():

    result = {
        "cpm": 100.0, "wpm": 20.0, "elapsed_seconds": 5.0,
        "saccades": 3, "regressions": 1, "skipped_characters": 0,
    }

    frame = render_result_frame(400, 300, result)

    assert frame.shape == (300, 400, 3)
