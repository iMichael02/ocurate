import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

import ocurate.api.sessions_api as sessions_api
from ocurate.app import create_app
from ocurate.config import Settings
from ocurate.passages.passage import UnknownPassageError, build_default_passage
from ocurate.passages.passage_store import StoredPassageError
from ocurate.sessions.tokens import TokenAlreadyUsed

API_KEY = "test-api-key-value"
SECRET = "test-token-secret-value"
DATABASE_URL = "mysql+pymysql://user:password@localhost/ocurate"


@pytest.fixture(autouse=True)
def stored_passages(monkeypatch):
    """The Passage lookup is mocked: only the `default` Passage exists."""

    def fake_get_passage(engine, passage_id):

        if passage_id != "default":
            raise UnknownPassageError(passage_id)

        return build_default_passage()

    monkeypatch.setattr(sessions_api, "get_passage", fake_get_passage)


@pytest.fixture
def app():

    # Built in a fixture, not in the test body: configure_logging resets the
    # root handlers, which would drop caplog's handler mid-test.
    return create_app(Settings(api_key=API_KEY, token_secret=SECRET, database_url=DATABASE_URL))


@pytest.fixture
def client(app):

    return TestClient(app)


def post_session(client, headers=None, body=None):

    return client.post("/sessions", headers=headers or {}, json=body if body is not None else {"passage_id": "default"})


def test_valid_key_creates_a_session(app, client):

    response = post_session(client, {"X-API-Key": API_KEY})

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"session_id", "passage_id", "token", "expires_in"}
    assert body["passage_id"] == "default"
    assert body["expires_in"] == 60

    grant = app.state.tokens.verify_and_consume_token(body["token"])
    assert grant.session_id == body["session_id"]
    assert grant.passage_id == "default"


def test_each_call_gets_a_new_session_id(client):

    first = post_session(client, {"X-API-Key": API_KEY}).json()
    second = post_session(client, {"X-API-Key": API_KEY}).json()

    assert first["session_id"] != second["session_id"]
    assert first["token"] != second["token"]


def test_missing_api_key_is_refused(app, client):

    response = post_session(client)

    assert response.status_code == 401
    assert app.state.tokens.pending_count() == 0


@pytest.mark.parametrize("wrong", ["nope", API_KEY + "x", API_KEY[:-1], "", API_KEY.upper()])
def test_wrong_api_key_is_refused(app, client, wrong):

    response = post_session(client, {"X-API-Key": wrong})

    assert response.status_code == 401
    assert app.state.tokens.pending_count() == 0


def test_missing_and_wrong_key_look_the_same(client):

    missing = post_session(client)
    wrong = post_session(client, {"X-API-Key": "nope"})

    assert missing.status_code == wrong.status_code == 401
    assert missing.json() == wrong.json() == {"detail": "unauthorized"}


def test_key_is_checked_before_the_body(client):

    response = post_session(client, body={"unexpected": 1})

    assert response.status_code == 401


def test_unknown_passage_is_not_found_and_creates_nothing(app, client):

    response = post_session(client, {"X-API-Key": API_KEY}, {"passage_id": "no-such-passage"})

    assert response.status_code == 404
    assert response.json() == {"detail": "unknown passage id"}
    assert app.state.tokens.pending_count() == 0


@pytest.mark.parametrize("body", [{}, {"passage_id": ""}, {"passage_id": 3}, {"passage_id": "default", "extra": 1}])
def test_bad_body_is_rejected(app, client, body):

    response = post_session(client, {"X-API-Key": API_KEY}, body)

    assert response.status_code == 422
    assert app.state.tokens.pending_count() == 0


def test_missing_token_secret_is_only_revealed_to_a_caller_with_the_key():

    client = TestClient(create_app(Settings(api_key=API_KEY, database_url=DATABASE_URL)))

    assert post_session(client, {"X-API-Key": API_KEY}).status_code == 503
    assert post_session(client, {"X-API-Key": "wrong"}).status_code == 401
    assert post_session(client).status_code == 401


@pytest.mark.parametrize("settings", [Settings(token_secret=SECRET, database_url=DATABASE_URL), Settings()])
def test_unset_api_key_looks_like_any_other_refusal(settings):

    client = TestClient(create_app(settings))

    assert post_session(client, {"X-API-Key": API_KEY}).status_code == 401
    assert post_session(client).status_code == 401


def test_needs_a_configured_passage_database():

    client = TestClient(create_app(Settings(api_key=API_KEY, token_secret=SECRET)))

    assert post_session(client, {"X-API-Key": API_KEY}).status_code == 503


def test_unreachable_database_answers_503_and_creates_nothing(app, client, monkeypatch):

    def fail(engine, passage_id):
        raise OperationalError("SELECT", {}, Exception("connection refused"))

    monkeypatch.setattr(sessions_api, "get_passage", fail)

    response = post_session(client, {"X-API-Key": API_KEY})

    assert response.status_code == 503
    assert response.json() == {"detail": "passage database unavailable"}
    assert app.state.tokens.pending_count() == 0


def test_invalid_stored_passage_answers_500(client, monkeypatch):

    def invalid(engine, passage_id):
        raise StoredPassageError(passage_id, "lines differ in length")

    monkeypatch.setattr(sessions_api, "get_passage", invalid)

    assert post_session(client, {"X-API-Key": API_KEY}).status_code == 500


def test_too_many_pending_sessions_answers_503():

    client = TestClient(create_app(Settings(api_key=API_KEY, token_secret=SECRET,
                                            database_url=DATABASE_URL, max_concurrent_sessions=1)))

    assert post_session(client, {"X-API-Key": API_KEY}).status_code == 201

    response = post_session(client, {"X-API-Key": API_KEY})

    assert response.status_code == 503
    assert response.json() == {"detail": "too many pending sessions"}


def test_dev_mode_works_without_a_token_secret():

    client = TestClient(create_app(Settings(api_key=API_KEY, database_url=DATABASE_URL, dev_mode=True)))

    assert post_session(client, {"X-API-Key": API_KEY}).status_code == 201


def test_lifetime_comes_from_settings():

    client = TestClient(create_app(Settings(api_key=API_KEY, token_secret=SECRET, database_url=DATABASE_URL, token_ttl_seconds=15)))

    assert post_session(client, {"X-API-Key": API_KEY}).json()["expires_in"] == 15


def test_api_key_and_token_never_appear_in_logs(app, client, caplog):

    with caplog.at_level(logging.DEBUG):
        created = post_session(client, {"X-API-Key": API_KEY}).json()
        post_session(client, {"X-API-Key": "wrong-key-value"})
        post_session(client)
        app.state.tokens.verify_and_consume_token(created["token"])
        with pytest.raises(TokenAlreadyUsed):
            app.state.tokens.verify_and_consume_token(created["token"])

    token = created["token"]
    payload_part, signature_part = token.split(".")

    assert "session_created" in caplog.text
    assert "session_create_refused" in caplog.text
    for secret in (API_KEY, "wrong-key-value", SECRET, token, payload_part, signature_part):
        assert secret not in caplog.text
