import json
import logging

import numpy as np
import pytest

from app.analysis.calibration import CALIBRATION_POINTS, Calibration, CalibrationResult, TargetStatus
from app.analysis.eye_features import FEATURE_SIZE_V2, model_columns
from app.config import Settings
from app.passages.passage import Passage
from app.schemas import protocol
from app.sessions.session_manager import (CALIBRATION_SAMPLES_PER_POINT, Authenticated, FrameRateLimiter,
                             PassageUnavailable, Phase, Session)
from app.sessions.tokens import InvalidSignature, TokenAlreadyUsed
from tests.fake_clock import FakeClock

PASSAGE = Passage(["ab", "cd"])
LAST_POINT = len(CALIBRATION_POINTS) - 1


# --- helpers ------------------------------------------------------------------

def authenticate(token):

    if token == "used":
        raise TokenAlreadyUsed()
    if token != "good":
        raise InvalidSignature()

    return Authenticated("session-1", "default", PASSAGE)


def dump(message):

    return json.dumps(message)


def hello(version=2, token="good"):

    return dump({"type": "hello", "version": version, "token": token})


def quadrant_layout():
    """The Passage's four Cells as the four quadrants of the viewport."""

    cells = [{"row": r, "col": c, "x": c * 0.5, "y": r * 0.5, "w": 0.5, "h": 0.5} for r in range(2) for c in range(2)]

    return dump({"type": "layout", "viewport": {"width": 1000, "height": 800}, "cells": cells})


def frame_dict(t, target=None, shift=0.0, eye_centres=False):
    """A valid frame. `shift` moves the iris so features differ between frames."""

    iris = [{"x": 0.62 + shift, "y": 0.41}, {"x": 0.63 + shift, "y": 0.42}, {"x": 0.62 + shift, "y": 0.43},
            {"x": 0.61 + shift, "y": 0.42}] + [{"x": 0.38 + shift, "y": 0.41}, {"x": 0.39 + shift, "y": 0.42},
                                                  {"x": 0.38 + shift, "y": 0.43}, {"x": 0.37 + shift, "y": 0.42}]
    corners = [{"x": 0.66, "y": 0.42}, {"x": 0.58, "y": 0.42}, {"x": 0.62, "y": 0.4}, {"x": 0.62, "y": 0.44},
               {"x": 0.42, "y": 0.42}, {"x": 0.34, "y": 0.42}, {"x": 0.38, "y": 0.4}, {"x": 0.38, "y": 0.44}]
    message = {
        "type": "frame", "t": t, "iris": iris, "eye_corners": corners, "nose": {"x": 0.5, "y": 0.55},
        "matrix": [[0.99, 0.01, -0.02, 1.2], [-0.01, 0.99, 0.03, -0.8], [0.02, -0.03, 0.99, -35.0], [0, 0, 0, 1]],
    }
    if target is not None:
        message["target"] = {"x": target[0], "y": target[1]}
    if eye_centres:
        message["eye_centres"] = [{"x": 0.62, "y": 0.42, "confidence": 0.9}, {"x": 0.38, "y": 0.42, "confidence": 0.9}]

    return message


def frame(t, target=None, **kwargs):

    return dump(frame_dict(t, target, **kwargs))


class FixedModel:
    """Predicts whatever `gaze` currently is."""

    def __init__(self):
        self.gaze = (0.25, 0.25)

    def predict(self, X):
        return np.array([self.gaze for _ in X])


class FakeCalibration:
    """Counts tagged frames; `outcome` and `reason` decide how it finishes."""

    outcome = "ready"
    reason = None
    model = FixedModel()

    def __init__(self):
        self.restarts = 0
        self.samples = {i: 0 for i in range(16)}

    def restart(self):
        self.restarts += 1
        self.samples = {i: 0 for i in range(16)}

    def add_frame(self, target, features):
        self.samples[CALIBRATION_POINTS.index(target)] += 1

    def progress(self, current):
        return [TargetStatus(i, "ok" if i < current else "collecting" if i == current else "pending", n)
                for i, n in self.samples.items()]

    def finish(self):
        points = [TargetStatus(i, "ok", n) for i, n in self.samples.items()]
        model = type(self).model if self.outcome == "ready" else None
        return CalibrationResult(points, self.outcome, self.reason, model)


def make_session(settings=None, calibration_factory=FakeCalibration):

    return Session(settings or Settings(), authenticate, calibration_factory)


def types(reply):

    return [m.type for m in reply.messages]


def started(settings=None, **kwargs):
    """A Session that has sent hello and layout."""

    session = make_session(settings, **kwargs)
    session.receive(hello())
    session.receive(quadrant_layout())

    return session


def calibrate(session, t0=0.0):
    """Streams every target to the end, returning the reply to the last frame
    and the next free timestamp."""

    t = t0
    reply = None

    for index, point in enumerate(CALIBRATION_POINTS):
        count = CALIBRATION_SAMPLES_PER_POINT if index == LAST_POINT else 3
        for _ in range(count):
            reply = session.receive(frame(t, point))
            t += 33.0

    return reply, t


def reading_session(**kwargs):

    session = started(**kwargs)
    calibrate(session)
    session.receive(dump({"type": "calibration_done"}))

    return session


# --- handshake ----------------------------------------------------------------

def test_hello_is_acknowledged_with_the_negotiated_version():

    session = make_session()

    reply = session.receive(hello(version=1))

    assert reply.close_code is None
    assert reply.messages[0].model_dump() == {"type": "hello_ack", "version": 1, "supported": [1, 2]}
    assert session.session_id == "session-1"
    assert session.phase is Phase.LAYOUT


def test_an_unsupported_version_is_refused_before_the_token_is_checked():

    session = make_session()

    reply = session.receive(hello(version=3, token="not even checked"))

    assert reply.close_code == protocol.CLOSE_UNSUPPORTED_VERSION
    assert reply.messages[0].code == "unsupported_version"
    assert reply.messages[0].supported == [1, 2]


@pytest.mark.parametrize("token", ["bad", "used"])
def test_a_refused_token_closes_with_4401(token):

    session = make_session()

    reply = session.receive(hello(token=token))

    assert reply.close_code == protocol.CLOSE_INVALID_TOKEN
    assert [m.code for m in reply.messages] == ["invalid_token"]
    assert reply.messages[0].message == "Session token refused"
    assert session.outcome is None


def test_an_unavailable_passage_closes_without_a_protocol_error():

    def unavailable(token):
        raise PassageUnavailable()

    reply = Session(Settings(), unavailable).receive(hello())

    assert reply.close_code == 1011
    assert reply.messages == []


def test_the_first_message_must_be_hello():

    reply = make_session().receive(quadrant_layout())

    assert reply.close_code == protocol.CLOSE_INVALID_MESSAGE
    assert [m.code for m in reply.messages] == ["out_of_order"]


def test_a_second_hello_is_out_of_order_and_abandons_the_session():

    session = make_session()
    session.receive(hello())

    reply = session.receive(hello())

    assert types(reply) == ["error", "abandoned"]
    assert reply.messages[0].code == "out_of_order"
    assert reply.messages[1].reason == "protocol_error"
    assert reply.close_code == protocol.CLOSE_INVALID_MESSAGE
    assert session.outcome.reason == "protocol_error"


@pytest.mark.parametrize("raw", ["not json", "[]", '{"type":"nonsense"}', b"\x00binary", None])
def test_an_invalid_message_closes_with_4400(raw):

    session = make_session()
    session.receive(hello())

    reply = session.receive(raw)

    assert reply.messages[0].code == "invalid_message"
    assert reply.close_code == protocol.CLOSE_INVALID_MESSAGE


def test_an_oversized_message_is_refused():

    session = make_session(Settings(max_message_bytes=100))

    reply = session.receive(hello(token="x" * 200))

    assert reply.messages[0].code == "invalid_message"


def test_the_error_names_fields_but_never_echoes_values():

    session = make_session()
    session.receive(hello())

    reply = session.receive(dump({"type": "layout", "viewport": {"width": 1, "height": 1}, "cells": "secret-value"}))

    assert "secret-value" not in reply.messages[0].message


# --- layout -------------------------------------------------------------------

def test_a_layout_covering_every_cell_starts_calibration():

    session = make_session()
    session.receive(hello())

    reply = session.receive(quadrant_layout())

    assert reply.messages == []
    assert session.phase is Phase.CALIBRATING


@pytest.mark.parametrize("drop", [0, 3])
def test_a_layout_missing_a_cell_is_refused(drop):

    session = make_session()
    session.receive(hello())
    message = json.loads(quadrant_layout())
    del message["cells"][drop]

    reply = session.receive(dump(message))

    assert reply.messages[0].code == "invalid_message"


def test_a_layout_with_an_unknown_cell_is_refused():

    session = make_session()
    session.receive(hello())
    message = json.loads(quadrant_layout())
    message["cells"][3]["row"] = 5

    assert session.receive(dump(message)).messages[0].code == "invalid_message"


def test_a_second_layout_is_out_of_order():

    session = started()

    assert session.receive(quadrant_layout()).messages[0].code == "out_of_order"


def test_a_frame_before_the_layout_is_out_of_order():

    session = make_session()
    session.receive(hello())

    assert session.receive(frame(0.0)).messages[0].code == "out_of_order"


# --- frames and timestamps ------------------------------------------------------

def test_a_timestamp_going_backwards_ends_the_session():

    session = started()
    session.receive(frame(1000.0, CALIBRATION_POINTS[0]))

    reply = session.receive(frame(999.0, CALIBRATION_POINTS[0]))

    assert [m.type for m in reply.messages] == ["error", "abandoned"]
    assert reply.messages[0].code == "timestamp_regression"
    assert reply.close_code == protocol.CLOSE_INVALID_MESSAGE


def test_an_equal_timestamp_is_accepted():

    session = started()
    session.receive(frame(1000.0, CALIBRATION_POINTS[0]))

    assert session.receive(frame(1000.0, CALIBRATION_POINTS[0])).close_code is None


def test_eye_centres_are_refused_on_version_1():

    session = make_session()
    session.receive(hello(version=1))
    session.receive(quadrant_layout())

    reply = session.receive(frame(0.0, CALIBRATION_POINTS[0], eye_centres=True))

    assert reply.messages[0].code == "invalid_message"


def test_eye_centres_are_accepted_on_version_2():

    session = started()

    assert session.receive(frame(0.0, CALIBRATION_POINTS[0], eye_centres=True)).close_code is None


# --- calibration --------------------------------------------------------------

def test_the_first_frame_of_a_target_reports_progress():

    session = started()

    reply = session.receive(frame(0.0, CALIBRATION_POINTS[0]))

    status = reply.messages[0]
    assert status.type == "calibration_status"
    assert status.outcome is None
    assert (status.attempt, status.max_attempts) == (1, 3)
    assert [p.state for p in status.points][:2] == ["collecting", "pending"]


def test_progress_is_sent_every_few_frames_not_for_each_one():

    session = started()

    counts = [len(session.receive(frame(33.0 * i, CALIBRATION_POINTS[0])).messages) for i in range(11)]

    assert counts == [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def test_untagged_frames_while_calibrating_are_ignored():

    session = started()

    assert session.receive(frame(0.0)).messages == []


def test_a_target_off_the_grid_is_ignored():

    session = started()

    assert session.receive(frame(0.0, (0.5, 0.5))).messages == []


def test_calibration_is_judged_once_the_last_target_has_enough_samples():

    session = started()

    reply, _ = calibrate(session)

    assert reply.messages[0].outcome == "ready"
    assert session.phase is Phase.CALIBRATION_READY


def test_a_failed_calibration_waits_for_a_restart():

    class Failing(FakeCalibration):
        outcome, reason = "failed", "too_few_points"

    session = started(calibration_factory=Failing)

    reply, t = calibrate(session)

    status = reply.messages[0]
    assert (status.outcome, status.reason, status.attempt) == ("failed", "too_few_points", 1)
    assert reply.close_code is None
    assert session.phase is Phase.CALIBRATION_FAILED

    # Frames still in flight are ignored, not errors.
    assert session.receive(frame(t, CALIBRATION_POINTS[0])).messages == []

    assert session.receive(dump({"type": "calibration_restart"})).messages == []
    assert session.phase is Phase.CALIBRATING
    reply, _ = calibrate(session, t)
    assert reply.messages[0].attempt == 2


def test_restart_discards_the_failed_attempt_samples():

    class Failing(FakeCalibration):
        outcome, reason = "failed", "too_few_points"

    session = started(calibration_factory=Failing)
    calibrate(session)
    calibration = session._calibration

    session.receive(dump({"type": "calibration_restart"}))

    assert calibration.restarts == 1
    assert sum(calibration.samples.values()) == 0


def test_the_last_failed_attempt_abandons_the_session():

    class Failing(FakeCalibration):
        outcome, reason = "failed", "missing_row_or_column"

    session = started(Settings(max_calibration_attempts=2), calibration_factory=Failing)
    _, t = calibrate(session)
    session.receive(dump({"type": "calibration_restart"}))

    reply, _ = calibrate(session, t)

    assert types(reply) == ["calibration_status", "error", "abandoned"]
    assert reply.messages[0].attempt == 2
    assert reply.messages[1].code == "calibration_failed"
    assert reply.messages[2].reason == "calibration_failed"
    assert reply.close_code == protocol.CLOSE_NORMAL
    assert session.outcome.reason == "calibration_failed"


def test_restart_without_a_failed_calibration_is_out_of_order():

    assert started().receive(dump({"type": "calibration_restart"})).messages[0].code == "out_of_order"


def test_calibration_done_before_ready_is_out_of_order():

    assert started().receive(dump({"type": "calibration_done"})).messages[0].code == "out_of_order"


def test_calibration_samples_and_model_are_dropped_when_the_session_ends():

    session = reading_session()
    assert session._model is not None

    session.receive(dump({"type": "quit"}))

    assert session._model is None
    assert session._calibration is None


# --- reading ------------------------------------------------------------------

def read(session, cells, t, frames_per_cell=25):
    """Holds the gaze on each (x, y) for `frames_per_cell` frames; returns all
    messages sent and the next timestamp."""

    sent = []

    for gaze in cells:
        FakeCalibration.model.gaze = gaze
        for _ in range(frames_per_cell):
            sent.extend(session.receive(frame(t)).messages)
            t += 33.0

    return sent, t


CELL_CENTRES = {(0, 0): (0.25, 0.25), (0, 1): (0.75, 0.25), (1, 0): (0.25, 0.75), (1, 1): (0.75, 0.75)}


def test_reading_starts_on_the_first_cell_and_completes_on_the_last():

    session = reading_session()
    t = 100000.0

    sent, _ = read(session, [CELL_CENTRES[c] for c in [(0, 0), (0, 1), (1, 0), (1, 1)]], t)

    assert types_of(sent) == ["reading_started", "fixation", "fixation", "fixation", "fixation", "completed"]
    fixations = [(m.row, m.col) for m in sent if m.type == "fixation"]
    assert fixations == [(0, 0), (0, 1), (1, 0), (1, 1)]
    result = sent[-1].result
    assert result.saccades == 3
    assert [(c.row, c.col) for c in result.sequence] == fixations
    assert session.outcome.kind == "completed"
    assert session.outcome.result["regressions"] == 0


def types_of(messages):

    return [m.type for m in messages]


def test_the_close_code_is_normal_on_completion():

    session = reading_session()

    reply = None
    t = 100000.0
    for gaze in [CELL_CENTRES[c] for c in [(0, 0), (1, 1)]]:
        FakeCalibration.model.gaze = gaze
        for _ in range(25):
            reply = session.receive(frame(t))
            t += 33.0
            if reply.close_code is not None:
                break

    assert reply.close_code == protocol.CLOSE_NORMAL
    assert reply.messages[-1].type == "completed"


def test_fixations_before_the_first_cell_are_not_reported():

    session = reading_session()

    sent, _ = read(session, [CELL_CENTRES[(1, 0)]], 100000.0)

    assert sent == []


def test_staying_on_a_cell_reports_it_once():

    session = reading_session()

    sent, _ = read(session, [CELL_CENTRES[(0, 0)]], 100000.0, frames_per_cell=40)

    assert types_of(sent) == ["reading_started", "fixation"]


def test_a_gaze_off_every_cell_reports_nothing():

    session = reading_session()

    sent, _ = read(session, [(0.99, 0.99)], 100000.0, frames_per_cell=20)

    assert sent == []


def test_the_fixation_time_is_the_browsers_frame_time():

    session = reading_session()

    sent, _ = read(session, [CELL_CENTRES[(0, 0)]], 100000.0)

    fixation = next(m for m in sent if m.type == "fixation")
    assert fixation.t >= 100000.0 + 150.0
    assert fixation.t % 33.0 == pytest.approx(100000.0 % 33.0)


def test_frames_without_a_face_are_skipped_while_reading():

    session = reading_session()
    message = frame_dict(100000.0)
    message["iris"][0] = {"x": 1.4, "y": 0.4}
    message["nose"] = {"x": 1.4, "y": 0.4}

    assert session.receive(dump(message)).messages == []


def test_a_tagged_frame_while_reading_is_ignored():

    session = reading_session()

    assert session.receive(frame(100000.0, CALIBRATION_POINTS[0])).messages == []


# --- ending -------------------------------------------------------------------

@pytest.mark.parametrize("message, reason", [("quit", "quit"), ("viewport_changed", "viewport_changed")])
def test_quit_and_viewport_change_abandon_the_session(message, reason):

    session = reading_session()

    reply = session.receive(dump({"type": message}))

    assert [m.reason for m in reply.messages] == [reason]
    assert reply.close_code == protocol.CLOSE_NORMAL
    assert session.outcome.kind == "abandoned"
    assert session.outcome.reason == reason


def test_a_timeout_abandons_the_session_with_4408():

    session = started()

    reply = session.timeout()

    assert reply.messages[0].reason == "frame_timeout"
    assert reply.close_code == protocol.CLOSE_TIMEOUT
    assert session.outcome.reason == "frame_timeout"


def test_a_timeout_before_hello_only_closes():

    session = make_session()

    reply = session.timeout()

    assert reply.messages == []
    assert reply.close_code == protocol.CLOSE_TIMEOUT
    assert session.outcome is None


def test_a_dropped_socket_abandons_the_session():

    session = started()

    session.socket_closed()

    assert session.outcome.reason == "socket_closed"


def test_a_dropped_socket_after_completion_changes_nothing():

    session = reading_session()
    read(session, [CELL_CENTRES[(0, 0)], CELL_CENTRES[(1, 1)]], 100000.0)
    assert session.outcome.kind == "completed"

    session.socket_closed()

    assert session.outcome.kind == "completed"


def test_nothing_is_handled_after_the_session_ended():

    session = reading_session()
    session.receive(dump({"type": "quit"}))

    reply = session.receive(frame(1.0))

    assert reply.messages == [] and reply.close_code is None


def test_outgoing_messages_pass_the_protocol_schemas():

    session = started()
    reply, _ = calibrate(session)

    for message in reply.messages:
        assert protocol.parse_server_message(protocol.serialize(message)) == message


# --- real calibration -----------------------------------------------------------

def test_a_full_session_with_the_real_calibration_and_gaze_model():
    """Features follow the target linearly, so the fitted model should put the
    gaze in the right quadrant."""

    session = make_session(calibration_factory=Calibration)
    session.receive(hello())
    session.receive(quadrant_layout())

    def shifted(point):
        return {"shift": (point[0] - 0.5) * 0.2}

    t = 0.0
    reply = None
    for index, point in enumerate(CALIBRATION_POINTS):
        for _ in range(CALIBRATION_SAMPLES_PER_POINT if index == LAST_POINT else 3):
            message = frame_dict(t, point, **shifted(point))
            message["nose"] = {"x": 0.5, "y": 0.4 + 0.2 * point[1]}
            reply = session.receive(dump(message))
            t += 33.0

    assert reply.messages[0].outcome == "ready"

    session.receive(dump({"type": "calibration_done"}))

    sent = []
    for cell in [(0, 0), (1, 1)]:
        point = CELL_CENTRES[cell]
        for _ in range(25):
            message = frame_dict(t, **shifted(point))
            message["nose"] = {"x": 0.5, "y": 0.4 + 0.2 * point[1]}
            sent.extend(session.receive(dump(message)).messages)
            t += 33.0

    assert [m.type for m in sent] == ["reading_started", "fixation", "fixation", "completed"]


# --- frame-rate limit -----------------------------------------------------------

def test_the_limiter_lets_a_steady_30_fps_browser_through_for_a_minute():

    clock = FakeClock(0.0)
    limiter = FrameRateLimiter(30, clock)

    for _ in range(30 * 60):
        clock.now += 1 / 30
        assert limiter.allow()


def test_the_limiter_tolerates_a_batch_of_a_second_of_frames():

    limiter = FrameRateLimiter(30, FakeClock(0.0))

    assert all(limiter.allow() for _ in range(60))


def test_the_limiter_refuses_a_sustained_flood_and_recovers_when_it_stops():

    clock = FakeClock(0.0)
    limiter = FrameRateLimiter(30, clock)

    allowed = 0
    for _ in range(500):
        clock.now += 1 / 300
        allowed += limiter.allow()

    assert allowed < 200
    assert not limiter.allow()

    clock.now += 2.0
    assert limiter.allow()


def test_a_frame_over_the_limit_abandons_the_session():

    clock = FakeClock(0.0)
    session = Session(Settings(), authenticate, FakeCalibration, FrameRateLimiter(1, clock))
    session.receive(hello())
    session.receive(quadrant_layout())

    replies = [session.receive(frame(float(i), (0.1, 0.1))) for i in range(3)]

    assert types(replies[2]) == ["error", "abandoned"]
    assert replies[2].messages[0].code == "rate_limited"
    assert replies[2].messages[1].reason == "rate_limited"
    assert replies[2].close_code == protocol.CLOSE_RATE_LIMITED
    assert session.outcome.reason == "rate_limited"


# --- diagnostics ----------------------------------------------------------------

class ListHandler(logging.Handler):

    def __init__(self):
        super().__init__(logging.INFO)
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def session_log():
    """The records the Session logger emits during a test. It listens on that logger directly, because
    other tests change its level and leave handlers on it, which caplog would pick up."""

    logger = logging.getLogger("app.sessions.session_manager")
    handler = ListHandler()
    level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    yield handler.records

    logger.removeHandler(handler)
    logger.setLevel(level)


def events(session_log, name):
    """Messages of the structured log lines called `name`, as dicts of strings."""

    found = []

    for record in session_log:
        message = record.getMessage()
        if message.split(" ")[0] == name:
            found.append(dict(part.split("=", 1) for part in message.split(" ")[1:]))

    return found


def test_calibration_judging_is_logged_with_the_number_of_usable_points(session_log):

    started_session = started()

    calibrate(started_session)

    [judged] = events(session_log, "calibration_judged")
    assert judged["outcome"] == "ready"
    assert judged["attempt"] == "1"
    assert judged["ok_points"] == "16"


def test_a_stalled_reading_session_reports_where_it_is_stuck(session_log):

    session = reading_session()

    # Looks steadily at a Cell that is not the first one, for longer than one report interval.
    read(session, [CELL_CENTRES[(1, 0)]], 100000.0, frames_per_cell=200)
    session.receive(dump({"type": "quit"}))

    [progress] = events(session_log, "reading_progress")
    assert progress["reading_started"] == "False"
    assert int(progress["fixation_frames"]) > 0
    assert progress["cells_fixated_before_start"] == "1"
    assert progress["nearest_to_first_cell"] == "0.25"

    [ended] = events(session_log, "session_ended")
    assert ended["reason"] == "quit"
    assert ended["frames"] == "200"
    assert ended["reading_started"] == "False"


def test_reading_progress_is_reported_once_per_interval_not_per_frame(session_log):

    session = reading_session()

    read(session, [CELL_CENTRES[(1, 0)]], 100000.0, frames_per_cell=100)   # about 3.3 s

    assert events(session_log, "reading_progress") == []


def test_a_gaze_off_screen_and_missing_faces_are_counted(session_log):

    session = reading_session()

    read(session, [(1.2, 0.5)], 100000.0, frames_per_cell=10)
    message = frame_dict(101000.0)
    message["iris"][0] = {"x": 1.4, "y": 0.4}
    message["nose"] = {"x": 1.4, "y": 0.4}
    session.receive(dump(message))
    session.receive(dump({"type": "quit"}))

    [ended] = events(session_log, "session_ended")
    assert ended["gaze_off_screen_frames"] == "10"
    assert ended["no_face_frames"] == "1"
    assert ended["frames"] == "11"


def test_a_completed_session_reports_that_reading_started(session_log):

    session = reading_session()

    read(session, [CELL_CENTRES[c] for c in [(0, 0), (0, 1), (1, 0), (1, 1)]], 100000.0)

    [ended] = events(session_log, "session_ended")
    assert ended["outcome"] == "completed"
    assert ended["reading_started"] == "True"
    assert ended["cells_fixated"] == "4"
    assert events(session_log, "reading_progress") == []


def test_a_session_that_never_reached_reading_logs_no_reading_counters(session_log):

    session = started()

    session.receive(dump({"type": "quit"}))

    [ended] = events(session_log, "session_ended")
    assert "frames" not in ended


def test_diagnostics_never_log_gaze_coordinates_or_features(session_log):

    session = reading_session()

    read(session, [CELL_CENTRES[(1, 0)]], 100000.0, frames_per_cell=200)
    session.receive(dump({"type": "quit"}))

    logged = " ".join(record.getMessage() for record in session_log)
    for forbidden in ("gaze=", "position", "landmarks", "features", "iris", "matrix", "0.75"):
        assert forbidden not in logged


class ScaledModel(FixedModel):
    """A model that also reports how far the frame is from calibration: `z` is what it says."""

    def __init__(self):
        super().__init__()
        self.z = np.zeros(len(model_columns(FEATURE_SIZE_V2)))

    def standardize(self, X):
        return np.array([self.z for _ in X])


class ScaledCalibration(FakeCalibration):

    model = ScaledModel()


def test_reading_reports_how_far_the_features_are_from_calibration(session_log):

    session = reading_session(calibration_factory=ScaledCalibration)
    ScaledCalibration.model.gaze = CELL_CENTRES[(1, 0)]
    ScaledCalibration.model.z = np.zeros(len(model_columns(FEATURE_SIZE_V2)))
    ScaledCalibration.model.z[-1] = -35.0   # the last model column: an eye centre, far from calibration

    t = 100000.0
    for _ in range(40):
        session.receive(frame(t))
        t += 33.0
    session.receive(dump({"type": "quit"}))

    [ended] = events(session_log, "session_ended")
    assert ended["frames_out_of_range"] == "40"
    assert ended["max_abs_z"] == "35.0"
    assert ended["worst_feature_group"] == "eye_centre"


def test_a_model_without_standardize_still_reads_and_reports_no_scale(session_log):

    session = reading_session()

    read(session, [CELL_CENTRES[(1, 0)]], 100000.0, frames_per_cell=10)
    session.receive(dump({"type": "quit"}))

    [ended] = events(session_log, "session_ended")
    assert ended["max_abs_z"] == "0.0"
    assert ended["worst_feature_group"] == "None"


def test_a_shifted_head_no_longer_moves_the_estimate_of_a_real_calibrated_model(session_log):
    """End to end with the real Calibration and GazeModel. The head sits still in calibration and then
    2 units closer: head pose is not a model input, so nothing is out of range."""

    session = started(calibration_factory=Calibration)
    t = 0.0
    for index, point in enumerate(CALIBRATION_POINTS):
        for k in range(CALIBRATION_SAMPLES_PER_POINT):
            # Looking at different dots moves the iris; the head stays almost still.
            message = frame_dict(t, point, shift=(point[0] - 0.5) * 0.1)
            message["matrix"][2][3] = -35.0 + 0.001 * ((index + k) % 3)
            session.receive(dump(message))
            t += 33.0
    session.receive(dump({"type": "calibration_done"}))

    for _ in range(30):
        message = frame_dict(t)
        message["matrix"][2][3] = -33.0
        message["matrix"][0][2] = 0.4          # and turned
        message["nose"] = {"x": 0.55, "y": 0.6}
        session.receive(dump(message))
        t += 33.0
    session.receive(dump({"type": "quit"}))

    [ended] = events(session_log, "session_ended")
    assert ended["frames_out_of_range"] == "0"
    assert float(ended["max_abs_z"]) < 3
    assert ended["worst_feature_group"] == "None"


def test_head_pose_and_face_position_do_not_change_what_the_model_sees():

    session = started()

    base = frame_dict(1000.0)
    moved = frame_dict(1033.0)
    moved["matrix"] = [[0.9, 0.3, -0.1, 4.0], [-0.3, 0.9, 0.2, -3.0], [0.1, -0.2, 0.9, -20.0], [0, 0, 0, 1]]
    moved["nose"] = {"x": 0.7, "y": 0.8}

    a = session._features(protocol.Frame.model_validate(base))
    b = session._features(protocol.Frame.model_validate(moved))

    assert list(a) == list(b)


def test_the_model_sees_only_the_eye_features():

    session = started()

    features = session._features(protocol.Frame.model_validate(frame_dict(1000.0, eye_centres=True)))

    assert len(features) == len(model_columns(FEATURE_SIZE_V2))
    assert len(features) == 10


def test_a_version_1_session_has_no_eye_centre_columns():

    session = make_session()
    session.receive(hello(version=1))
    session.receive(quadrant_layout())

    features = session._features(protocol.Frame.model_validate(frame_dict(1000.0)))

    assert len(features) == 6


def test_a_frame_without_a_face_gives_no_features():

    session = started()
    message = frame_dict(1000.0)
    message["iris"][0] = {"x": 1.4, "y": 0.4}

    assert session._features(protocol.Frame.model_validate(message)) is None
