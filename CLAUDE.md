# Ocurate

Webcam-based Braille reading tracker. This repo is the **gaze-analysis backend**; the web interface (browser UI plus its own web server) lives elsewhere. Read [CONTEXT.md](./CONTEXT.md) for domain terms and [docs/architecture-design.md](./docs/architecture-design.md) (section 0 especially) for the technical pipeline and the frontend ↔ backend contract before making changes.

## Stack

Python 3.12, FastAPI (+ uvicorn), scikit-learn, numpy, SQLAlchemy Core + PyMySQL (Passages only). Dependencies are listed in `requirements.txt`; install into `venv/` with `venv/bin/pip install -r requirements.txt`. See README.md for running, testing and the `OCURATE_*` configuration.

## Status of the split

The old standalone OpenCV app has been removed. The service skeleton exists; the pure-logic modules below were written for the old app and are still being migrated. The design in architecture-design.md is the target.

## Layout

The code is the `ocurate` package. `tests/` mirrors it.

- `ocurate/` — app factory, settings, logging
- `ocurate/api/` — HTTP and WebSocket routes
- `ocurate/sessions/` — Session state machine and tokens
- `ocurate/analysis/` — pure gaze and reading-analysis logic (no I/O)
- `ocurate/passages/` — Passage model and its MySQL store
- `ocurate/schemas/` — Pydantic request, response and protocol schemas
- `docs/` — architecture, protocol and ADRs

Modules:

- `ocurate/app.py` — FastAPI app factory (`create_app`) with `GET /health`, the Passage endpoints and the routers below
- `ocurate/config.py` — `Settings`, read from `OCURATE_*` environment variables
- `ocurate/schemas/protocol.py` — WebSocket message schemas (Pydantic), error/close codes, version handshake; see docs/websocket-protocol.md and docs/session-transcript.md
- `ocurate/api/sessions_api.py` — `POST /sessions` (API key, then Passage lookup, then a signed single-use token); `ocurate/schemas/sessions.py` holds its request and response; see docs/t9-sessions.md
- `ocurate/api/ws_api.py` — the `/ws` WebSocket route: checks the token, loads the Passage, feeds each message to a `Session` and sends its replies; calls `app.state.on_session_finished(outcome)` when a Session ends
- `ocurate/sessions/session_manager.py` — `Session`: the per-socket state machine (hello → layout → calibration with retries → reading → completed/abandoned). No I/O, so tests drive it with plain messages
- `ocurate/analysis/cell_layout.py` — `cell_at`: maps a gaze point to a Cell from the browser-reported Layout rectangles
- `ocurate/sessions/tokens.py` — `TokenStore`: HMAC-signed Session tokens, single use, in-memory pending/used tables with a cap on pending Sessions
- `ocurate/log_setup.py` — structured logging (`log_event`) that drops landmarks, features, tokens and results

Pure logic, reused by the service:

- `ocurate/analysis/eye_features.py` — turns the landmark subset and transformation matrix sent by the browser into the model's feature vector (iris position normalized per eye, eye aspect ratio, head pose + translation, nose position). `extract_features` takes a `protocol.Frame` and returns `None` ("no face") if any landmark or the matrix is missing, malformed or off-image; `tests/analysis/golden/eye_features.json` pins its output to the vectors the old MediaPipe-based version produced.
- `ocurate/analysis/eye_centre.py` — Python reference of the Timm & Barth eye-centre method the browser runs (ADR 0004, docs/eye-centre.md); the service itself only receives its output in `frame.eye_centres` (protocol v2), which `extract_features(frame, use_eye_centres=True)` turns into 4 extra features
- `ocurate/analysis/gaze_model.py` — `GazeModel`, an sklearn `Ridge` regression pipeline; interim stand-in for the CNN ("BlazeGaze") (see docs/adr/0001)
- `ocurate/analysis/gaze_smoother.py` — EMA smoothing over raw per-frame gaze points (`GazeSmoother`)
- `ocurate/analysis/fixation_detector.py` — dispersion + duration based fixation detection (`FixationDetector`)
- `ocurate/passages/passage.py` — `Passage` (a fixed Grade 1 Braille text with a uniform-width grid) and the ASCII→Braille Unicode table
- `ocurate/passages/passage_store.py` — the MySQL `passages` table (id + text lines): `init_db` creates it and keeps the default Passage in sync with the code; `get_passage` / `list_passages` read it back through `Passage` and raise `StoredPassageError` for a row that is not a valid Passage
- `ocurate/schemas/passage.py` — `PassageSummary`, the JSON the Passage endpoints serve, and `passage_summary` which builds it from a `Passage`
- `ocurate/analysis/reading_session.py` — `ReadingSession`: turns a stream of (row, column, timestamp) fixations into Reading Speed (CPM/WPM) plus the secondary layer

- `ocurate/analysis/calibration.py` — the 16-point (4×4) `CALIBRATION_POINTS` and `Calibration`: per-target mean of tagged frames, success rule (≥12 usable targets, every row and column covered), fits a `GazeModel` only on success, `restart()` clears samples for a retry.

Not written yet: the signed result callback (hook: `app.state.on_session_finished`), frame-rate limiting, and a cap on live Sessions.

## Testing

`venv/bin/pytest` runs the suite (`tests/`, in subfolders that mirror the package). The pure-logic modules (`passage.py`, `reading_session.py`, `schemas/protocol.py`, `calibration.py`, `eye_features.py`, `gaze_smoother.py`, `fixation_detector.py`, `gaze_model.py`) are unit tested (the Passage store and endpoints against mocked database connections, no real database), as are `config.py`, `log_setup.py`, `tokens.py`, `session_manager.py`, `cell_layout.py`, `POST /sessions`, the WebSocket endpoint and the health endpoint. Anything that needs a real webcam is now exercised through the web interface, not here.

## Working in this repo

- Keep `CONTEXT.md` a pure glossary (no implementation/pipeline details) and `architecture-design.md` as the pipeline/technical spec — don't let pipeline description creep back into `CONTEXT.md`.
- Passages are reference data in MySQL; nothing else goes in the database. The service only reads them: the one write path is `passage_store.init_db` (run from the command line, not by the app), which creates the table and keeps the code-owned `default` Passage in sync with `build_default_passage`.
- Apart from that Passage table, this service writes nothing to disk and keeps no history: the web server persists completed Sessions' results (see docs/adr/0003). Don't add file/DB logging here without revisiting that decision first. Calibration samples and the personalized model must never be stored.
- All timing uses the browser's frame timestamps, never arrival time.
