# Gaze accuracy benchmark

How we measure the gaze model offline, and what must happen before it is changed. The code is in
`benchmark/`; run it with `venv/bin/python -m benchmark.run` (see Running). It is a development tool: it is not
part of the service image and the service never imports it.

## Status

| Item | State |
|---|---|
| Metric, harness, split, candidate switches, tests | Done |
| Recording script (`benchmark/record.py`) | Done. Used with a real camera for the recordings below |
| Recordings of real Learners | **One Learner, five sessions** (`p02`, 2026-11-17). No other people are available |
| Baseline numbers | Measured on that one Learner (see Results). Not a population baseline |
| Threshold in QUALITY.md (REQ-06) | **Not set.** One Learner cannot set it |
| Held-out Learner-level test, subgroup rule | **Cannot be run.** The split puts the only Learner on the dev side |
| Any change to the shipped model | None. Every candidate is off in the service |

The harness also ships a simulated Learner (`benchmark/synthetic.py`). It exists to test the harness and to
give tests deterministic input. Its eye model is a guess, so its numbers say nothing about real accuracy, and
the report labels them "synthetic, not a decision".

## Metric (fixed before looking at results)

- **Primary: Cell accuracy.** The share of fixation frames whose predicted Braille Cell is the Cell the
  Learner was looking at. This is what decides Reading Speed, Regressions and Skipped Characters.
- **Secondary: point-of-gaze error** between the smoothed estimate and the true gaze point: in viewport
  fractions, in cm and in degrees of visual angle (from the recording's screen size and viewing distance).
- **Also reported:** calibration success rate (failures are counted, not hidden), the share of frames
  rejected by a candidate, and the median time to process one frame.
- **Which frames are scored.** Only frames whose true gaze point has been still for 0.3 s
  (`SETTLE_SECONDS`). Just after a saccade the smoothed estimate lags the eye by design, and that is not model
  error. Frames with no face are counted and skipped, as in the service.

## Pipeline under test

`benchmark/pipeline.py` replays a recording through the service's own classes: `extract_features` and
`model_columns`, `Calibration` (so the success rule is unchanged), `GazeModel`, `GazeSmoother`,
`FixationDetector` and `cell_at`. The baseline config is what `Session` does today (a test checks that the
baseline model equals the one a plain `Calibration` fits). A candidate changes one setting of that config.

## Recordings

A recording is one Learner: 16-point calibration frames, then a read of a Passage, each frame with its ground
truth. Frames are protocol `Frame` messages exactly as the browser sends them (a `null` frame is "no face"),
so replay runs the real feature code.

```json
{
  "format": 1,
  "learner": "p07",
  "conditions": {"lighting": "dim", "glasses": "yes", "distance": "near", "webcam": "hd", "head": "still"},
  "geometry": {"screen_width_cm": 34.4, "screen_height_cm": 19.4, "distance_cm": 60},
  "cells": [{"row": 0, "col": 0, "x": 0.08, "y": 0.25, "w": 0.06, "h": 0.15}],
  "calibration": [{"target": {"x": 0.1, "y": 0.1}, "frame": {"type": "frame", "t": 0, "...": "..."}}],
  "reading": [{"truth": {"x": 0.11, "y": 0.32}, "frame": null}]
}
```

- `calibration[].target` must be one of the 16 grid points, as in a live Session. `reading[].truth` is where
  the Learner was asked to look. Have them follow a moving cue or fixate named Cells, so the truth is known
  rather than assumed.
- `learner` identifies a person, not a session. Give several recordings of the same person the same `learner` id: the
  split keeps them on one side and the report counts them as one Learner.
- `conditions` are free text per key. The report breaks results down by every key whose value varies.
- **Privacy.** Frames hold face landmarks, so a recording is personal data. Record only with written consent,
  from a separate recording session, never from a live Session (the service stores nothing, REQ-04). Keep the
  files out of git: `benchmark/data/` is ignored. Delete them when the consent period ends.

### Recording a Learner

`benchmark/record.py` is the recording script. It serves a small page on `127.0.0.1` that reuses the frontend's
own `face-tracker.js` (from `--frontend`, default `../ocurate-fe`, not modified), so frames are exactly what the
service receives, eye centres included (one recording serves v1 and v2). The page runs the 16 Calibration dots
with the web interface's timings, then moves a cue dot over each non-blank Cell of the Passage in reading order
(`--dwell-ms`, `--passes`). The truth is the cue's Cell centre. The server computes targets and truth from the
grid and the Layout, so the page cannot misreport them.

```
venv/bin/python -m benchmark.record --learner p07 --consent --screen-cm 34.4x19.4 --distance-cm 60 \
    --condition lighting=dim --condition glasses=yes --condition distance=near \
    --condition webcam=hd --condition head=still
# open http://localhost:8765 in the Learner's browser, enable the camera, start
```

- `--consent` is required and states that the Learner gave written consent. `--learner` is a pseudonym (letters,
  digits, `-`, `_`), never a name.
- The page goes fullscreen. A resize, Esc, leaving fullscreen or hiding the tab discards the recording, as a
  `viewport_changed` would abandon a Session.
- The browser keeps frames in memory and posts one recording at the end. The server validates it with the
  protocol schemas (frame shape, strictly increasing `t`, a complete Layout) and writes
  `benchmark/data/<learner>.json` with mode 0600. It refuses to overwrite without `--overwrite`, never logs a
  request body, and saves one Learner per run. Weak recordings (few frames with a face) are saved with warnings.
- It needs the internet once per run, because the frontend loads MediaPipe and its face model from a CDN.
- Record the condition values you intend to compare (`lighting=good|dim`, `glasses=no|yes`,
  `distance=near|far`, `webcam=...`, `head=still|moving`). The adoption rule needs at least 3 Learners per
  subgroup before a subgroup can veto a candidate.

## Results (2026-11-17)

**Data.** One Learner, five sessions, all dim or good light, no glasses, near, HD webcam, head still (4 dim, 1
good). They are repeated measures on one face and one camera, not a Learner-level test: there is no held-out
Learner (the report says so), no condition other than lighting varies, and nothing generalises to other
people. Every number below is from those five sessions.

**Baseline** (Ridge, v1 landmark features, as the service runs today), per session: cell accuracy 25.5, 15.1,
34.1, 12.6 and 8.6 % (mean 19.2 %); mean error 17.3 % of the screen, about 3.8 degrees. A Braille Cell is about
6 % of the screen wide, so the model usually lands one or more Cells away. The spread between sessions of the
same person is larger than any candidate's effect.

**Where the error comes from** (error as % of the screen, per session, raw predictions):

| Measure | Range over the 5 sessions |
|---|---|
| On the calibration frames the model was fitted on | 11.3 to 15.8 % (2.5 to 3.3 degrees) |
| Leave one calibration target out | 15.7 to 21.0 % |
| Reading | 15.9 to 19.7 % |

Reading error is about the same as the error on an unseen calibration target, and does not grow over a
session (first and second half are similar). So the loss is not drift between calibration and reading.
The six eye features cannot separate gaze positions at Cell width even inside the calibration grid. The mean
reading offset (10 to 17 % of the screen) points in a different direction in each session of the same person,
so a fixed correction would not help, and removing it would still leave 11 to 14 %. Why the features are this
noisy was not investigated (landmark jitter at 640x480 and a small iris range are the guesses).

**Candidates**, compared per session against the baseline (gain in cell accuracy, points). "Better" counts the
sessions out of 5 where the candidate beat the baseline. The adoption rule (`MIN_GAIN` 2 points, on held-out
Learners) could not be applied, so none is adopted and none is a proven loser for other people.

| Candidate | Mean cell accuracy | Better | Decision |
|---|---|---|---|
| baseline | 19.2 % | | |
| `clip-to-screen` | 20.6 % | 5 / 5 | Only consistent gain, mean +1.4, range +0.4 to +3.8. Below `MIN_GAIN`, so not adopted. Cannot hurt an on-screen target. Revisit if a larger test confirms it |
| `fixation-0.05` | 19.8 % | 4 / 5 | Not adopted. Mean +0.6, one session -4.2 |
| `smoothing-0.15` | 19.7 % | 3 / 5 | Not adopted. Range -6 to +6 |
| `alpha-10` | 20.3 % | 3 / 5 | Not adopted. Range -8 to +13 |
| `clamp-out-of-range` | 19.0 % | 2 / 5 | Not adopted. No effect |
| `fixation-0.1s` | 19.0 % | 2 / 5 | Not adopted. No effect |
| `drop-out-of-range` | 18.4 % | 1 / 5 | Not adopted. Drops about half the reading frames for no gain |
| `smoothing-0.4` | 16.6 % | 0 / 5 | Rejected on this Learner |
| `alpha-0.1` | 17.7 % | 2 / 5 | Not adopted. No effect |
| `reject-blinks` | 17.1 % | 1 / 5 | Not adopted. Rejects few frames and the effect swings both ways |
| `v2-eye-centres` | 11.8 % | 3 / 5 | Not adopted. Gains of +8 in two sessions, losses of -26 and -29 in two others. ADR 0004's question stays open: no evidence it beats v1, and 24 features from 16 targets overfit |
| `poly2`, `poly2-alpha-10` | 11.4 %, 17.8 % | 1 / 5, 2 / 5 | Rejected on this Learner |
| `kernel-rbf` | 7.1 % | 1 / 5 | Rejected on this Learner. Also the slowest |
| `head-rotation` | 4.9 % | 0 / 5 | Rejected on this Learner. Worse in every session |
| `head-pose` | 0.2 % | 0 / 5 | Rejected on this Learner. Worse in every session. The columns stay out of the model (architecture-design.md section 3) |

The in-sample check explains the head-pose result: there is no drift for it to correct. The median time to
process one reading frame is 0.3 to 0.6 ms for every candidate (REQ-03 concerns the browser step, which this
does not measure; see Open work).

**Conclusion.** Nothing in this ticket's candidate list fixes Cell-level accuracy, because the limit is the
information in the eye features, not the regression or the post-processing. The shipped model stays as it is.
The next step is a model with a better eye representation (the pretrained backbone in ADR 0001), as a separate
ticket, and it needs recordings from many people to be judged.

## Split and tuning

`split_learners` assigns each Learner to dev or test by a hash of the learner id, so the split is fixed,
survives added recordings (existing Learners never change side) and never puts a Learner on both sides.
Anything chosen by looking at results (an alpha, a threshold) is chosen on the dev learners. Every number used
for a decision comes from the test learners. The model is fitted per Session on that Learner's own
calibration, so the split matters for tuning choices, not for the fit itself.

## Candidates

`benchmark/candidates.py`. Each is the baseline plus one change.

| Candidate | What changes | Why it might help | Risk |
|---|---|---|---|
| `v2-eye-centres` | Add the 4 browser eye-centre features (ADR 0004) | Possibly finer iris position | 24 features from 16 targets can overfit. Drop v2 if no gain, as ADR 0004 says |
| `alpha-0.1`, `alpha-10` | Ridge strength | Bias/variance on a few hundred samples | Tune on dev only |
| `poly2`, `poly2-alpha-10` | Degree 2 terms | The iris-to-screen map is not exactly linear, especially at the edges | More parameters than calibration samples at v2 |
| `kernel-rbf` | RBF kernel ridge | Non-linear without picking terms | Slower per frame (the benchmark reports it) |
| `clip-to-screen` | Clip predictions to 0..1 | Can never move a point further from a target inside the screen | Changes which edge Cells a fixation can land on |
| `drop-out-of-range`, `clamp-out-of-range` | Drop, or pull back, frames with any \|z\| > 3 | The model extrapolates there | Dropping loses frames |
| `reject-blinks` | Drop frames whose eye aspect ratio is under 0.7 of the calibration median, in calibration and reading | WebEyeTrack suppresses predictions during blinks the same way | A threshold to tune |
| `head-rotation`, `head-pose` | Bring head pose columns back (`MODEL_FEATURE_GROUPS`) | WebEyeTrack's main finding: ridge regression without head pose drifts over a session | The columns were removed on purpose (architecture-design.md section 3): they barely vary in calibration, so the fit puts large weights on them |
| `smoothing-0.15`, `smoothing-0.4` | EMA alpha | Noise against lag | Tune on dev |
| `fixation-0.05`, `fixation-0.1s` | Fixation dispersion / duration | Fixations that survive gaze noise | More false fixations |

Not in the benchmark, as separate tickets: a pretrained backbone fine-tuned on calibration (ADR 0001), and
WebEyeTrack's metric head-pose estimation with a MAML-trained few-shot model. The paper's few-shot approach
needs a pretrained network and training data we do not have, which is why Ridge stays the interim model.

## Adoption rule

A candidate is adopted only if, on the test learners:

1. Cell accuracy improves by at least `MIN_GAIN` (2 points; revisit once the real baseline is known),
2. no subgroup of at least `MIN_GROUP_LEARNERS` (3) learners gets worse by more than 1 point,
3. calibration success does not drop, and
4. the median frame time stays within 33 ms (REQ-03).

A subgroup smaller than 3 learners is still reported but cannot veto: it is too noisy to judge. With real
data, record more Learners per condition rather than loosening this.

Changes to adopt also need: golden values and tests updated deliberately, ADR 0001 updated if the model type
changes, and no change to the protocol (a new feature or version goes through websocket-protocol.md first).

## Running

```
# Real recordings (not in git), 1 file per Learner:
venv/bin/python -m benchmark.run --data benchmark/data --json report.json

# Harness check on simulated Learners (about 1 minute; says nothing about real accuracy):
venv/bin/python -m benchmark.run --synthetic --learners-per-condition 6
```

The output is a table of baseline and candidates (cell accuracy, error in degrees and % of the screen,
calibration success, frame ms, decision), then the baseline per condition. `--seed` changes the synthetic
cohort and nothing else.

## Open work

1. **Recordings of other people.** Needed for a Learner-level test, any subgroup (glasses, distance, webcam, head
   movement) and a real threshold. Not available at the moment. Until then nothing here can be decided.
2. **Set the REQ-06 threshold** from a baseline measured on several people, and replace `MIN_GAIN` if 2 points is
   not the right size. Do not set it from the current one-Learner baseline.
3. **Re-run the candidates** on those recordings (`venv/bin/python -m benchmark.run --data benchmark/data`).
   `clip-to-screen` is the one to watch.
4. **Browser time per frame (REQ-03).** Measured 2026-11-17 with `venv/bin/python -m benchmark.browser_timing`
   (Chrome 157, Linux, 12 cores): `detect()` median 11.4 ms without eye centres, 17.8 ms with (p95 19.1 ms).
   The 33 ms median limit holds; the eye centres add 6.4 ms against a 3 ms limit, so that part fails. Left to do:
   find why it is far above the 0.51 ms per crop seen in Node, and repeat on the client's laptop. The recorder's
   20 to 24 fps is probably the frontend's frame cap skipping frames on a 60 Hz display, not processing time
   (untested), and would be fixed in the frontend.
5. **A model with a better eye representation** (pretrained backbone fine-tuned on calibration, ADR 0001), as a
   separate ticket.
