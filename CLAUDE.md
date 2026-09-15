# Ocurate

Webcam-based Braille reading tracker. Read [CONTEXT.md](./CONTEXT.md) for domain terms and [architecture-design.md](./architecture-design.md) for the technical pipeline before making changes.

## Stack

Python 3.12, OpenCV, MediaPipe Tasks (Face Landmarker), scikit-learn, Pillow, numpy. Dependencies are listed in `requirements.txt`; install into `venv/` with `venv/bin/pip install -r requirements.txt`.

## Running it

`venv/bin/python3 main.py` — opens the webcam, runs 9-point calibration (~1.5s per point), then displays the default Passage until it's fully read (or `q`/Esc to quit), then shows the Reading Speed result.

## Layout

- `camera.py` — `Camera`, a thin `cv2.VideoCapture` wrapper
- `face_tracker.py` — MediaPipe Face Landmarker wrapper (`FaceTracker`), runs in `VIDEO` mode
- `eye_features.py` — turns a `FaceTracker` result into the model's feature vector (iris position normalized per eye, eye aspect ratio, head pose + translation from the facial transformation matrix, nose position)
- `gaze_model.py` — `GazeModel`, an sklearn `Ridge` regression pipeline; interim stand-in for the CNN ("BlazeGaze") described in architecture-design.md (see docs/adr/0001)
- `gaze_smoother.py` — EMA smoothing over raw per-frame gaze points (`GazeSmoother`)
- `fixation_detector.py` — dispersion + duration based fixation detection (`FixationDetector`)
- `calibration.py` — 9-point calibration grid and `gaze_to_braille_cell` (gaze point → row/column on the Braille grid, clamped to the grid bounds)
- `passage.py` — `Passage` (a fixed Grade 1 Braille text with a uniform-width grid) and the ASCII→Braille Unicode table
- `reading_session.py` — `ReadingSession`: turns a stream of (row, column, timestamp) fixations into Reading Speed (CPM/WPM) plus the secondary layer (saccades, regressions, skipped characters)
- `braille_render.py` — PIL-based rendering of calibration dots, the Braille passage, and the result screen into OpenCV BGR frames (`cv2.putText` can't render the Braille Unicode block, hence PIL)
- `main.py` — entry point wiring the above into calibrate → read → show result
- `models/face_landmarker.task` — MediaPipe model asset used by `FaceTracker`

## Testing

`venv/bin/pytest` runs the suite (`tests/`). Pure-logic modules (`passage.py`, `reading_session.py`, `calibration.py`, `eye_features.py`, `braille_render.py` geometry/shape, `gaze_smoother.py`, `fixation_detector.py`, `gaze_model.py`) are unit tested. `camera.py`, `face_tracker.py`, and the calibration/reading loops in `main.py` are not — they need a real webcam and, for `main.py`'s reading loop specifically, a person actually reading the passage, so they've only been smoke-tested manually against real hardware, not exercised by an automated test.

## Working in this repo

- Keep `CONTEXT.md` a pure glossary (no implementation/pipeline details) and `architecture-design.md` as the pipeline/technical spec — don't let pipeline description creep back into `CONTEXT.md`.
- Sessions are ephemeral by design (see CONTEXT.md's Session entry) — nothing is persisted to disk after a run; don't add file/DB logging without revisiting that decision first.
