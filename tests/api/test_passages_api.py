from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

import app.app as app_module
from app.app import create_app
from app.config import Settings
from app.passages.passage import UnknownPassageError, build_default_passage
from app.passages.passage_store import StoredPassageError
from app.analysis.reading_session import ReadingSession
from app.schemas.passage import passage_summary

DATABASE_URL = "mysql+pymysql://user:password@localhost/ocurate"

# The Passages the mocked store serves, by id.
STORED = {"default": build_default_passage()}


@pytest.fixture
def store(monkeypatch):
    """Replaces the database-backed store functions the endpoints call."""

    def fake_get_passage(engine, passage_id):

        try:
            return STORED[passage_id]
        except KeyError:
            raise UnknownPassageError(passage_id) from None

    def fake_list_passages(engine):

        return [passage_summary(passage_id, passage) for passage_id, passage in STORED.items()]

    monkeypatch.setattr(app_module, "get_passage", fake_get_passage)
    monkeypatch.setattr(app_module, "list_passages", fake_list_passages)


@pytest.fixture
def client(store):

    return TestClient(create_app(Settings(database_url=DATABASE_URL)))


def database_down():

    return OperationalError("SELECT", {}, Exception("connection refused"))


def test_listing_serves_every_stored_passage(client):

    response = client.get("/passages")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == list(STORED)


@pytest.mark.parametrize("passage_id", list(STORED))
def test_single_passage_matches_the_passage_logic(client, passage_id):

    passage = STORED[passage_id]

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


@pytest.mark.parametrize("passage_id", list(STORED))
def test_served_counts_are_what_reading_speed_uses(client, passage_id):

    served = client.get(f"/passages/{passage_id}").json()

    session = ReadingSession(STORED[passage_id])
    session.register_fixation(served["first_cell"]["row"], served["first_cell"]["col"], timestamp=0.0)
    session.register_fixation(served["last_cell"]["row"], served["last_cell"]["col"], timestamp=60.0)

    # Over exactly one minute, CPM and WPM equal the counts they divide.
    result = session.result()
    assert result["cpm"] == pytest.approx(served["char_count"])
    assert result["wpm"] == pytest.approx(served["word_count"])


def test_passages_need_a_configured_database():

    client = TestClient(create_app(Settings()))

    assert client.get("/passages").status_code == 503
    assert client.get("/passages/default").status_code == 503


@pytest.mark.parametrize("path", ["/passages", "/passages/default"])
def test_an_unreachable_database_answers_503(monkeypatch, path):

    def fail(*args):
        raise database_down()

    monkeypatch.setattr(app_module, "get_passage", fail)
    monkeypatch.setattr(app_module, "list_passages", fail)
    client = TestClient(create_app(Settings(database_url=DATABASE_URL)))

    response = client.get(path)

    assert response.status_code == 503
    assert response.json() == {"detail": "passage database unavailable"}


def test_an_invalid_stored_passage_answers_500(monkeypatch):

    def invalid(engine, passage_id):
        raise StoredPassageError(passage_id, "lines differ in length")

    monkeypatch.setattr(app_module, "get_passage", invalid)
    client = TestClient(create_app(Settings(database_url=DATABASE_URL)))

    response = client.get("/passages/default")

    assert response.status_code == 500
    assert response.json() == {"detail": "stored passage is invalid"}


def test_the_engine_is_disposed_on_shutdown(monkeypatch):

    engine = MagicMock()
    monkeypatch.setattr(app_module, "create_engine", lambda *args, **kwargs: engine)

    with TestClient(create_app(Settings(database_url=DATABASE_URL))):
        engine.dispose.assert_not_called()

    engine.dispose.assert_called_once()


def test_a_listed_origin_gets_cors_headers_on_passages(store):

    app = create_app(Settings(database_url=DATABASE_URL, allowed_origins=("http://localhost:5173",)))

    response = TestClient(app).get("/passages", headers={"origin": "http://localhost:5173"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_an_unlisted_origin_gets_no_cors_headers(store):

    app = create_app(Settings(database_url=DATABASE_URL, allowed_origins=("http://localhost:5173",)))

    response = TestClient(app).get("/passages", headers={"origin": "https://evil.example"})

    assert "access-control-allow-origin" not in response.headers


def test_cors_is_off_when_no_origins_are_listed(store):

    app = create_app(Settings(database_url=DATABASE_URL))

    response = TestClient(app).get("/passages", headers={"origin": "http://localhost:5173"})

    assert "access-control-allow-origin" not in response.headers
