def distance_to_rect(cell, x, y):
    """How far (x, y) is from the rectangle; 0 inside it."""

    dx = max(cell.x - x, 0.0, x - (cell.x + cell.w))
    dy = max(cell.y - y, 0.0, y - (cell.y + cell.h))

    return (dx * dx + dy * dy) ** 0.5


def cell_at(cells, x, y, max_gap=0.02):
    """The (row, col) of the Cell rectangle that contains the viewport-
    normalized point (x, y). A point in the gap between Cells, or just outside
    the Passage, goes to the nearest rectangle if it is within `max_gap`
    (normalized units); otherwise it is on no Cell and this returns None.
    `cells` are the `protocol.CellRect`s the browser reported in its layout."""

    best = None
    best_distance = max_gap

    for cell in cells:
        distance = distance_to_rect(cell, x, y)
        if distance == 0.0:
            return cell.row, cell.col
        if distance <= best_distance:
            best, best_distance = cell, distance

    return (best.row, best.col) if best is not None else None
