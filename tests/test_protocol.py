import copy
import json
import re
from pathlib import Path

import pytest

import protocol
from protocol import ProtocolError, parse_client_message, parse_server_message, serialize


def landmarks(count, value=0.5):
    return [{"x": value, "y": value} for _ in range(count)]


def frame(**overrides):
    message = {
        "type": "frame",
        "t": 1234.5,
        "iris": landmarks(8),
        "eye_corners": landmarks(8),
        "nose": {"x": 0.5, "y": 0.6},
        "matrix": [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, -30.0], [0.0, 0.0, 0.0, 1.0]],
    }
    message.update(overrides)
    return message


def cell(row, col, **overrides):
    rect = {"row": row, "col": col, "x": col * 0.1, "y": row * 0.1, "w": 0.1, "h": 0.1}
    rect.update(overrides)
    return rect


def layout(**overrides):
    message = {
        "type": "layout",
        "viewport": {"width": 1280, "height": 720},
        "cells": [cell(0, 0), cell(0, 1), cell(1, 0)],
    }
    message.update(overrides)
    return message


def points(states=None):
    return [{"index": i, "state": "ok", "samples": 10} for i in range(16)]


def calibration_status(**overrides):
    message = {"type": "calibration_status", "points": points(), "outcome": "ready",
               "attempt": 1, "max_attempts": 3}
    message.update(overrides)
    return message


RESULT = {"elapsed_seconds": 12.5, "cpm": 240.0, "wpm": 48.0, "saccades": 20,
          "regressions": 2, "skipped_characters": 1, "sequence": [{"row": 0, "col": 0}]}

EYE_CENTRES = [{"x": 0.35, "y": 0.4, "confidence": 0.8}, {"x": 0.65, "y": 0.4, "confidence": 0.0}]

CLIENT_VALID = {
    "hello": {"type": "hello", "version": 1, "token": "abc"},
    "hello v2": {"type": "hello", "version": 2, "token": "abc"},
    "layout": layout(),
    "frame": frame(),
    "frame with target": frame(target={"x": 0.1, "y": 0.9}),
    "frame with eye_centres": frame(eye_centres=EYE_CENTRES),
    "calibration_restart": {"type": "calibration_restart"},
    "calibration_done": {"type": "calibration_done"},
    "viewport_changed": {"type": "viewport_changed"},
    "quit": {"type": "quit"},
}

SERVER_VALID = {
    "hello_ack": {"type": "hello_ack", "version": 1, "supported": [1]},
    "calibration_status ready": calibration_status(),
    "calibration_status in progress": calibration_status(outcome=None),
    "calibration_status failed": calibration_status(outcome="failed", reason="too_few_points"),
    "reading_started": {"type": "reading_started"},
    "fixation": {"type": "fixation", "row": 0, "col": 3, "t": 99.0},
    "completed": {"type": "completed", "result": RESULT},
    "abandoned": {"type": "abandoned", "reason": "viewport_changed"},
    "error": {"type": "error", "code": "invalid_message", "message": "frame.iris"},
    "error unsupported_version": {"type": "error", "code": "unsupported_version",
                                  "message": "unsupported", "supported": [1]},
}


def wire(message):
    return json.dumps(message)


@pytest.mark.parametrize("name", CLIENT_VALID)
def test_valid_client_messages_parse(name):
    message = CLIENT_VALID[name]
    assert parse_client_message(wire(message)).type == message["type"]


@pytest.mark.parametrize("name", SERVER_VALID)
def test_valid_server_messages_parse_and_round_trip(name):
    parsed = parse_server_message(wire(SERVER_VALID[name]))
    assert parse_server_message(serialize(parsed)) == parsed


def with_change(base, path, value):
    message = copy.deepcopy(base)
    target = message
    for key in path[:-1]:
        target = target[key]
    if value is DELETE:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return message


DELETE = object()

CLIENT_INVALID = {
    # hello
    "hello missing token": with_change(CLIENT_VALID["hello"], ["token"], DELETE),
    "hello empty token": with_change(CLIENT_VALID["hello"], ["token"], ""),
    "hello version zero": with_change(CLIENT_VALID["hello"], ["version"], 0),
    "hello version as string": with_change(CLIENT_VALID["hello"], ["version"], "1"),
    "hello extra field": with_change(CLIENT_VALID["hello"], ["extra"], 1),
    # layout
    "layout no cells": with_change(CLIENT_VALID["layout"], ["cells"], []),
    "layout duplicate cell": with_change(CLIENT_VALID["layout"], ["cells"], [cell(0, 0), cell(0, 0)]),
    "layout rect outside viewport": with_change(CLIENT_VALID["layout"], ["cells"], [cell(0, 0, x=0.95)]),
    "layout rect zero width": with_change(CLIENT_VALID["layout"], ["cells"], [cell(0, 0, w=0)]),
    "layout rect negative x": with_change(CLIENT_VALID["layout"], ["cells"], [cell(0, 0, x=-0.1)]),
    "layout negative row": with_change(CLIENT_VALID["layout"], ["cells"], [cell(-1, 0)]),
    "layout zero viewport": with_change(CLIENT_VALID["layout"], ["viewport", "width"], 0),
    "layout missing viewport": with_change(CLIENT_VALID["layout"], ["viewport"], DELETE),
    # frame
    "frame eye_centres one": with_change(CLIENT_VALID["frame with eye_centres"], ["eye_centres"], EYE_CENTRES[:1]),
    "frame eye_centres three": with_change(CLIENT_VALID["frame with eye_centres"], ["eye_centres"], EYE_CENTRES * 2),
    "frame eye_centres no confidence": with_change(CLIENT_VALID["frame with eye_centres"], ["eye_centres", 0, "confidence"], DELETE),
    "frame eye_centres confidence above 1": with_change(CLIENT_VALID["frame with eye_centres"], ["eye_centres", 0, "confidence"], 1.01),
    "frame eye_centres confidence below 0": with_change(CLIENT_VALID["frame with eye_centres"], ["eye_centres", 1, "confidence"], -0.1),
    "frame eye_centres out of range": with_change(CLIENT_VALID["frame with eye_centres"], ["eye_centres", 0, "x"], 1.6),
    "frame eye_centres extra field": with_change(CLIENT_VALID["frame with eye_centres"], ["eye_centres", 0, "z"], 0.1),
    "frame iris too few": with_change(CLIENT_VALID["frame"], ["iris"], landmarks(7)),
    "frame iris too many": with_change(CLIENT_VALID["frame"], ["iris"], landmarks(9)),
    "frame corners too few": with_change(CLIENT_VALID["frame"], ["eye_corners"], landmarks(4)),
    "frame landmark below range": with_change(CLIENT_VALID["frame"], ["nose", "x"], -0.51),
    "frame landmark above range": with_change(CLIENT_VALID["frame"], ["iris", 3, "y"], 1.51),
    "frame matrix 3x4": with_change(CLIENT_VALID["frame"], ["matrix"], [[0.0] * 4] * 3),
    "frame matrix 4x3": with_change(CLIENT_VALID["frame"], ["matrix"], [[0.0] * 3] * 4),
    "frame matrix flat": with_change(CLIENT_VALID["frame"], ["matrix"], [0.0] * 16),
    "frame missing t": with_change(CLIENT_VALID["frame"], ["t"], DELETE),
    "frame negative t": with_change(CLIENT_VALID["frame"], ["t"], -1),
    "frame missing nose": with_change(CLIENT_VALID["frame"], ["nose"], DELETE),
    "frame extra z": with_change(CLIENT_VALID["frame"], ["nose", "z"], 0.1),
    "frame extra field": with_change(CLIENT_VALID["frame"], ["blendshapes"], []),
    "frame target outside": with_change(CLIENT_VALID["frame"], ["target"], {"x": 1.2, "y": 0.5}),
    # no-field messages
    "quit extra field": {"type": "quit", "reason": "x"},
    "calibration_done extra field": {"type": "calibration_done", "x": 1},
    "calibration_restart extra field": {"type": "calibration_restart", "x": 1},
    "viewport_changed extra field": {"type": "viewport_changed", "x": 1},
    # envelope
    "unknown type": {"type": "dance"},
    "missing type": {"version": 1},
    "server message sent by browser": {"type": "reading_started"},
}


@pytest.mark.parametrize("name", CLIENT_INVALID)
def test_invalid_client_messages_are_rejected(name):
    with pytest.raises(ProtocolError) as caught:
        parse_client_message(wire(CLIENT_INVALID[name]))
    assert caught.value.code == "invalid_message"


@pytest.mark.parametrize("raw", [
    "not json", "", "[]", "null", "42", '"frame"',
])
def test_non_object_payloads_are_rejected(raw):
    with pytest.raises(ProtocolError):
        parse_client_message(raw)


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("where", ["t", "iris", "nose", "matrix", "target"])
def test_non_finite_numbers_are_rejected(literal, where):
    text = wire(frame(target={"x": 0.5, "y": 0.5}))
    replacements = {
        "t": ('"t": 1234.5', f'"t": {literal}'),
        "iris": ('"iris": [{"x": 0.5', f'"iris": [{{"x": {literal}'),
        "nose": ('"nose": {"x": 0.5', f'"nose": {{"x": {literal}'),
        "matrix": ('"matrix": [[1.0', f'"matrix": [[{literal}'),
        "target": ('"target": {"x": 0.5', f'"target": {{"x": {literal}'),
    }
    old, new = replacements[where]
    assert old in text
    with pytest.raises(ProtocolError):
        parse_client_message(text.replace(old, new, 1))


def test_landmark_range_boundaries_are_accepted():
    message = frame(nose={"x": -0.5, "y": 1.5}, iris=landmarks(8, 1.5), eye_corners=landmarks(8, -0.5))
    parse_client_message(wire(message))


def test_values_are_not_coerced_from_strings():
    with pytest.raises(ProtocolError):
        parse_client_message(wire(frame(t="12.5")))
    with pytest.raises(ProtocolError):
        parse_client_message(wire(frame(nose={"x": "0.5", "y": 0.5})))


def test_integer_numbers_are_accepted_for_floats():
    parse_client_message(wire(frame(t=1234, matrix=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])))


def test_error_names_fields_but_never_values():
    secret = "super-secret-token"
    message = with_change(CLIENT_VALID["hello"], ["version"], secret)
    with pytest.raises(ProtocolError) as caught:
        parse_client_message(wire(message))
    assert caught.value.fields == ["hello.version"]
    assert secret not in str(caught.value)


def test_frame_error_path_points_at_the_bad_landmark():
    with pytest.raises(ProtocolError) as caught:
        parse_client_message(wire(with_change(CLIENT_VALID["frame"], ["iris", 3, "y"], 9.0)))
    assert caught.value.fields == ["frame.iris.3.y"]


SERVER_INVALID = {
    "hello_ack missing supported": with_change(SERVER_VALID["hello_ack"], ["supported"], DELETE),
    "status 15 points": with_change(SERVER_VALID["calibration_status ready"], ["points"], points()[:15]),
    "status 17 points": with_change(SERVER_VALID["calibration_status ready"], ["points"],
                                    points() + [{"index": 16, "state": "ok", "samples": 1}]),
    "status duplicate index": with_change(SERVER_VALID["calibration_status ready"], ["points", 1, "index"], 0),
    "status unknown state": with_change(SERVER_VALID["calibration_status ready"], ["points", 0, "state"], "done"),
    "status negative samples": with_change(SERVER_VALID["calibration_status ready"], ["points", 0, "samples"], -1),
    "status failed without reason": calibration_status(outcome="failed"),
    "status reason without failure": calibration_status(reason="too_few_points"),
    "status attempt above max": calibration_status(attempt=4),
    "status attempt zero": calibration_status(attempt=0),
    "fixation missing col": with_change(SERVER_VALID["fixation"], ["col"], DELETE),
    "fixation negative row": with_change(SERVER_VALID["fixation"], ["row"], -1),
    "reading_started extra field": {"type": "reading_started", "x": 1},
    "completed missing cpm": with_change(SERVER_VALID["completed"], ["result", "cpm"], DELETE),
    "completed negative wpm": with_change(SERVER_VALID["completed"], ["result", "wpm"], -1.0),
    "completed extra result field": with_change(SERVER_VALID["completed"], ["result", "extra"], 1),
    "abandoned unknown reason": {"type": "abandoned", "reason": "bored"},
    "abandoned missing reason": {"type": "abandoned"},
    "error unknown code": {"type": "error", "code": "oops", "message": "x"},
    "error missing message": {"type": "error", "code": "invalid_message"},
    "unknown type": {"type": "dance"},
}


@pytest.mark.parametrize("name", SERVER_INVALID)
def test_invalid_server_messages_are_rejected(name):
    with pytest.raises(ProtocolError):
        parse_server_message(wire(SERVER_INVALID[name]))


def test_every_message_type_has_valid_and_invalid_examples():
    client_types = {"hello", "layout", "frame", "calibration_restart", "calibration_done",
                    "viewport_changed", "quit"}
    server_types = {"hello_ack", "calibration_status", "reading_started", "fixation",
                    "completed", "abandoned", "error"}
    assert {m["type"] for m in CLIENT_VALID.values()} == client_types
    assert {m["type"] for m in SERVER_VALID.values()} == server_types
    # Every type has at least one invalid example (the no-field messages via extra fields).
    assert {m.get("type") for m in CLIENT_INVALID.values()} >= client_types
    assert {m.get("type") for m in SERVER_INVALID.values()} >= server_types


def test_version_negotiation():
    assert protocol.SUPPORTED_VERSIONS == (1, 2)
    assert protocol.negotiate_version(1) == 1
    assert protocol.negotiate_version(2) == 2
    assert protocol.negotiate_version(3) is None
    assert protocol.negotiate_version(0) is None


def test_close_codes_and_reasons():
    assert (protocol.CLOSE_NORMAL, protocol.CLOSE_INVALID_MESSAGE, protocol.CLOSE_INVALID_TOKEN,
            protocol.CLOSE_TIMEOUT, protocol.CLOSE_UNSUPPORTED_VERSION) == (1000, 4400, 4401, 4408, 4409)
    assert "calibration_failed" in protocol.ABANDON_REASONS
    assert "unsupported_version" in protocol.ERROR_CODES


# --- the example transcript ----------------------------------------------------

TRANSCRIPT = Path(__file__).resolve().parent.parent / "docs" / "session-transcript.md"
BLOCK = re.compile(r"```json (client|server)\n(.*?)\n```", re.S)


def transcript_messages():
    return [(side, body) for side, body in BLOCK.findall(TRANSCRIPT.read_text())]


def test_transcript_messages_all_validate():
    messages = transcript_messages()
    assert messages
    for side, body in messages:
        parse = parse_client_message if side == "client" else parse_server_message
        parse(body)


def test_transcript_covers_a_complete_session():
    types = [(side, json.loads(body)["type"]) for side, body in transcript_messages()]
    seen = {message_type for _, message_type in types}
    assert {"hello", "hello_ack", "layout", "calibration_status", "calibration_done",
            "reading_started", "fixation", "completed"} <= seen
    assert any(side == "client" and t == "frame" for side, t in types)
    assert types[0] == ("client", "hello")
    assert types[-1] == ("server", "completed")
    frames = [json.loads(body) for side, body in transcript_messages()
              if side == "client" and json.loads(body)["type"] == "frame"]
    assert any("target" in f for f in frames) and any("target" not in f for f in frames)
