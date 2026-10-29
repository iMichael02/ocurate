from pydantic import BaseModel


class CellPosition(BaseModel):
    row: int
    col: int


class PassageSummary(BaseModel):
    """What the browser and web server need to render a Passage and know its
    ground truth. The counts are the Passage's own, the same ones Reading
    Speed divides by; nothing here derives them from the grid size."""

    id: str
    lines: list[str]
    braille_lines: list[str]
    rows: int
    columns: int
    char_count: int
    word_count: int
    first_cell: CellPosition
    last_cell: CellPosition


def passage_summary(passage_id, passage):

    return PassageSummary(
        id=passage_id,
        lines=passage.lines,
        braille_lines=passage.braille_lines,
        rows=passage.num_rows,
        columns=passage.num_columns,
        char_count=passage.char_count,
        word_count=passage.word_count,
        first_cell=CellPosition(row=passage.first_cell[0], col=passage.first_cell[1]),
        last_cell=CellPosition(row=passage.last_cell[0], col=passage.last_cell[1]),
    )
