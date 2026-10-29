import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from starlette.websockets import WebSocketDisconnect

import ocurate.api.ws_api as ws_api
from ocurate.app import create_app
from ocurate.config import Settings
from ocurate.passages.passage import Passage, UnknownPassageError
from ocurate.schemas import protocol
from tests.sessions.test_session_manager import CELL_CENTRES, frame, hello, quadrant_layout

DATABASE_URL = "mysql+pymysql://user:password@localhost/ocurate"
PASSAGE = Passage(["ab", "cd"])


@pytest.fixture(autouse=True)
def stored_passages(monkeypatch):

    def fake_get_passage(engine, passage_id):

        if passage_id != "default":
            raise UnknownPassageError(passage_id)

        return PASSAGE

    monkeypatch.setattr(ws_api, "get_passage", fake_get_passage)


def make_app(**overrides):

    settings = Settings(api_key="key", token_secret="secret", database_url=DATABASE_URL, **overrides)
    app = create_app(settings)
    app.state.finished = []
    app.state.on_session_finished = app.state.finished.append

    return app


def new_token(app):

    return app.state.tokens.create_session("default").token


def receive(websocket):

    return protocol.parse_server_message(websocket.receive_text())


def expect_close(websocket):

    with pytest.raises(WebSocketDisconnect) as closed:
        websocket.receive_text()

    return closed.value.code


def test_hello_is_acknowledged():

    app = make_app()

    with TestClient(app).websocket_connect("/ws") as websocket:
        websocket.send_text(hello(token=new_token(app)))

        ack = receive(websocket)

    assert (ack.type, ack.version, ack.supported) == ("hello_ack", 2, [1, 2])


def test_a_bad_token_is_refused_with_4401():

    app = make_app()

    with TestClient(app).websocket_connect("/ws") as websocket:
        websocket.send_text(hello(token="not-a-token"))

        assert receive(websocket).code == "invalid_token"
        assert expect_close(websocket) == protocol.CLOSE_INVALID_TOKEN


def test_a_token_works_once():

    app = make_app()
    token = new_token(app)
    client = TestClient(app)

    with client.websocket_connect("/ws") as first:
        first.send_text(hello(token=token))
        assert receive(first).type == "hello_ack"

    with client.websocket_connect("/ws") as second:
        second.send_text(hello(token=token))
        assert receive(second).code == "invalid_token"


def test_an_unsupported_version_is_refused_with_4409():

    app = make_app()

    with TestClient(app).websocket_connect("/ws") as websocket:
        websocket.send_text(hello(version=9, token=new_token(app)))

        error = receive(websocket)
        assert (error.code, error.supported) == ("unsupported_version", [1, 2])
        assert expect_close(websocket) == protocol.CLOSE_UNSUPPORTED_VERSION


def test_a_non_json_message_is_refused_with_4400():

    app = make_app()

    with TestClient(app).websocket_connect("/ws") as websocket:
        websocket.send_text("not json")

        assert receive(websocket).code == "invalid_message"
        assert expect_close(websocket) == protocol.CLOSE_INVALID_MESSAGE


def test_a_binary_message_is_refused_with_4400():

    app = make_app()

    with TestClient(app).websocket_connect("/ws") as websocket:
        websocket.send_bytes(b"\x00\x01")

        assert receive(websocket).code == "invalid_message"
        assert expect_close(websocket) == protocol.CLOSE_INVALID_MESSAGE


def test_quit_ends_the_session_and_reports_the_outcome():

    app = make_app()

    with TestClient(app).websocket_connect("/ws") as websocket:
        websocket.send_text(hello(token=new_token(app)))
        receive(websocket)
        websocket.send_text(quadrant_layout())
        websocket.send_text(json.dumps({"type": "quit"}))

        assert receive(websocket).reason == "quit"
        assert expect_close(websocket) == protocol.CLOSE_NORMAL

    [outcome] = app.state.finished
    assert (outcome.kind, outcome.reason, outcome.passage_id) == ("abandoned", "quit", "default")


def test_a_dropped_socket_is_reported_as_abandoned():

    app = make_app()

    with TestClient(app).websocket_connect("/ws") as websocket:
        websocket.send_text(hello(token=new_token(app)))
        receive(websocket)

    deadline = time.time() + 2
    while not app.state.finished and time.time() < deadline:
        time.sleep(0.01)

    assert [o.reason for o in app.state.finished] == ["socket_closed"]


def test_silence_times_out_with_4408():

    app = make_app(session_inactivity_seconds=0.1)

    with TestClient(app).websocket_connect("/ws") as websocket:
        websocket.send_text(hello(token=new_token(app)))
        receive(websocket)

        assert receive(websocket).reason == "frame_timeout"
        assert expect_close(websocket) == protocol.CLOSE_TIMEOUT


@pytest.mark.parametrize("failure", [OperationalError("SELECT", {}, Exception("down")), UnknownPassageError("x")])
def test_an_unavailable_passage_closes_with_1011(monkeypatch, failure):

    def fail(engine, passage_id):
        raise failure

    monkeypatch.setattr(ws_api, "get_passage", fail)
    app = make_app()

    with TestClient(app).websocket_connect("/ws") as websocket:
        websocket.send_text(hello(token=new_token(app)))

        assert expect_close(websocket) == 1011


def test_no_database_closes_with_1011():

    app = create_app(Settings(api_key="key", token_secret="secret"))

    with TestClient(app).websocket_connect("/ws") as websocket:
        websocket.send_text(hello(token=app.state.tokens.create_session("default").token))

        assert expect_close(websocket) == 1011


def test_calibration_progress_is_streamed():

    app = make_app()

    with TestClient(app).websocket_connect("/ws") as websocket:
        websocket.send_text(hello(token=new_token(app)))
        receive(websocket)
        websocket.send_text(quadrant_layout())
        websocket.send_text(frame(0.0, (0.1, 0.1)))

        status = receive(websocket)

    assert status.type == "calibration_status"
    assert status.points[0].state == "collecting"
