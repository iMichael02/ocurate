"""WebSocket message schemas: the single definition shared by validation,
tests and docs/websocket-protocol.md.

Every message is a JSON object with a `type`. Models reject unknown and
missing fields, wrong types (no string -> number coercion) and non-finite
numbers. Rules that need Session state (message order, the Layout covering
every Cell of the Passage, monotonic timestamps) are enforced by the Session
manager, not here.
"""

from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

SUPPORTED_VERSIONS = (1,)
CALIBRATION_POINT_COUNT = 16

LANDMARK_MIN = -0.5
LANDMARK_MAX = 1.5
# Tolerance for rectangles that touch the viewport edge after float rounding.
RECT_EPSILON = 1e-6

ERROR_CODES = (
    "unsupported_version",
    "invalid_token",
    "invalid_message",
    "out_of_order",
    "timestamp_regression",
    "calibration_failed",
)

ABANDON_REASONS = (
    "socket_closed",
    "quit",
    "viewport_changed",
    "frame_timeout",
    "protocol_error",
    "calibration_failed",
)

CLOSE_NORMAL = 1000
CLOSE_INVALID_MESSAGE = 4400
CLOSE_INVALID_TOKEN = 4401
CLOSE_TIMEOUT = 4408
CLOSE_UNSUPPORTED_VERSION = 4409


class Message(BaseModel):

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


# --- shared parts -----------------------------------------------------------

UnitFloat = Annotated[float, Field(ge=0.0, le=1.0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
NonNegativeFloat = Annotated[float, Field(ge=0.0)]


class Point(Message):
    """A viewport-normalized position (calibration target)."""

    x: UnitFloat
    y: UnitFloat


class Landmark(Message):
    """A MediaPipe landmark, normalized to the camera image, sent unchanged.
    It may lie slightly outside 0-1 when the face is partly out of frame."""

    x: Annotated[float, Field(ge=LANDMARK_MIN, le=LANDMARK_MAX)]
    y: Annotated[float, Field(ge=LANDMARK_MIN, le=LANDMARK_MAX)]


class Viewport(Message):

    width: Annotated[float, Field(gt=0)]
    height: Annotated[float, Field(gt=0)]


class CellRect(Message):
    """One Cell's rectangle, normalized 0-1 to the viewport. Row and column
    are 0-based."""

    row: NonNegativeInt
    col: NonNegativeInt
    x: UnitFloat
    y: UnitFloat
    w: Annotated[float, Field(gt=0, le=1.0)]
    h: Annotated[float, Field(gt=0, le=1.0)]

    @model_validator(mode="after")
    def _inside_viewport(self):
        if self.x + self.w > 1 + RECT_EPSILON or self.y + self.h > 1 + RECT_EPSILON:
            raise ValueError("rectangle extends outside the viewport")
        return self


# --- browser -> service -------------------------------------------------------

class Hello(Message):

    type: Literal["hello"]
    version: Annotated[int, Field(ge=1)]
    token: Annotated[str, Field(min_length=1, max_length=4096)]


class Layout(Message):

    type: Literal["layout"]
    viewport: Viewport
    cells: Annotated[List[CellRect], Field(min_length=1, max_length=10000)]

    @model_validator(mode="after")
    def _unique_cells(self):
        positions = {(cell.row, cell.col) for cell in self.cells}
        if len(positions) != len(self.cells):
            raise ValueError("duplicate (row, col) in cells")
        return self


Landmarks8 = Annotated[List[Landmark], Field(min_length=8, max_length=8)]
MatrixRow = Annotated[List[float], Field(min_length=4, max_length=4)]
Matrix4x4 = Annotated[List[MatrixRow], Field(min_length=4, max_length=4)]


class Frame(Message):
    """One webcam frame. `iris` is the left ring (474-477) then the right ring
    (469-472). `eye_corners` is, per eye (left eye first), left, right, top and
    bottom (362, 263, 386, 374 then 133, 33, 159, 145). `matrix` is row-major
    (rotation in [:3, :3], translation in [:3, 3]). `target` is present only
    during calibration."""

    type: Literal["frame"]
    t: NonNegativeFloat
    iris: Landmarks8
    eye_corners: Landmarks8
    nose: Landmark
    matrix: Matrix4x4
    target: Optional[Point] = None


class CalibrationRestart(Message):
    type: Literal["calibration_restart"]


class CalibrationDone(Message):
    type: Literal["calibration_done"]


class ViewportChanged(Message):
    type: Literal["viewport_changed"]


class Quit(Message):
    type: Literal["quit"]


ClientMessage = Annotated[
    Union[Hello, Layout, Frame, CalibrationRestart, CalibrationDone, ViewportChanged, Quit],
    Field(discriminator="type"),
]


# --- service -> browser -------------------------------------------------------

class HelloAck(Message):

    type: Literal["hello_ack"]
    version: Annotated[int, Field(ge=1)]
    supported: List[Annotated[int, Field(ge=1)]]


class CalibrationPoint(Message):

    index: Annotated[int, Field(ge=0, lt=CALIBRATION_POINT_COUNT)]
    state: Literal["pending", "collecting", "ok", "skipped"]
    samples: NonNegativeInt


class CalibrationStatus(Message):

    type: Literal["calibration_status"]
    points: Annotated[List[CalibrationPoint], Field(min_length=CALIBRATION_POINT_COUNT,
                                                    max_length=CALIBRATION_POINT_COUNT)]
    outcome: Optional[Literal["ready", "failed"]] = None
    reason: Optional[Literal["too_few_points", "missing_row_or_column"]] = None
    attempt: Annotated[int, Field(ge=1)]
    max_attempts: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def _consistent(self):
        if sorted(point.index for point in self.points) != list(range(CALIBRATION_POINT_COUNT)):
            raise ValueError("points must cover indices 0-15 exactly once")
        if (self.outcome == "failed") != (self.reason is not None):
            raise ValueError("reason is required when failed and only then")
        if self.attempt > self.max_attempts:
            raise ValueError("attempt exceeds max_attempts")
        return self


class ReadingStarted(Message):
    type: Literal["reading_started"]


class Fixation(Message):

    type: Literal["fixation"]
    row: NonNegativeInt
    col: NonNegativeInt
    t: NonNegativeFloat


class SequenceCell(Message):

    row: NonNegativeInt
    col: NonNegativeInt


class Result(Message):
    """Reading Speed plus the secondary layer, as ReadingSession.result()
    reports it, with `sequence` as {row, col} objects."""

    elapsed_seconds: NonNegativeFloat
    cpm: NonNegativeFloat
    wpm: NonNegativeFloat
    saccades: NonNegativeInt
    regressions: NonNegativeInt
    skipped_characters: NonNegativeInt
    sequence: List[SequenceCell]


class Completed(Message):
    type: Literal["completed"]
    result: Result


class Abandoned(Message):
    type: Literal["abandoned"]
    reason: Literal[ABANDON_REASONS]


class Error(Message):

    type: Literal["error"]
    code: Literal[ERROR_CODES]
    message: Annotated[str, Field(max_length=500)]
    supported: Optional[List[int]] = None  # only with unsupported_version


ServerMessage = Annotated[
    Union[HelloAck, CalibrationStatus, ReadingStarted, Fixation, Completed, Abandoned, Error],
    Field(discriminator="type"),
]

_client_adapter = TypeAdapter(ClientMessage)
_server_adapter = TypeAdapter(ServerMessage)


# --- parsing helpers ------------------------------------------------------------

class ProtocolError(Exception):
    """A message that failed validation. `fields` lists dotted paths only;
    values are never included (they may be landmarks or tokens)."""

    code = "invalid_message"

    def __init__(self, fields):
        self.fields = fields
        super().__init__("invalid message: " + (", ".join(fields) or "not a JSON object"))


def _fields_of(error):
    return sorted({".".join(str(part) for part in item["loc"]) or "(message)" for item in error.errors()})


def parse_client_message(raw):
    """Validate one browser -> service text frame. Raises ProtocolError."""
    try:
        return _client_adapter.validate_json(raw)
    except ValidationError as error:
        raise ProtocolError(_fields_of(error)) from None


def parse_server_message(raw):
    """Validate one service -> browser text frame (used by tests and clients)."""
    try:
        return _server_adapter.validate_json(raw)
    except ValidationError as error:
        raise ProtocolError(_fields_of(error)) from None


def serialize(message):
    """Encode an outgoing message as a JSON text frame."""
    return message.model_dump_json()


def negotiate_version(requested):
    """The version to speak, or None if `requested` is not supported."""
    return requested if requested in SUPPORTED_VERSIONS else None
