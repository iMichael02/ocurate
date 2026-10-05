# Architecture Design

Pipeline: Webcam + MediaPipe + modified WebEyeTrack ("BlazeGaze")

## 0. System split: web interface and gaze-analysis service

The application is split across three parties. This repo is only the last one.

```
Browser (web interface)            Web server                    Gaze-analysis service (this repo)
 webcam + MediaPipe (in-browser)    accounts, UI, history DB      Session state, gaze model, analysis
 renders Passage + calibration
        │                                │                                   │
        │◄── Learner login ─────────────►│                                   │
        │                                │── POST /sessions (API key) ──────►│
        │                                │◄─ session id + short-lived token ─│
        │◄── session id + token ─────────│                                   │
        │══════════════ WebSocket (token) ══════════════════════════════════►│
        │                                │◄── signed result callback ────────│
```

**Responsibilities**

- **Browser**: owns the webcam and runs MediaPipe Face Landmarker locally. Raw video never leaves the browser. Renders the Passage and the calibration targets, measures the Cell Layout, and shows live feedback.
- **Web server**: owns Learner identity and all persistence (the result history). Creates Sessions on this service and hands the browser its token. Not part of this repo.
- **This service**: stateless apart from the live in-memory Session (calibrated model, fixation sequence). Owns the feature definition, gaze model, smoothing, fixation detection, Cell mapping, Passage ground truth and Reading Speed. Writes nothing to disk. Persisting is the web server's job.

**Session lifecycle**

1. The web server calls `POST /sessions` (server-to-server, API key) with a Passage id. This service returns a session id and a short-lived token. The web server passes both to the browser.
2. The browser fetches the Passage (text, counts, first and last Cell) from `GET /passages/{id}` and renders it.
3. The browser opens one WebSocket to this service, authenticating with the token, and sends the protocol `version` in its first message.
4. Calibration, then reading, run over that same socket (see the protocol below).
5. On completion this service sends the result to the web server over a signed, idempotent callback keyed by session id (retried until acknowledged), and also streams it to the browser for display. The browser never relays the result, so a stored result cannot be forged by the Learner.
6. If the Session ends abandoned, the callback reports only `abandoned`.

**WebSocket protocol** (JSON text messages, each with a `type`; the protocol `version` is sent in the first message)

| Direction | `type` | Payload |
|---|---|---|
| browser → service | `hello` | `version`, token |
| service → browser | `hello_ack` | the negotiated `version` and the `supported` versions |
| browser → service | `layout` | viewport size and every Cell rectangle, normalized 0–1 to the viewport. Sent once, before calibration. |
| browser → service | `frame` | `t` (browser capture time, ms), the landmark subset (8 iris, 8 eye-corner, nose-tip landmarks), the 4×4 facial transformation matrix, and during calibration the current `target` point |
| browser → service | `calibration_restart` | none. Retry after a failed calibration, on the same socket, up to a limited number of attempts. |
| browser → service | `calibration_done` | none |
| browser → service | `viewport_changed` / `quit` | none |
| service → browser | `calibration_status` | per-target status (face seen, sample count), then `ready` or `failed` |
| service → browser | `reading_started` | none |
| service → browser | `fixation` | the Cell (row, column) the Learner is currently fixating, for live highlighting |
| service → browser | `completed` | the result (Reading Speed and secondary layer) |
| service → browser | `abandoned` | reason |

**Rules**

- **Clocks**: all timing (fixation duration, Reading Speed) uses the browser's frame timestamps `t`, never arrival time. Timestamps that go backwards are rejected. The browser may cap its frame rate (about 30/s). The service tolerates gaps through the fixation detector's existing reset and never asks for a resend.
- **Layout**: the Cell Layout is sent once and is fixed for the Session. Any viewport change (resize, fullscreen toggle, scroll) makes the browser send `viewport_changed`, and the Session ends abandoned. The Learner must recalibrate, because the model's targets were in the old layout's coordinates.
- **Abandonment**: no resume. A socket drop, `quit`, `viewport_changed`, or 30 s without frames ends the Session as abandoned. Abandoned Sessions are not scored and nothing about them is stored beyond the fact that they ended abandoned.
- **What is persisted** (by the web server, not here): the result summary (CPM, WPM, elapsed time, saccades, regressions, skipped characters) and the fixation sequence. Calibration samples, the personalized model and raw feature streams are never stored.

See ADR 0003 for why the system is split this way.

## 1. Webcam

Use a normal RGB webcam rather than specialized eye-tracking hardware. The webcam captures the learner's face while they look at the Braille displayed on the screen. This keeps the system low-cost and easy to deploy. The webcam is accessed by the browser (`getUserMedia`), not by this service.

## 2. MediaPipe = vision front-end

Use MediaPipe Face Landmarker, **running in the browser** (MediaPipe Tasks Web), to extract:
- facial landmarks
- eye regions
- head orientation
- face position
- potentially useful 3D facial information

MediaPipe does not directly determine which Braille character the learner is looking at. It provides the visual features needed by the gaze model.

The browser sends this service only the landmark subset the features need, plus the facial transformation matrix. `eye_features.py` (`extract_features`) stays in this service so the 20-value feature definition has a single implementation and the model's inputs can change without a frontend release.

## 3. Modified WebEyeTrack ("BlazeGaze") = gaze estimator

Instead of using WebEyeTrack exactly as provided, adapt its approach to our application:

Eye appearance + Head pose + Face position -> Gaze position

The model predicts a normalized point G=(x,y) representing where on the screen the learner is looking. WebEyeTrack's lightweight CNN architecture is attractive because it is designed for real-time webcam gaze estimation.

**Current implementation status**: `gaze_model.py` implements this stage as a `sklearn` `Ridge` regression pipeline (`StandardScaler` + `Ridge`), not the CNN described above. This is a deliberate interim baseline: the 16-point calibration (see below) produces far too little data to train or personalize a CNN from scratch. A pretrained CNN backbone, fine-tuned rather than trained from scratch, would be required before the CNN approach becomes viable. Ridge regression may end up being the shipped approach.

## 4. Personalization / calibration

Webcam gaze estimation varies significantly between people. The learner performs a short calibration (16-point 4×4 grid, evenly spaced from 0.1 to 0.9 of the viewport on each axis, see `calibration.py`):

```
● ● ● ●
● ● ● ●
● ● ● ●
● ● ● ●
```

The browser draws each point and tags every frame it streams with the current target. The learner looks at each point for a short period. This service aggregates the samples per point (mean per point, as today; fitting on all frames is a possible later change that needs no protocol change), fits the model, and reports per-point status back to the browser. A point with no face detected is skipped. Calibration fails, and the browser lets the Learner retry, unless at least 12 of the 16 points were usable and every row and column of the grid has at least one usable point. These samples adapt the gaze model to that individual:

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

If the gaze model predicts (x,y)=(320,250) and that coordinate falls inside C3, the system assigns: Current gaze → C3. The system becomes (x,y) → Braille character rather than requiring extremely precise gaze coordinates. All lines are assumed to have the same number of characters, which keeps the Passage's grid uniform.

The browser, which renders the Passage, is the only party that knows where each Cell sits in pixels, so it reports the Cell Layout (one normalized rectangle per Cell) once at Session start. This service maps each Fixation position to a Cell by finding the rectangle that contains it, replacing the uniform-grid arithmetic in `gaze_to_braille_cell`. Mapping from rectangles rather than a computed grid also leaves room for Grade 2 or non-uniform layouts later (ADR 0002).

## 6. Reading speed (headline metric)

The passage read each session is a fixed, pre-loaded piece of Grade 1 (uncontracted) Braille text with a known total character/word count and uniform line length (not arbitrary learner-entered text) — this guarantees the "same number of characters per line" assumption holds and that one cell = one character = unambiguous. Grade 2 (contracted) Braille is deliberately deferred — see ADR 0002 — but content/loading code should not hardcode a 1-cell-1-character assumption so deeply that adding Grade 2 later requires a rewrite.

Reading start/end are detected automatically from the fixation → Braille Cell pipeline, not a manual signal from the learner: start = first Fixation on the Passage's first Cell, end = first Fixation on its last Cell.

T = t_end - t_start

CPM = N_characters / (T / 60)
WPM = N_words / (T / 60)

If face/gaze tracking drops out mid-session (blink, look-away, poor lighting), the elapsed-time clock keeps running through the gap rather than pausing — T is still a plain timestamp difference between the first and last Cell fixation. A learner who looks away mid-passage simply scores a slower Reading Speed as a natural consequence, rather than the system trying to define and detect "paused" versus "genuinely slow."

This is the headline number shown to the learner at the end of a session. This service delivers it to the browser for display and to the web server for storage (see section 0). The service itself writes nothing to disk. Only completed Sessions are scored; an Abandoned Session produces no Reading Speed.

## 7. Eye-movement analysis (secondary layer)

Fixation detection, regressions, skipped characters, saccades, and line transitions (`fixation_detector.py`, `gaze_smoother.py`) are a secondary layer alongside reading speed — they characterize *how* the learner read (messy vs. clean, forward vs. backtracking), not just how fast.
