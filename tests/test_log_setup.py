import logging

from log_setup import format_event, log_event


def test_format_event_includes_plain_fields():

    line = format_event("session_ended", session_id="abc", reason="quit")

    assert line == "session_ended session_id=abc reason=quit"


def test_format_event_drops_sensitive_fields():

    line = format_event(
        "frame_received",
        session_id="abc",
        token="secret-token",
        landmarks=[[0.1, 0.2]],
        features=[1.0, 2.0],
        result={"cpm": 99},
    )

    assert line == "frame_received session_id=abc"
    assert "secret-token" not in line
    assert "0.1" not in line


def test_log_event_emits_one_scrubbed_record(caplog):

    logger = logging.getLogger("ocurate.test")

    with caplog.at_level(logging.INFO, logger="ocurate.test"):
        log_event(logger, "session_started", session_id="abc", api_key="hunter2")

    assert caplog.messages == ["session_started session_id=abc"]
