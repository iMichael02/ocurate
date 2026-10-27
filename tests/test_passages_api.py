import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import create_app
from config import Settings
from passage import UnknownPassageError, build_default_passage
from passage_store import get_passage, init_db, list_passages
from reading_session import ReadingSession

# The Passages init_db seeds, by id.
SEEDED = {"default": build_default_passage()}


@pytest.fixture
def database_url(tmp_path):

    url = f"sqlite:///{tmp_path / 'passages.db'}"
    init_db(create_engine(url))

    return url


@pytest.fixture
def engine(database_url):

    return create_engine(database_url)


@pytest.fixture
def client(database_url):

    return TestClient(create_app(Settings(database_url=database_url)))


def test_listing_serves_every_stored_passage(client):

    response = client.get("/passages")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == list(SEEDED)


@pytest.mark.parametrize("passage_id", list(SEEDED))
def test_single_passage_matches_the_passage_logic(client, passage_id):

    passage = SEEDED[passage_id]

    response = client.get(f"/passages/{passage_id}")

    assert response.status_code == 200
    assert response.json() == {
        "id": passage_id,
        "lines": passage.lines,
        "braille_lines": passage.braille_lines,
        "rows": passage.num_rows,
        "columns": passage.num_columns,
        "char_count": passage.char_count,
        "word_count": passage.word_count,
        "first_cell": {"row": passage.first_cell[0], "col": passage.first_cell[1]},
        "last_cell": {"row": passage.last_cell[0], "col": passage.last_cell[1]},
    }


def test_listing_and_single_endpoint_agree(client):

    for item in client.get("/passages").json():
        assert client.get(f"/passages/{item['id']}").json() == item


def test_unknown_passage_is_not_found(client):

    response = client.get("/passages/no-such-passage")

    assert response.status_code == 404
    assert response.json() == {"detail": "unknown passage id"}


def test_get_passage_rejects_an_unknown_id(engine):

    with pytest.raises(UnknownPassageError):
        get_passage(engine, "no-such-passage")


@pytest.mark.parametrize("passage_id", list(SEEDED))
def test_served_counts_are_what_reading_speed_uses(client, engine, passage_id):

    served = client.get(f"/passages/{passage_id}").json()

    session = ReadingSession(get_passage(engine, passage_id))
    session.register_fixation(served["first_cell"]["row"], served["first_cell"]["col"], timestamp=0.0)
    session.register_fixation(served["last_cell"]["row"], served["last_cell"]["col"], timestamp=60.0)

    # Over exactly one minute, CPM and WPM equal the counts they divide.
    result = session.result()
    assert result["cpm"] == pytest.approx(served["char_count"])
    assert result["wpm"] == pytest.approx(served["word_count"])


def test_seeded_default_passage_keeps_its_lines(engine):

    assert get_passage(engine, "default").lines == build_default_passage().lines


def test_init_db_can_run_twice_without_duplicating(engine):

    init_db(engine)

    assert [item["id"] for item in list_passages(engine)] == ["default"]


def test_stored_passage_is_validated_by_the_passage_class(engine):

    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO passages (id, text_lines) VALUES (:id, :text_lines)"),
            {"id": "uneven", "text_lines": "short\na longer line"},
        )

    with pytest.raises(ValueError):
        get_passage(engine, "uneven")


def test_passages_need_a_configured_database():

    client = TestClient(create_app(Settings()))

    assert client.get("/passages").status_code == 503
    assert client.get("/passages/default").status_code == 503
