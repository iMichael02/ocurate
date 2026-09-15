import pytest

from passage import Passage
from reading_session import ReadingSession


@pytest.fixture
def passage():
    return Passage(["the fox", "runs by"])


def test_ignores_fixations_before_reaching_the_first_cell(passage):

    session = ReadingSession(passage)

    session.register_fixation(0, 3, timestamp=1.0)

    assert session.start_time is None


def test_starts_on_first_cell_fixation(passage):

    session = ReadingSession(passage)

    session.register_fixation(0, 0, timestamp=1.0)

    assert session.start_time == 1.0
    assert not session.is_complete()


def test_completes_on_last_cell_fixation(passage):

    session = ReadingSession(passage)

    session.register_fixation(0, 0, timestamp=1.0)
    session.register_fixation(1, 6, timestamp=3.0)

    assert session.is_complete()
    assert session.end_time == 3.0


def test_reading_speed_from_known_passage_length(passage):

    session = ReadingSession(passage)

    session.register_fixation(0, 0, timestamp=0.0)
    session.register_fixation(1, 6, timestamp=6.0)

    result = session.result()

    # 6 seconds = 0.1 minutes; passage has 12 non-space chars, 4 words
    assert result["cpm"] == pytest.approx(120.0)
    assert result["wpm"] == pytest.approx(40.0)


def test_repeated_fixation_on_same_cell_is_not_a_new_event(passage):

    session = ReadingSession(passage)

    session.register_fixation(0, 0, timestamp=0.0)
    session.register_fixation(0, 0, timestamp=0.5)
    session.register_fixation(1, 6, timestamp=3.0)

    result = session.result()

    assert result["saccades"] == 1


def test_backward_saccade_is_a_regression(passage):

    session = ReadingSession(passage)

    session.register_fixation(0, 0, timestamp=0.0)
    session.register_fixation(0, 3, timestamp=1.0)
    session.register_fixation(0, 1, timestamp=2.0)
    session.register_fixation(1, 6, timestamp=4.0)

    result = session.result()

    assert result["regressions"] == 1


def test_forward_jump_over_a_character_counts_as_skipped():

    session = ReadingSession(Passage(["abcd"]))

    session.register_fixation(0, 0, timestamp=0.0)
    session.register_fixation(0, 2, timestamp=1.0)
    session.register_fixation(0, 3, timestamp=2.0)

    result = session.result()

    # column 1 ("b") was jumped over
    assert result["skipped_characters"] == 1


def test_forward_jump_over_a_space_is_not_counted_as_skipped():

    session = ReadingSession(Passage(["ab cd"]))

    session.register_fixation(0, 0, timestamp=0.0)
    session.register_fixation(0, 1, timestamp=0.5)
    session.register_fixation(0, 3, timestamp=1.0)  # skips the space at column 2
    session.register_fixation(0, 4, timestamp=1.5)

    result = session.result()

    assert result["skipped_characters"] == 0


def test_regressing_to_a_previously_skipped_cell_unmarks_it():

    session = ReadingSession(Passage(["abcd"]))

    session.register_fixation(0, 0, timestamp=0.0)
    session.register_fixation(0, 2, timestamp=1.0)  # skips "b" at column 1
    session.register_fixation(0, 1, timestamp=2.0)  # regresses back and reads "b"
    session.register_fixation(0, 3, timestamp=3.0)

    result = session.result()

    assert result["skipped_characters"] == 0


def test_fixations_after_completion_are_ignored(passage):

    session = ReadingSession(passage)

    session.register_fixation(0, 0, timestamp=0.0)
    session.register_fixation(1, 6, timestamp=2.0)
    session.register_fixation(0, 0, timestamp=5.0)

    assert session.end_time == 2.0
