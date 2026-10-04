---
status: accepted
---

# Split into a web interface and a gaze-analysis service; MediaPipe runs in the browser

Ocurate began as one local Python process that owned the webcam, the screen and the analysis. It is now split: a web interface (the browser plus its own web server) and this repo as a gaze-analysis service. The web server owns Learner identity and result history. This service holds only live in-memory Session state.

Decisions that follow from that and are expensive to undo:

- **Hosted, multi-learner, and raw video never leaves the browser.** MediaPipe Face Landmarker runs client-side. The browser sends only the landmark subset the features need plus the facial transformation matrix. `extract_features` stays in Python so the feature definition has one implementation and the gaze model can change its inputs without a frontend release. The alternative (stream video to the service) was rejected on privacy and bandwidth grounds. Computing the feature vector in JS was rejected because it duplicates the maths across two languages.
- **Live, not batch.** One WebSocket per Session carries calibration, frames in and events out. Reading end is detected from fixations, so the service must tell the browser when to stop; batch upload would push that decision onto the client.
- **The browser's capture clock is the only clock.** Fixation duration and Reading Speed use frame timestamps from the browser, so network jitter cannot corrupt them.
- **The service reports results to the web server directly** over a signed, idempotent callback; the browser never relays them. A Learner's own browser could otherwise submit an inflated Reading Speed.
- **The service persists nothing.** Earlier versions kept Sessions ephemeral (nothing written to disk); that rule is replaced by "completed Sessions are stored by the web server; this service stays stateless." Calibration samples and the personalized model are never stored, since they are biometric-adjacent.
- **Fixed viewport per Session, no resume.** The model's calibration targets are in the viewport's coordinates, so any resize, fullscreen change or scroll abandons the Session and the Learner recalibrates. A dropped connection also abandons it: resuming would need the same Session pinned to the same process and would break the "clock keeps running through gaps" rule.
- **The OpenCV desktop app is dropped.** `main.py`, `camera.py`, `face_tracker.py` and `braille_render.py` are to be deleted (the browser now owns the webcam, MediaPipe and rendering). The repo is backend-only. Real-webcam testing now happens through the web interface.

The calibration grid also grows from 9 to 16 points (4×4) at the same time. This is a tuning change rather than a separate decision, but it affects the usable-point threshold (at least 12 of 16, covering every row and column). ADR 0001's conclusion is unchanged: 16 samples is still far too little to train a CNN.
