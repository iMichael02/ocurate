import json
import logging
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from starlette.websockets import WebSocketDisconnect

import app.api.ws_api as ws_api
from app.app import create_app
from app.config import Settings
from app.passages.passage import Passage, UnknownPassageError
from app.schemas import protocol
from app.sessions.tokens import build_token_store
from tests.sessions.test_session_manager import CELL_CENTRES, frame, hello, quadrant_layout
from tests.fake_clock import FakeClock

DATABASE_URL = "mysql+pymysql://user:password@localhost/ocurate"
PASSAGE = Passage(["ab", "cd"])


@pytest.fixture(autouse=True)
def stored_passages(monkeypatch):

    def fake_get_passage(engine, passage_id):

        if passage_id != "default":
            raise UnknownPassageError(passage_id)

        return PASSAGE

    monkeypatch.setattr(ws_api, "get_passage", fake_get_passage)


def make_app(clock=None, **overrides):
    """`clock` replaces the token store's clock, so a test can move time forward."""

    settings = Settings(api_key="key", token_secret="secret", database_url=DATABASE_URL, **overrides)
    app = create_app(settings)

    if clock is not None:
        app.state.tokens = build_token_store(settings, clock)

    app.state.finished = []
    app.state.on_session_finished = app.state.finished.append

    return app


def capture_refusals(caplog):
    """create_app resets the root logging handlers, so listen on the Session logger itself."""

    logger = logging.getLogger("app.sessions.session_manager")
    logger.addHandler(caplog.handler)
    logger.setLevel(logging.WARNING)

    return logger


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


def test_an_expired_token_is_refused_with_4401(caplog):

    clock = FakeClock(1000.0)
    app = make_app(clock)
    token = new_token(app)
    clock.now += app.state.settings.token_ttl_seconds + 1

    capture_refusals(caplog)

    with TestClient(app).websocket_connect("/ws") as websocket:
        websocket.send_text(hello(token=token))

        assert receive(websocket).code == "invalid_token"
        assert expect_close(websocket) == protocol.CLOSE_INVALID_TOKEN

    assert "session_token_refused reason=expired" in caplog.messages


def test_a_reused_token_is_refused_with_4401_and_the_first_socket_goes_on(caplog):

    app = make_app()
    token = new_token(app)
    client = TestClient(app)
    capture_refusals(caplog)

    with client.websocket_connect("/ws") as first:
        first.send_text(hello(token=token))
        assert receive(first).type == "hello_ack"

        # Opened while the first one is still live, like a second tab.
        with client.websocket_connect("/ws") as second:
            second.send_text(hello(token=token))

            assert receive(second).code == "invalid_token"
            assert expect_close(second) == protocol.CLOSE_INVALID_TOKEN

        assert "session_token_refused reason=already_used" in caplog.messages

        first.send_text(quadrant_layout())
        first.send_text(frame(0.0, (0.1, 0.1)))

        assert receive(first).type == "calibration_status"


def test_a_browser_origin_that_is_not_listed_is_refused():

    app = make_app(allowed_origins=("http://localhost:5173",))

    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect("/ws", headers={"origin": "https://evil.example"}):
            pass


def test_a_listed_origin_is_accepted():

    app = make_app(allowed_origins=("http://localhost:5173",))

    with TestClient(app).websocket_connect("/ws", headers={"origin": "http://localhost:5173"}) as websocket:
        websocket.send_text(hello(token=new_token(app)))

        assert receive(websocket).type == "hello_ack"


def test_no_origin_is_accepted_because_only_browsers_send_one():

    app = make_app(allowed_origins=("http://localhost:5173",))

    with TestClient(app).websocket_connect("/ws") as websocket:
        websocket.send_text(hello(token=new_token(app)))

        assert receive(websocket).type == "hello_ack"


def test_with_no_origins_listed_every_browser_origin_is_refused():

    app = make_app()

    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect("/ws", headers={"origin": "http://localhost:5173"}):
            pass


def test_a_socket_over_the_live_session_cap_is_closed_with_1013():

    app = make_app(max_concurrent_sessions=1)
    client = TestClient(app)

    with client.websocket_connect("/ws") as first:
        first.send_text(hello(token=new_token(app)))
        assert receive(first).type == "hello_ack"

        with client.websocket_connect("/ws") as second:
            assert expect_close(second) == protocol.CLOSE_TRY_AGAIN_LATER

    assert app.state.live_sessions == 0


def test_a_closed_session_frees_its_place_under_the_cap():

    app = make_app(max_concurrent_sessions=1)
    client = TestClient(app)

    with client.websocket_connect("/ws") as first:
        first.send_text(hello(token=new_token(app)))
        assert receive(first).type == "hello_ack"

    with client.websocket_connect("/ws") as second:
        second.send_text(hello(token=new_token(app)))

        assert receive(second).type == "hello_ack"


def test_a_frame_flood_is_closed_with_4429():

    app = make_app(max_frames_per_second=2)

    with TestClient(app).websocket_connect("/ws") as websocket:
        websocket.send_text(hello(token=new_token(app)))
        assert receive(websocket).type == "hello_ack"
        websocket.send_text(quadrant_layout())

        for i in range(10):
            websocket.send_text(frame(float(i), (0.1, 0.1)))

        types_seen = []
        with pytest.raises(WebSocketDisconnect) as closed:
            while True:
                types_seen.append(receive(websocket).type)

    assert closed.value.code == protocol.CLOSE_RATE_LIMITED
    assert "abandoned" in types_seen


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
