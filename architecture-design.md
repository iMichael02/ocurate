# Architecture Design

Pipeline: Webcam + MediaPipe + modified WebEyeTrack ("BlazeGaze")

## 1. Webcam

Use a normal RGB webcam rather than specialized eye-tracking hardware. The webcam captures the learner's face while they look at the Braille displayed on the screen. This keeps the system low-cost and easy to deploy.

## 2. MediaPipe = vision front-end

Use MediaPipe Face Landmarker to extract:
- facial landmarks
- eye regions
- head orientation
- face position
- potentially useful 3D facial information

MediaPipe does not directly determine which Braille character the learner is looking at. It provides the visual features needed by the gaze model.

## 3. Modified WebEyeTrack ("BlazeGaze") = gaze estimator

Instead of using WebEyeTrack exactly as provided, adapt its approach to our application:

Eye appearance + Head pose + Face position -> Gaze position

The model predicts a normalized point G=(x,y) representing where on the screen the learner is looking. WebEyeTrack's lightweight CNN architecture is attractive because it is designed for real-time webcam gaze estimation.

**Current implementation status**: `gaze_model.py` implements this stage as a `sklearn` `Ridge` regression pipeline (`StandardScaler` + `Ridge`), not the CNN described above. This is a deliberate interim baseline: the 9-point calibration (see below) produces far too little data to train or personalize a CNN from scratch. A pretrained CNN backbone, fine-tuned rather than trained from scratch, would be required before the CNN approach becomes viable. Ridge regression may end up being the shipped approach.

## 4. Personalization / calibration

Webcam gaze estimation varies significantly between people. The learner performs a short calibration (9-point grid, see `calibration.py`):

```
● ● ●
● ● ●
● ● ●
```

The learner looks at each point for a short period. These samples adapt the gaze model to that individual:

```
Generic model
  ↓
Short calibration
  ↓
Personalized model
  ↓
More accurate gaze
```

WebEyeTrack's few-shot personalization / MAML approach is the inspiration here, though the current Ridge-based implementation personalizes by simply fitting the pipeline on the learner's calibration samples rather than a meta-learned few-shot procedure.

## 5. Make it Braille-aware

No need for perfect pixel-level gaze estimation. Because the application controls the screen, it knows exactly where every Braille character is located:

```
┌──────┬──────┬──────┬──────┬──────┐
│  ⠓   │  ⠑   │  ⠇   │  ⠇   │  ⠕   │
│  C1  │  C2  │  C3  │  C4  │  C5  │
└──────┴──────┴──────┴──────┴──────┘
```

If the gaze model predicts (x,y)=(320,250) and that coordinate falls inside C3, the system assigns: Current gaze → C3. The system becomes (x,y) → Braille character rather than requiring extremely precise gaze coordinates. All lines are assumed to have the same number of characters, which keeps the cell grid uniform (see `calibration.py`'s `gaze_to_braille_cell`).

## 6. Reading speed (headline metric)

The passage read each session is a fixed, pre-loaded piece of Grade 1 (uncontracted) Braille text with a known total character/word count and uniform line length (not arbitrary learner-entered text) — this guarantees the "same number of characters per line" assumption holds and that one cell = one character = unambiguous. Grade 2 (contracted) Braille is deliberately deferred — see ADR 0002 — but content/loading code should not hardcode a 1-cell-1-character assumption so deeply that adding Grade 2 later requires a rewrite.

Reading start/end are detected automatically from the fixation → Braille Cell pipeline, not a manual signal from the learner: start = first Fixation on the Passage's first Cell, end = first Fixation on its last Cell.

T = t_end - t_start

CPM = N_characters / (T / 60)
WPM = N_words / (T / 60)

If face/gaze tracking drops out mid-session (blink, look-away, poor lighting), the elapsed-time clock keeps running through the gap rather than pausing — T is still a plain timestamp difference between the first and last Cell fixation. A learner who looks away mid-passage simply scores a slower Reading Speed as a natural consequence, rather than the system trying to define and detect "paused" versus "genuinely slow."

This is the headline number shown to the learner at the end of a session. Sessions are ephemeral (calibrate → read → show result), so this result is displayed on-screen only; nothing is written to disk.

## 7. Eye-movement analysis (secondary layer)

Fixation detection, regressions, skipped characters, saccades, and line transitions (`fixation_detector.py`, `gaze_smoother.py`) are a secondary layer alongside reading speed — they characterize *how* the learner read (messy vs. clean, forward vs. backtracking), not just how fast.
