# Ocurate

Webcam-based Braille reading tracker. This repo is the **gaze-analysis backend**; the web interface (browser UI plus its own web server) lives elsewhere. Read [CONTEXT.md](./CONTEXT.md) for domain terms and [architecture-design.md](./architecture-design.md) (section 0 especially) for the technical pipeline and the frontend ↔ backend contract before making changes.

## Stack

Python 3.12, FastAPI (+ uvicorn), scikit-learn, numpy. Dependencies are listed in `requirements.txt`; install into `venv/` with `venv/bin/pip install -r requirements.txt`. See README.md for running, testing and the `OCURATE_*` configuration.

## Status of the split

The old standalone OpenCV app has been removed. The service skeleton exists; the pure-logic modules below were written for the old app and are still being migrated. The design in architecture-design.md is the target.

## Layout

Service skeleton:

- `app.py` — FastAPI app factory (`create_app`) with `GET /health`
- `config.py` — `Settings`, read from `OCURATE_*` environment variables
- `protocol.py` — WebSocket message schemas (Pydantic), error/close codes, version handshake; see docs/websocket-protocol.md and docs/session-transcript.md
- `log_setup.py` — structured logging (`log_event`) that drops landmarks, features, tokens and results

Pure logic, reused by the service:

- `eye_features.py` — turns the landmark subset and transformation matrix sent by the browser into the model's feature vector (iris position normalized per eye, eye aspect ratio, head pose + translation, nose position). Currently reads a MediaPipe `FaceLandmarkerResult`; it must be adapted to the browser's message.
- `gaze_model.py` — `GazeModel`, an sklearn `Ridge` regression pipeline; interim stand-in for the CNN ("BlazeGaze") (see docs/adr/0001)
- `gaze_smoother.py` — EMA smoothing over raw per-frame gaze points (`GazeSmoother`)
- `fixation_detector.py` — dispersion + duration based fixation detection (`FixationDetector`)
- `passage.py` — `Passage` (a fixed Grade 1 Braille text with a uniform-width grid) and the ASCII→Braille Unicode table
- `reading_session.py` — `ReadingSession`: turns a stream of (row, column, timestamp) fixations into Reading Speed (CPM/WPM) plus the secondary layer

Needs changing:

- `calibration.py` — still has the 9-point grid and the uniform-grid `gaze_to_braille_cell`. Target: a 16-point (4×4) grid, and Cell mapping from the browser-reported Cell Layout rectangles.

Not written yet: the Session manager (in-memory Session state), the WebSocket endpoint, `POST /sessions`, `GET /passages/{id}`, the token check and the signed result callback.

## Testing

`venv/bin/pytest` runs the suite (`tests/`). The pure-logic modules (`passage.py`, `reading_session.py`, `protocol.py`, `calibration.py`, `eye_features.py`, `gaze_smoother.py`, `fixation_detector.py`, `gaze_model.py`) are unit tested, as are `config.py`, `log_setup.py` and the health endpoint. Anything that needs a real webcam is now exercised through the web interface, not here.

## Working in this repo

- Keep `CONTEXT.md` a pure glossary (no implementation/pipeline details) and `architecture-design.md` as the pipeline/technical spec — don't let pipeline description creep back into `CONTEXT.md`.
- This service writes nothing to disk and keeps no history: the web server persists completed Sessions' results (see docs/adr/0003). Don't add file/DB logging here without revisiting that decision first. Calibration samples and the personalized model must never be stored.
- All timing uses the browser's frame timestamps, never arrival time.
