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

        if not lines or any(not line for line in lines):
            raise ValueError("Passage needs at least one line, and no line may be empty")

        if any(ch not in ASCII_TO_BRAILLE for line in lines for ch in line):
            raise ValueError("Passage lines may only contain lowercase letters a-z and spaces")

        if len({len(line) for line in lines}) > 1:
            raise ValueError("Passage lines must all have the same length")

        self.lines = lines
        self.braille_lines = [text_to_braille(line) for line in lines]

        self.num_rows = len(lines)
        self.num_columns = len(lines[0])

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
    """No Passage is stored under the requested id. Ids are stable: the web
    server stores them with each Session's result."""

    def __init__(self, passage_id):

        self.passage_id = passage_id
        super().__init__(passage_id)
