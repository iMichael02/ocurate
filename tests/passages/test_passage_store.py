from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.passages.passage import UnknownPassageError, build_default_passage, build_short_passage
from app.passages.passage_store import (
    SEED_PASSAGES,
    StoredPassageError,
    get_passage,
    init_db,
    list_passages,
    wait_and_init_db,
)


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


def test_init_db_creates_the_table_then_updates_every_seed_row():

    engine, connection = mock_engine(MagicMock(), MagicMock(rowcount=1), MagicMock(rowcount=1))

    init_db(engine)

    statements = [sql_of(call) for call in connection.execute.call_args_list]
    assert "CREATE TABLE IF NOT EXISTS passages" in statements[0]
    assert [s.lstrip().split()[0] for s in statements[1:]] == ["UPDATE", "UPDATE"]
    assert len(statements) == 3

    updated = {call.args[1]["id"]: call.args[1]["text_lines"] for call in connection.execute.call_args_list[1:]}
    assert updated == {
        "default": "\n".join(build_default_passage().lines),
        "short": "i can read this",
    }


def test_init_db_inserts_the_seed_rows_that_are_missing():

    engine, connection = mock_engine(
        MagicMock(), MagicMock(rowcount=0), MagicMock(), MagicMock(rowcount=0), MagicMock()
    )

    init_db(engine)

    statements = [sql_of(call).lstrip().split()[0] for call in connection.execute.call_args_list]
    assert statements == ["CREATE", "UPDATE", "INSERT", "UPDATE", "INSERT"]


def test_init_db_tolerates_a_concurrent_insert():

    duplicate = IntegrityError("INSERT", {}, Exception("duplicate key"))
    engine, connection = mock_engine(
        MagicMock(), MagicMock(rowcount=0), duplicate, MagicMock(rowcount=1)
    )

    init_db(engine)

    # The second seed row is still handled after the first insert lost the race.
    assert len(connection.execute.call_args_list) == 4


def test_every_seed_is_a_valid_passage():

    for passage_id, build in SEED_PASSAGES.items():
        assert build().num_rows >= 1, passage_id

    assert set(SEED_PASSAGES) == {"default", "short"}


def test_the_short_seed_is_one_sentence_on_one_row():

    passage = build_short_passage()

    assert passage.lines == ["i can read this"]
    assert passage.num_rows == 1


def test_wait_and_init_db_retries_until_the_database_answers():

    not_ready = OperationalError("CREATE", {}, Exception("connection refused"))
    engine, connection = mock_engine(not_ready, not_ready, MagicMock(), MagicMock(rowcount=1), MagicMock(rowcount=1))
    sleeps = []

    wait_and_init_db(engine, attempts=5, delay_seconds=2, sleep=sleeps.append)

    assert sleeps == [2, 2]
    assert len(connection.execute.call_args_list) == 5


def test_wait_and_init_db_gives_up_after_the_last_attempt():

    not_ready = OperationalError("CREATE", {}, Exception("connection refused"))
    engine, _ = mock_engine(not_ready, not_ready, not_ready)

    with pytest.raises(OperationalError):
        wait_and_init_db(engine, attempts=3, delay_seconds=0, sleep=lambda _: None)
