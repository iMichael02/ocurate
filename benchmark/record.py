"""Records one consented Learner for the gaze benchmark.

    venv/bin/python -m benchmark.record --learner p07 --consent \\
        --screen-cm 34.4x19.4 --distance-cm 60 \\
        --condition lighting=dim --condition glasses=yes --condition distance=near \\
        --condition webcam=hd --condition head=still

Then open http://localhost:8765 in the browser the Learner will use, and follow the page. It runs the same
Calibration dots as the web interface, then shows a cue dot on each Cell of the Passage in reading order, so
the true gaze point is known instead of assumed. Landmarks come from the frontend's own `face-tracker.js`
(served from `--frontend`, default ../ocurate-fe), so the frames are exactly what the service would receive.

The browser keeps everything in memory and posts one recording at the end; this script validates it with the
service's own schemas and writes `benchmark/data/<learner>.json` (docs/gaze-benchmark.md, "Recordings").

Privacy (REQ-04). A recording is personal data: face landmarks. Record only with written consent, from a
separate recording session and never from a live Session. `--consent` states that you have it. Use a
pseudonymous learner id (no name). The server listens on 127.0.0.1 only, never logs a request body, writes
nothing but the one recording file (mode 0600, refuses to overwrite without --overwrite) and
is not part of the service image.
"""

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from app.analysis.calibration import CALIBRATION_POINTS
from app.passages.passage import build_default_passage
from app.schemas import protocol
from benchmark import recording as recording_io
from benchmark.metrics import Geometry
from benchmark.recording import Recording

PAGE_DIRECTORY = Path(__file__).parent / "recorder_page"
DATA_DIRECTORY = Path(__file__).parent / "data"
MAX_BODY_BYTES = 64 * 1024 * 1024
LEARNER_ID = re.compile(r"[A-Za-z0-9_-]{1,32}")
CONDITION_KEY = re.compile(r"[a-z_]{1,24}")
FRAME_FIELDS_PER_POINT = 20         # what the service needs on the last point; used only for a warning
MIN_FACE_SHARE = 0.7                # below this the recording is saved but flagged
FRONTEND_PREFIXES = ("js/", "css/")


class RecordingRejected(ValueError):
    """The posted data cannot be a valid recording. The message never contains landmark values."""


def parse_conditions(items):
    """['lighting=dim', ...] -> {'lighting': 'dim'}."""

    conditions = {}

    for item in items:
        key, separator, value = item.partition("=")
        if not separator or not CONDITION_KEY.fullmatch(key) or not value.strip():
            raise ValueError(f"condition must look like key=value (lowercase key): {item!r}")
        conditions[key] = value.strip()

    return conditions


def parse_screen(text):
    """'34.4x19.4' -> (34.4, 19.4)."""

    try:
        width, height = (float(part) for part in text.lower().split("x"))
    except ValueError:
        raise ValueError(f"--screen-cm must look like 34.4x19.4: {text!r}") from None

    if not (width > 0 and height > 0 and math.isfinite(width) and math.isfinite(height)):
        raise ValueError("--screen-cm must be positive")

    return width, height


def _frame(raw, where):

    if raw is None:
        return None

    try:
        frame = protocol.Frame.model_validate({**raw, "type": "frame"})
    except (ValidationError, TypeError):
        raise RecordingRejected(f"{where}: not a valid frame") from None

    if frame.target is not None:
        raise RecordingRejected(f"{where}: frames carry no target; the target is the entry's index")

    return frame


def build_recording(payload, learner, geometry, conditions):
    """A `Recording` from the page's payload, or `RecordingRejected`.

    payload: {"cells": [CellRect...],
              "calibration": [{"target": 0..15, "frame": Frame | null}],
              "reading": [{"row": r, "col": c, "frame": Frame | null}]}
    The target and truth points are computed here from the grid and the Layout, not trusted from the page.
    """

    passage = build_default_passage()

    try:
        cells = [protocol.CellRect.model_validate(c) for c in payload["cells"]]
        raw_calibration = payload["calibration"]
        raw_reading = payload["reading"]
    except (KeyError, TypeError, ValidationError):
        raise RecordingRejected("payload needs cells, calibration and reading") from None

    wanted = {(r, c) for r in range(passage.num_rows) for c in range(passage.num_columns)}
    if {(c.row, c.col) for c in cells} != wanted or len(cells) != len(wanted):
        raise RecordingRejected("cells must be the Passage's Layout: every Cell once")

    centres = {(c.row, c.col): (c.x + c.w / 2, c.y + c.h / 2) for c in cells}
    last_t = -math.inf
    calibration, reading = [], []

    def checked_time(frame, where):
        nonlocal last_t
        if frame is not None:
            if frame.t <= last_t:
                raise RecordingRejected(f"{where}: t must strictly increase")
            last_t = frame.t
        return frame

    for index, entry in enumerate(raw_calibration):
        where = f"calibration[{index}]"
        target = entry.get("target") if isinstance(entry, dict) else None
        if not isinstance(target, int) or isinstance(target, bool) or not 0 <= target < len(CALIBRATION_POINTS):
            raise RecordingRejected(f"{where}: target must be an index 0-15")
        frame = checked_time(_frame(entry.get("frame"), where), where)
        calibration.append((CALIBRATION_POINTS[target], frame))

    for index, entry in enumerate(raw_reading):
        where = f"reading[{index}]"
        key = (entry.get("row"), entry.get("col")) if isinstance(entry, dict) else None
        if key not in centres:
            raise RecordingRejected(f"{where}: row and col must name a Cell of the Layout")
        frame = checked_time(_frame(entry.get("frame"), where), where)
        reading.append((centres[key], frame))

    if not calibration or not reading:
        raise RecordingRejected("calibration and reading must not be empty")

    return Recording(learner=learner, geometry=geometry, cells=cells, calibration=calibration, reading=reading,
                     conditions=conditions)


def quality_warnings(recording):
    """Plain-language problems that make a recording poor evidence. It is still saved."""

    warnings = []
    per_target = {}

    for target, frame in recording.calibration:
        per_target.setdefault(target, []).append(frame is not None)

    thin = [t for t, seen in per_target.items() if sum(seen) < FRAME_FIELDS_PER_POINT]
    if len(per_target) < len(CALIBRATION_POINTS):
        warnings.append(f"only {len(per_target)} of 16 calibration targets have frames")
    if thin:
        warnings.append(f"{len(thin)} calibration targets have fewer than {FRAME_FIELDS_PER_POINT} frames with a face")

    for name, entries in (("calibration", recording.calibration), ("reading", recording.reading)):
        share = sum(frame is not None for _, frame in entries) / len(entries)
        if share < MIN_FACE_SHARE:
            warnings.append(f"a face was found in only {share:.0%} of the {name} frames")

    return warnings


def serve_frontend(app, frontend):
    """Adds `GET /fe/<path>` to `app`: the frontend's own js/ and css/ files, read-only. Shared with
    benchmark/browser_timing.py."""

    frontend = Path(frontend).resolve()

    @app.get("/fe/{path:path}")
    def frontend_file(path: str):
        # Only the frontend's js/ and css/ folders: no dotfiles, node_modules or anything else.
        full = (frontend / path).resolve()
        allowed = path.startswith(FRONTEND_PREFIXES) and full.is_relative_to(frontend) and full.is_file() \
            and not any(part.startswith(".") for part in Path(path).parts)
        if not allowed:
            raise HTTPException(404)
        return FileResponse(full, headers={"Cache-Control": "no-store"})


def create_app(learner, geometry, conditions, frontend, output, overwrite=False, dwell_ms=1000, passes=1):
    """The recorder server. `frontend` is the ocurate-fe folder, `output` the file to write."""

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    output = Path(output)
    passage = build_default_passage()
    saved = {"done": False}

    def static(path):
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    @app.get("/")
    def page():
        return static(PAGE_DIRECTORY / "index.html")

    @app.get("/recorder.js")
    def script():
        return static(PAGE_DIRECTORY / "recorder.js")

    serve_frontend(app, frontend)

    @app.get("/config")
    def config():
        return {"learner": learner, "lines": passage.lines, "dwell_ms": dwell_ms, "passes": passes,
                "output": output.name}

    @app.post("/recording")
    async def post_recording(request: Request):
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise HTTPException(415)
        if saved["done"]:
            raise HTTPException(409, "already saved; restart the recorder for another Learner")

        body = b""
        async for chunk in request.stream():
            body += chunk
            if len(body) > MAX_BODY_BYTES:
                raise HTTPException(413)

        try:
            payload = json.loads(body)
            recording = build_recording(payload, learner, geometry, conditions)
        except (ValueError, AttributeError) as error:
            reason = str(error) if isinstance(error, RecordingRejected) else "body is not valid JSON"
            return JSONResponse({"saved": False, "reason": reason}, status_code=422)

        if output.exists() and not overwrite:
            return JSONResponse({"saved": False, "reason": f"{output.name} exists; use --overwrite"}, status_code=409)

        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.close(descriptor)
        recording_io.save(recording, output)
        saved["done"] = True

        return {"saved": True, "file": output.name, "calibration_frames": len(recording.calibration),
                "reading_frames": len(recording.reading), "warnings": quality_warnings(recording)}

    return app


def parse_args(argv=None):

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--learner", required=True, help="pseudonymous id, letters, digits, - and _ (no name)")
    parser.add_argument("--consent", action="store_true",
                        help="I have this Learner's written consent to record face landmarks for the benchmark")
    parser.add_argument("--screen-cm", required=True, help="visible screen size, WIDTHxHEIGHT in cm, e.g. 34.4x19.4")
    parser.add_argument("--distance-cm", type=float, required=True, help="eye-to-screen distance in cm")
    parser.add_argument("--condition", action="append", default=[], metavar="KEY=VALUE",
                        help="lighting, glasses, distance, webcam, head... (repeatable)")
    parser.add_argument("--frontend", default=str(Path(__file__).resolve().parents[2] / "ocurate-fe"),
                        help="the ocurate-fe folder (default: next to this repo)")
    parser.add_argument("--data", default=str(DATA_DIRECTORY), help="where to write the recording")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dwell-ms", type=int, default=1000, help="time the cue stays on each Cell")
    parser.add_argument("--passes", type=int, default=1, help="how many times to read the Passage")
    parser.add_argument("--port", type=int, default=8765)

    return parser.parse_args(argv)


def main(argv=None):

    args = parse_args(argv)

    if not args.consent:
        sys.exit("Refusing to record: pass --consent only once this Learner has given written consent.")
    if not LEARNER_ID.fullmatch(args.learner):
        sys.exit("--learner must be 1-32 letters, digits, - or _ (a pseudonym, not a name)")
    if not Path(args.frontend, "js", "camera", "face-tracker.js").is_file():
        sys.exit(f"--frontend {args.frontend!r} is not the ocurate-fe folder")
    if not (args.distance_cm > 0 and args.dwell_ms >= 400 and args.passes >= 1):
        sys.exit("--distance-cm must be positive, --dwell-ms at least 400, --passes at least 1")

    try:
        width, height = parse_screen(args.screen_cm)
        conditions = parse_conditions(args.condition)
    except ValueError as error:
        sys.exit(str(error))

    output = Path(args.data) / f"{args.learner}.json"
    if output.exists() and not args.overwrite:
        sys.exit(f"{output} exists; use --overwrite to replace it")

    app = create_app(args.learner, Geometry(width, height, args.distance_cm), conditions, args.frontend, output,
                     args.overwrite, args.dwell_ms, args.passes)

    print(f"Open http://localhost:{args.port} in the browser the Learner will use (fullscreen, F11).")
    print(f"Writes {output}. Personal data: keep it out of git and delete it when the consent period ends.")
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
