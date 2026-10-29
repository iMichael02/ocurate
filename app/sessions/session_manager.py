"""The live state of one WebSocket Session: a state machine that turns the
browser's messages into the service's replies. It does no I/O, so tests can
drive it with plain messages; ws_api.py connects it to a real socket.

Phases: hello -> layout -> calibration (retried on failure) -> reading, then
the Session ends completed or abandoned. See docs/websocket-protocol.md.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

import numpy as np

from app.analysis.calibration import CALIBRATION_POINTS, Calibration, target_index
from app.analysis.cell_layout import cell_at
from app.analysis.eye_features import extract_features
from app.analysis.fixation_detector import FixationDetector
from app.analysis.gaze_smoother import GazeSmoother
from app.log_setup import log_event
from app.analysis.reading_session import ReadingSession
from app.schemas import protocol
from app.sessions.tokens import TokenError

logger = logging.getLogger(__name__)

# The last target is judged once it has had this many tagged frames. The
# browser sends about 30 per target, minus a short settling period.
CALIBRATION_SAMPLES_PER_POINT = 20
# While a target is being collected, report progress every this many frames.
STATUS_EVERY_FRAMES = 5

CLOSE_INTERNAL_ERROR = 1011


class PassageUnavailable(Exception):
    """The Passage for a valid token could not be loaded (e.g. the database
    is down). The Session cannot start; the token is spent."""


class Phase(Enum):
    HELLO = "hello"
    LAYOUT = "layout"
    CALIBRATING = "calibrating"
    CALIBRATION_FAILED = "calibration_failed"
    CALIBRATION_READY = "calibration_ready"
    READING = "reading"
    ENDED = "ended"


@dataclass(frozen=True)
class Authenticated:

    session_id: str
    passage_id: str
    passage: Any


@dataclass
class Reply:
    """What to send, in order, and the close code if the socket should close."""

    messages: list = field(default_factory=list)
    close_code: Optional[int] = None


@dataclass(frozen=True)
class Outcome:
    """How a Session ended: `completed` with a result, or `abandoned` with a
    reason. This is what the signed callback reports to the web server."""

    kind: str
    session_id: str
    passage_id: str
    reason: Optional[str] = None
    result: Optional[dict] = None


class Session:

    def __init__(self, settings, authenticate: Callable[[str], Authenticated],
                 calibration_factory=Calibration):
        """`authenticate(token)` returns an Authenticated or raises TokenError
        (bad token) or PassageUnavailable."""

        self._settings = settings
        self._authenticate = authenticate
        self._calibration_factory = calibration_factory

        self.phase = Phase.HELLO
        self.outcome = None
        self.session_id = None

        self._auth = None
        self._version = None
        self._cells = None
        self._last_t = None

        self._calibration = None
        self._attempt = 1
        self._current_target = None
        self._frames_at_target = 0
        self._last_target_frames = 0
        self._model = None

        self._smoother = None
        self._detector = None
        self._reading = None
        self._current_cell = None

    # --- entry points ---------------------------------------------------------

    def receive(self, raw):
        """Handles one text frame from the browser."""

        if self.phase is Phase.ENDED:
            return Reply()

        if not isinstance(raw, str) or len(raw.encode("utf-8")) > self._settings.max_message_bytes:
            return self._violation("invalid_message", "message is not text or is too large")

        try:
            message = protocol.parse_client_message(raw)
        except protocol.ProtocolError as error:
            return self._violation("invalid_message", str(error))

        if self.phase is Phase.HELLO:
            return self._on_hello(message)

        if isinstance(message, protocol.Quit):
            return self._abandon("quit", protocol.CLOSE_NORMAL)

        if isinstance(message, protocol.ViewportChanged):
            return self._abandon("viewport_changed", protocol.CLOSE_NORMAL)

        if isinstance(message, protocol.Frame):
            return self._on_frame(message)

        if isinstance(message, protocol.Layout):
            return self._on_layout(message)

        if isinstance(message, protocol.CalibrationRestart):
            return self._on_calibration_restart()

        if isinstance(message, protocol.CalibrationDone):
            return self._on_calibration_done()

        return self._violation("out_of_order", f"{message.type} is not allowed now")

    def timeout(self):
        """No message for `session_inactivity_seconds`."""

        if self.phase is Phase.ENDED:
            return Reply()

        if self._auth is None:
            return self._end_unauthenticated(protocol.CLOSE_TIMEOUT)

        return self._abandon("frame_timeout", protocol.CLOSE_TIMEOUT)

    def socket_closed(self):
        """The browser went away. Nothing can be sent."""

        if self.phase is not Phase.ENDED and self._auth is not None:
            self._abandon("socket_closed", protocol.CLOSE_NORMAL)

        self._release()
        self.phase = Phase.ENDED

        return Reply()

    # --- handshake ------------------------------------------------------------

    def _on_hello(self, message):

        if not isinstance(message, protocol.Hello):
            return self._violation("out_of_order", "hello must come first")

        # The version is checked before the token.
        version = protocol.negotiate_version(message.version)

        if version is None:
            error = protocol.Error(type="error", code="unsupported_version",
                                   message=f"Protocol version {message.version} is not supported",
                                   supported=list(protocol.SUPPORTED_VERSIONS))
            return self._end_unauthenticated(protocol.CLOSE_UNSUPPORTED_VERSION, error)

        try:
            self._auth = self._authenticate(message.token)
        except TokenError as error:
            log_event(logger, "session_token_refused", logging.WARNING, reason=error.code)
            return self._end_unauthenticated(
                protocol.CLOSE_INVALID_TOKEN,
                protocol.Error(type="error", code="invalid_token", message="Session token refused"))
        except PassageUnavailable:
            log_event(logger, "session_passage_unavailable", logging.ERROR)
            return self._end_unauthenticated(CLOSE_INTERNAL_ERROR)

        self._version = version
        self.session_id = self._auth.session_id
        self.phase = Phase.LAYOUT

        log_event(logger, "session_started", session_id=self.session_id, version=version)

        return Reply([protocol.HelloAck(type="hello_ack", version=version,
                                        supported=list(protocol.SUPPORTED_VERSIONS))])

    def _on_layout(self, message):

        if self.phase is not Phase.LAYOUT:
            return self._violation("out_of_order", "layout is sent once, before calibration")

        passage = self._auth.passage
        expected = {(row, col) for row in range(passage.num_rows) for col in range(passage.num_columns)}
        reported = {(cell.row, cell.col) for cell in message.cells}

        if reported != expected:
            return self._violation("invalid_message", "layout must cover every Cell of the Passage")

        self._cells = message.cells
        self._calibration = self._calibration_factory()
        self.phase = Phase.CALIBRATING

        return Reply()

    # --- frames ---------------------------------------------------------------

    def _on_frame(self, frame):

        if self.phase is Phase.LAYOUT:
            return self._violation("out_of_order", "layout must come before frames")

        if self._version == 1 and frame.eye_centres is not None:
            return self._violation("invalid_message", "eye_centres: not allowed on protocol version 1")

        if self._last_t is not None and frame.t < self._last_t:
            return self._violation("timestamp_regression", "frame time went backwards")
        self._last_t = frame.t

        if self.phase is Phase.CALIBRATING and frame.target is not None:
            return self._on_calibration_frame(frame)

        if self.phase is Phase.READING and frame.target is None:
            return self._on_reading_frame(frame)

        # Untagged frames while a dot settles, and frames still in flight
        # between phases, are expected and carry nothing for this phase.
        return Reply()

    def _features(self, frame):

        return extract_features(frame, use_eye_centres=self._version == 2)

    # --- calibration ----------------------------------------------------------

    def _on_calibration_frame(self, frame):

        index = target_index(frame.target)

        if index is None:
            return Reply()

        self._calibration.add_frame(CALIBRATION_POINTS[index], self._features(frame))

        changed = index != self._current_target
        if changed:
            self._current_target = index
            self._frames_at_target = 0
        self._frames_at_target += 1

        if index == len(CALIBRATION_POINTS) - 1:
            self._last_target_frames += 1
            if self._last_target_frames >= CALIBRATION_SAMPLES_PER_POINT:
                return self._judge_calibration()

        if changed or self._frames_at_target % STATUS_EVERY_FRAMES == 1:
            return Reply([self._status(self._calibration.progress(index))])

        return Reply()

    def _status(self, points, outcome=None, reason=None):

        return protocol.CalibrationStatus(
            type="calibration_status",
            points=[protocol.CalibrationPoint(index=p.index, state=p.state, samples=p.samples) for p in points],
            outcome=outcome,
            reason=reason,
            attempt=self._attempt,
            max_attempts=self._settings.max_calibration_attempts,
        )

    def _judge_calibration(self):

        result = self._calibration.finish()
        status = self._status(result.points, result.outcome, result.reason)

        if result.outcome == "ready":
            self._model = result.model
            # Calibration samples are never kept once the model is fitted.
            self._calibration = None
            self.phase = Phase.CALIBRATION_READY
            return Reply([status])

        if self._attempt >= self._settings.max_calibration_attempts:
            reply = self._abandon("calibration_failed", protocol.CLOSE_NORMAL)
            error = protocol.Error(type="error", code="calibration_failed", message="Calibration failed")
            reply.messages[:0] = [status, error]
            return reply

        self.phase = Phase.CALIBRATION_FAILED
        return Reply([status])

    def _on_calibration_restart(self):

        if self.phase is not Phase.CALIBRATION_FAILED:
            return self._violation("out_of_order", "calibration_restart only follows a failed calibration")

        self._attempt += 1
        self._calibration.restart()
        self._current_target = None
        self._frames_at_target = 0
        self._last_target_frames = 0
        self.phase = Phase.CALIBRATING

        return Reply()

    def _on_calibration_done(self):

        if self.phase is not Phase.CALIBRATION_READY:
            return self._violation("out_of_order", "calibration_done only follows a ready calibration")

        self._smoother = GazeSmoother()
        self._detector = FixationDetector()
        self._reading = ReadingSession(self._auth.passage)
        self._current_cell = None
        self.phase = Phase.READING

        return Reply()

    # --- reading --------------------------------------------------------------

    def _on_reading_frame(self, frame):

        features = self._features(frame)

        if features is None:
            return Reply()

        gaze = self._model.predict(np.asarray(features, dtype=float).reshape(1, -1))[0]
        gaze = self._smoother.update(gaze)

        # Timing is the browser's: frame.t is in ms, the analysis uses seconds.
        fixation = self._detector.update(gaze, frame.t / 1000.0)

        if fixation is None:
            return Reply()

        x, y = fixation["position"]
        cell = cell_at(self._cells, float(x), float(y))

        if cell is None or cell == self._current_cell:
            return Reply()

        return self._on_fixation(cell, frame.t)

    def _on_fixation(self, cell, t):

        was_started = self._reading.start_time is not None
        self._reading.register_fixation(cell[0], cell[1], t / 1000.0)

        if self._reading.start_time is None:
            # Reading starts on the first Cell; fixations elsewhere do not count yet.
            return Reply()

        self._current_cell = cell
        messages = []

        if not was_started:
            messages.append(protocol.ReadingStarted(type="reading_started"))

        messages.append(protocol.Fixation(type="fixation", row=cell[0], col=cell[1], t=t))

        if not self._reading.is_complete():
            return Reply(messages)

        result = self._reading.result()
        result["sequence"] = [{"row": row, "col": col} for row, col in result["sequence"]]
        messages.append(protocol.Completed(type="completed", result=protocol.Result(**result)))

        self._finish(Outcome("completed", self.session_id, self._auth.passage_id, result=result))

        return Reply(messages, protocol.CLOSE_NORMAL)

    # --- ending ---------------------------------------------------------------

    def _abandon(self, reason, close_code):

        self._finish(Outcome("abandoned", self.session_id, self._auth.passage_id, reason=reason))

        return Reply([protocol.Abandoned(type="abandoned", reason=reason)], close_code)

    def _violation(self, code, text):
        """A message the Session cannot accept. Before the handshake it only
        closes the socket; after it the Session ends abandoned."""

        error = protocol.Error(type="error", code=code, message=text[:500])

        if self._auth is None:
            return self._end_unauthenticated(protocol.CLOSE_INVALID_MESSAGE, error)

        reply = self._abandon("protocol_error", protocol.CLOSE_INVALID_MESSAGE)
        reply.messages.insert(0, error)

        return reply

    def _end_unauthenticated(self, close_code, error=None):

        self.phase = Phase.ENDED

        return Reply([error] if error is not None else [], close_code)

    def _finish(self, outcome):

        self.outcome = outcome
        log_event(logger, "session_ended", session_id=outcome.session_id,
                  outcome=outcome.kind, reason=outcome.reason)
        self._release()
        self.phase = Phase.ENDED

    def _release(self):
        """Drops everything calibration produced: samples and the personalized
        model are never kept past the Session."""

        self._calibration = None
        self._model = None
        self._smoother = None
        self._detector = None
