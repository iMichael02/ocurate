ASCII_TO_BRAILLE = {
    "a": "⠁", "b": "⠃", "c": "⠉", "d": "⠙",
    "e": "⠑", "f": "⠋", "g": "⠛", "h": "⠓",
    "i": "⠊", "j": "⠚", "k": "⠅", "l": "⠇",
    "m": "⠍", "n": "⠝", "o": "⠕", "p": "⠏",
    "q": "⠟", "r": "⠗", "s": "⠎", "t": "⠞",
    "u": "⠥", "v": "⠧", "w": "⠺", "x": "⠭",
    "y": "⠽", "z": "⠵", " ": "⠀",
}


def text_to_braille(text):

    return "".join(ASCII_TO_BRAILLE[ch] for ch in text)


class Passage:
    """A fixed, pre-loaded piece of Grade 1 Braille text (see CONTEXT.md).

    `lines` are the plain-text (lowercase letters and spaces) rows as they
    appear on screen. All lines must already be the same length: the uniform
    grid is an assumption of the Passage concept, not something the software
    silently corrects (see docs/adr/0002-grade-1-braille-passages.md).
    """

    def __init__(self, lines):

        if len({len(line) for line in lines}) > 1:
            raise ValueError("Passage lines must all have the same length")

        self.lines = lines
        self.braille_lines = [text_to_braille(line) for line in lines]

        self.num_rows = len(lines)
        self.num_columns = len(lines[0]) if lines else 0

        self.char_count = sum(len(line.replace(" ", "")) for line in lines)
        self.word_count = sum(len(line.split()) for line in lines)

        self.first_cell = (0, 0)
        self.last_cell = (self.num_rows - 1, self.num_columns - 1)

    def char_at(self, row, column):

        return self.lines[row][column]


def build_default_passage():

    return Passage([
        "read the texts",
        "with your eyes",
        "and count them",
    ])


class UnknownPassageError(KeyError):
    """No Passage is registered under the requested id."""

    def __init__(self, passage_id):

        self.passage_id = passage_id
        super().__init__(passage_id)


# The Grade 1 Passages this service serves, by id. Ids are stable: the web
# server stores them with each Session's result.
PASSAGES = {
    "default": build_default_passage(),
}


def get_passage(passage_id):
    """The Passage registered under `passage_id`. Raises UnknownPassageError,
    which Session creation uses to reject an unknown id."""

    try:
        return PASSAGES[passage_id]
    except KeyError:
        raise UnknownPassageError(passage_id) from None


def passage_summary(passage_id, passage):
    """What the browser and web server need to render a Passage and know its
    ground truth. The counts are the Passage's own, the same ones Reading
    Speed divides by; nothing here derives them from the grid size."""

    first_row, first_col = passage.first_cell
    last_row, last_col = passage.last_cell

    return {
        "id": passage_id,
        "lines": list(passage.lines),
        "braille_lines": list(passage.braille_lines),
        "rows": passage.num_rows,
        "columns": passage.num_columns,
        "char_count": passage.char_count,
        "word_count": passage.word_count,
        "first_cell": {"row": first_row, "col": first_col},
        "last_cell": {"row": last_row, "col": last_col},
    }


def list_passages():

    return [passage_summary(passage_id, passage) for passage_id, passage in PASSAGES.items()]
