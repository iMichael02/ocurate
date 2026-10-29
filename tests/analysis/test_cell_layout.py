import pytest

from app.analysis.cell_layout import cell_at
from app.schemas.protocol import CellRect


def grid(rows=2, columns=3, gap=0.0):
    """Cells of 0.1 x 0.1 starting at (0.2, 0.2), `gap` apart."""

    return [CellRect(row=r, col=c, x=0.2 + c * (0.1 + gap), y=0.2 + r * (0.1 + gap), w=0.1, h=0.1)
            for r in range(rows) for c in range(columns)]


@pytest.mark.parametrize("x, y, expected", [
    (0.25, 0.25, (0, 0)),
    (0.45, 0.25, (0, 2)),
    (0.35, 0.35, (1, 1)),
])
def test_a_point_inside_a_rectangle_is_that_cell(x, y, expected):

    assert cell_at(grid(), x, y) == expected


def test_a_point_in_the_gap_goes_to_the_nearest_cell():

    cells = grid(gap=0.01)

    assert cell_at(cells, 0.305, 0.25) in {(0, 0), (0, 1)}


def test_a_point_just_outside_the_passage_goes_to_the_nearest_cell():

    assert cell_at(grid(), 0.19, 0.25) == (0, 0)


def test_a_point_far_from_every_cell_is_on_no_cell():

    assert cell_at(grid(), 0.9, 0.9) is None


def test_the_reported_layout_is_used_not_a_uniform_grid():

    cells = [CellRect(row=0, col=0, x=0.0, y=0.0, w=0.9, h=1.0),
             CellRect(row=0, col=1, x=0.9, y=0.0, w=0.1, h=1.0)]

    assert cell_at(cells, 0.5, 0.5) == (0, 0)
    assert cell_at(cells, 0.95, 0.5) == (0, 1)
