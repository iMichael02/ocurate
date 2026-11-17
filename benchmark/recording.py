"""A recorded Learner: calibration frames, reading frames and the ground truth for both.

The frames are protocol `Frame` messages, exactly what the browser sends, so replaying a recording runs the
service's own feature code. A frame may be null (no face detected). Recordings hold face landmarks, so they
are personal data: record them with consent, keep them outside git (benchmark/data/ is ignored) and never
from live Sessions (REQ-04). See docs/gaze-benchmark.md for the file format.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.schemas import protocol
from benchmark.metrics import Geometry

FORMAT_VERSION = 1


@dataclass
class Recording:
    learner: str
    geometry: Geometry
    cells: list                      # protocol.CellRect, the Layout the Learner saw
    calibration: list                # [((x, y) target, Frame | None)]
    reading: list                    # [((x, y) true gaze point, Frame | None)]
    conditions: dict = field(default_factory=dict)   # e.g. {"lighting": "dim", "glasses": "yes"}
    synthetic: bool = False


def _frame_json(frame):

    return None if frame is None else frame.model_dump(exclude_none=True)


def _frame_from_json(data):

    return None if data is None else protocol.Frame.model_validate(data)


def to_json(recording):

    return {
        "format": FORMAT_VERSION,
        "learner": recording.learner,
        "synthetic": recording.synthetic,
        "conditions": recording.conditions,
        "geometry": vars(recording.geometry),
        "cells": [cell.model_dump() for cell in recording.cells],
        "calibration": [{"target": {"x": x, "y": y}, "frame": _frame_json(f)} for (x, y), f in recording.calibration],
        "reading": [{"truth": {"x": x, "y": y}, "frame": _frame_json(f)} for (x, y), f in recording.reading],
    }


def from_json(data):

    if data.get("format") != FORMAT_VERSION:
        raise ValueError(f"unsupported recording format: {data.get('format')!r}")

    return Recording(
        learner=data["learner"],
        geometry=Geometry(**data["geometry"]),
        cells=[protocol.CellRect.model_validate(c) for c in data["cells"]],
        calibration=[((e["target"]["x"], e["target"]["y"]), _frame_from_json(e["frame"])) for e in data["calibration"]],
        reading=[((e["truth"]["x"], e["truth"]["y"]), _frame_from_json(e["frame"])) for e in data["reading"]],
        conditions=data.get("conditions", {}),
        synthetic=data.get("synthetic", False),
    )


def save(recording, path):

    Path(path).write_text(json.dumps(to_json(recording)))


def load(path):

    return from_json(json.loads(Path(path).read_text()))


def load_directory(directory):
    """Every *.json recording in `directory`, sorted by file name."""

    return [load(p) for p in sorted(Path(directory).glob("*.json"))]
