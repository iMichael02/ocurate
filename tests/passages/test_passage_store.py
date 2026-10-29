from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from ocurate.passages.passage import UnknownPassageError, build_default_passage
from ocurate.passages.passage_store import StoredPassageError, get_passage, init_db, list_passages


def mock_engine(*results):
    """An engine whose connections return `results` from successive
    `execute` calls; both `connect()` and `begin()` yield the connection."""

    connection = MagicMock()
    connection.execute.side_effect = list(results)

    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    engine.begin.return_value.__enter__.return_value = connection

    return engine, connection


def query_result(rows):

    result = MagicMock()
    result.first.return_value = rows[0] if rows else None
    result.all.return_value = rows

    return result


def row(passage_id, text_lines):

    return SimpleNamespace(id=passage_id, text_lines=text_lines)


def sql_of(call):

    return str(call.args[0])


def test_get_passage_builds_the_passage_from_the_stored_lines():

    engine, _ = mock_engine(query_result([row("default", "ab\ncd")]))

    passage = get_passage(engine, "default")

    assert passage.lines == ["ab", "cd"]


def test_get_passage_queries_by_id():

    engine, connection = mock_engine(query_result([row("default", "ab")]))

    get_passage(engine, "default")

    assert connection.execute.call_args.args[1] == {"id": "default"}


def test_get_passage_rejects_an_unknown_id():

    engine, _ = mock_engine(query_result([]))

    with pytest.raises(UnknownPassageError):
        get_passage(engine, "no-such-passage")


@pytest.mark.parametrize("text_lines", ["short\na longer line", "", "ab\n", "AB\ncd", "a-\ncd"])
def test_get_passage_reports_an_invalid_row(text_lines):

    engine, _ = mock_engine(query_result([row("bad", text_lines)]))

    with pytest.raises(StoredPassageError) as raised:
        get_passage(engine, "bad")

    assert raised.value.passage_id == "bad"


def test_list_passages_summarises_every_row():

    engine, _ = mock_engine(query_result([row("a", "ab\ncd"), row("b", "xy")]))

    assert [item.id for item in list_passages(engine)] == ["a", "b"]


def test_list_passages_skips_an_invalid_row_instead_of_failing():

    engine, _ = mock_engine(query_result([row("good", "ab"), row("bad", "ab\nc")]))

    assert [item.id for item in list_passages(engine)] == ["good"]


def test_init_db_updates_an_existing_default_row():

    engine, connection = mock_engine(MagicMock(), MagicMock(rowcount=1))

    init_db(engine)

    statements = [sql_of(call) for call in connection.execute.call_args_list]
    assert "CREATE TABLE IF NOT EXISTS passages" in statements[0]
    assert statements[1].lstrip().startswith("UPDATE passages")
    assert len(statements) == 2
    assert connection.execute.call_args.args[1] == {
        "id": "default",
        "text_lines": "\n".join(build_default_passage().lines),
    }


def test_init_db_inserts_the_default_row_when_missing():

    engine, connection = mock_engine(MagicMock(), MagicMock(rowcount=0), MagicMock())

    init_db(engine)

    assert sql_of(connection.execute.call_args).lstrip().startswith("INSERT INTO passages")


def test_init_db_tolerates_a_concurrent_insert():

    duplicate = IntegrityError("INSERT", {}, Exception("duplicate key"))
    engine, _ = mock_engine(MagicMock(), MagicMock(rowcount=0), duplicate)

    init_db(engine)
