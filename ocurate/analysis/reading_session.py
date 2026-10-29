class ReadingSession:
    """Tracks a Learner's Braille-Cell fixation sequence for one Passage and
    derives Reading Speed plus the secondary eye-movement layer (see
    CONTEXT.md: Fixation, Saccade, Regression, Skipped Character).

    Reading start/end are detected automatically: start is the first
    fixation on the Passage's first Cell, end is the first fixation on its
    last Cell (see architecture-design.md step 6/7).
    """

    def __init__(self, passage):

        self.passage = passage

        self.start_time = None
        self.end_time = None

        self.sequence = []
        self._max_index_reached = -1

        self.regressions = 0
        self.saccades = 0
        self._skipped_indices = set()

    def _linear_index(self, row, column):

        return row * self.passage.num_columns + column

    def is_complete(self):

        return self.end_time is not None

    def register_fixation(self, row, column, timestamp):

        if self.is_complete():
            return

        cell = (row, column)

        if self.start_time is None:
            if cell != self.passage.first_cell:
                return
            self.start_time = timestamp

        if self.sequence and self.sequence[-1] == cell:
            return

        index = self._linear_index(row, column)

        if self.sequence:

            previous_index = self._linear_index(*self.sequence[-1])

            self.saccades += 1

            if index < previous_index:
                self.regressions += 1
            elif index > self._max_index_reached + 1:
                for skipped in range(self._max_index_reached + 1, index):
                    skipped_row, skipped_column = divmod(skipped, self.passage.num_columns)
                    if self.passage.char_at(skipped_row, skipped_column) != " ":
                        self._skipped_indices.add(skipped)

            self._max_index_reached = max(self._max_index_reached, index)

        else:
            self._max_index_reached = index

        # A cell being fixated now, even via a regression, is no longer "never fixated".
        self._skipped_indices.discard(index)

        self.sequence.append(cell)

        if cell == self.passage.last_cell:
            self.end_time = timestamp

    def result(self):

        elapsed_seconds = self.end_time - self.start_time
        minutes = max(elapsed_seconds, 1e-6) / 60

        return {
            "elapsed_seconds": elapsed_seconds,
            "cpm": self.passage.char_count / minutes,
            "wpm": self.passage.word_count / minutes,
            "regressions": self.regressions,
            "saccades": self.saccades,
            "skipped_characters": len(self._skipped_indices),
            "sequence": list(self.sequence),
        }
