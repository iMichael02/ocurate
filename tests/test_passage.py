import pytest

from passage import Passage, text_to_braille, build_default_passage


def test_encodes_hello_to_braille():

    assert text_to_braille("hello") == "⠓⠑⠇⠇⠕"


def test_rejects_uneven_line_lengths():

    with pytest.raises(ValueError):
        Passage(["short", "a longer line"])


def test_grid_dimensions():

    passage = Passage(["the fox", "runs by"])

    assert passage.num_rows == 2
    assert passage.num_columns == 7


def test_char_count_excludes_spaces():

    passage = Passage(["the fox", "runs by"])

    assert passage.char_count == len("thefoxrunsby")


def test_word_count():

    passage = Passage(["the fox", "runs by"])

    assert passage.word_count == 4


def test_char_at_returns_source_character():

    passage = Passage(["the fox", "runs by"])

    assert passage.char_at(0, 0) == "t"
    assert passage.char_at(0, 3) == " "


def test_first_and_last_cell():

    passage = Passage(["the fox", "runs by"])

    assert passage.first_cell == (0, 0)
    assert passage.last_cell == (1, 6)


def test_braille_lines_are_translated():

    passage = Passage(["ab"])

    assert passage.braille_lines == ["⠁⠃"]


def test_build_default_passage_has_uniform_lines():

    passage = build_default_passage()

    line_lengths = {len(line) for line in passage.lines}

    assert len(line_lengths) == 1
    assert passage.num_rows >= 2
