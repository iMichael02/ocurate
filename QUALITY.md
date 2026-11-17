# Quality requirements & test policy

> Put this file at the root of your repo and update it **every project week**:
> add requirements on Monday, fill in results before Friday's client demo, then commit.
> It's the evidence for criteria **Q1, Q2 and Q3** of the evaluation grid (Eng. Manager).
> Delete these quoted instructions when you're done.

| Grid   | What it asks                                                          | Where it lives in this file                 |
| ------ | --------------------------------------------------------------------- | ------------------------------------------- |
| **Q1** | You questioned and specified the quality requirements of your product | §1 Requirements                             |
| **Q2** | You defined how you'll know each requirement is met                   | §2 Verification                             |
| **Q3** | You actually ran those checks                                         | §2 _Result_ and _Evidence_ columns + §3 Log |

---

## 1. Requirements (Q1)

> Start with 2–3 requirements for **this week's deliverable**, not the whole product, and add more each week.
> Use the checklist below to question what matters for your client, and keep only what's relevant.
>
> - **Functional suitability**: is the result correct or accurate enough?
> - **Performance**: speed, volume, resources (on _the client's_ hardware?)
> - **Reliability**: robustness to bad or missing input, reproducibility
> - **Security & confidentiality**: data access, NDA, hosting, allowed tools, GDPR
> - **Maintainability**: can someone _at the client_ run, understand and modify it after you leave?
> - **Usability**: can the intended user actually use it without you?
> - **Compatibility / portability**: does it fit the client's environment (OS, tools, infra)?
>
> A requirement must be **measurable**:
>
> - ❌ "The model must be accurate." / "The app must be fast."
> - ✅ "Detection recall ≥ 80 % on the incidents of the held-out period."
> - ✅ "A report is generated in < 10 s for one year of data on the client's laptop."

| ID     | Requirement | Characteristic | Metric & threshold | Why it matters (client need) | Validated by client? |
| ------ | ----------- | -------------- | ------------------ | ---------------------------- | -------------------- |
| REQ-01 | **Correct features.** The server computes the same gaze features as the reference implementation, and the browser's eye centre matches the server's Python reference. | Functional suitability | Server feature vector equals the stored expected values within 1e-6. Browser eye centre equals the Python reference within 1e-6 (position) and 1e-3 (confidence). | One wrong feature silently corrupts every gaze prediction. | ☐ |
| REQ-02 | **Robust to bad input.** Missing or malformed data never crashes the service or yields a bad model. A frame without valid landmarks or matrix counts as "no face", and Calibration only succeeds with enough well-spread targets. | Reliability | 100 % of missing/malformed landmark or matrix inputs give "no face". Model is fitted only if ≥ 12 of 16 targets are usable and every row and column is covered. | Webcams drop faces, and a poor Calibration gives a wrong Reading Speed. | ☐ |
| REQ-03 | **Real-time capture.** Per-frame processing in the browser is fast enough to keep up with the webcam, including the eye-centre step. | Performance efficiency | Median ≤ 33 ms per frame on the client's laptop. Eye centres add ≤ 3 ms. | Slow frames mean fewer gaze samples. | ☐ |
| REQ-04 | **Privacy.** No face image, crop or landmark leaves the browser or is stored or logged. Only computed coordinates are sent. | Security & confidentiality | 0 images, crops or landmarks stored or logged. | Faces are biometric data, and the client forbids storing user images. | ☐ |
| REQ-05 | **Real-service interoperability.** Frontend and backend work together end to end, without the frontend's mock mode. | Compatibility | One full Session without mock: 0 protocol errors, ends `completed`. | Results must come from the real service, not a simulation. | ☐ |
| REQ-06 | **Gaze accuracy.** The gaze model puts a fixation on the Braille Cell the Learner is looking at, because that decides Reading Speed and the secondary metrics. The threshold comes from the measured baseline, not a guess. | Functional suitability | Cell accuracy on held-out Learners (share of fixation frames on the correct Cell), also mean error in degrees and % of screen. Threshold: **to be set from the baseline** (docs/gaze-benchmark.md). | A model that cannot tell neighbouring Cells apart makes Reading Speed meaningless. | ☐ |

## 2. Verification (Q2 → Q3)

> For each requirement: **how** will you check it, **when**, and **who** owns it?
> Methods: unit/integration test, benchmark, evaluation on a held-out dataset, comparison with a baseline,
> expert review by the client, user test, checklist or audit, CI job…
> For data/ML work, describe the protocol: dataset split, no leakage, baseline, and metric defined **before** looking at the results.
> A verification is **relevant** if passing it shows the requirement is met, not just that something ran: same metric and threshold as §1, runnable before the demo.

| ID     | Verification method | Pass criterion | When | Owner | Result | Evidence |
| ------ | ------------------- | -------------- | ---- | ----- | ------ | -------- |
| REQ-01 | **Golden-value tests.** Compare the computed features with vectors recorded from the reference implementation (`tests/analysis/test_eye_features.py`, `test/eye-centre.test.js`). | Every case within the REQ-01 tolerances. | Automatic | Backend / frontend dev | ✅ | `pytest` 543 and `npm test` 40 passed, 2026-11-12. Gap: the v2 eye-centre features have no stored-value test. |
| REQ-02 | **Unit tests.** Feed bad landmarks or matrix, run Calibration with 11 vs 12 targets, with a missing row or column, and with a retry. | All tests pass. | Automatic | Backend dev | ✅ | `pytest` 543 passed, 2026-11-12. |
| REQ-03 | **Browser benchmark.** Time `detect()` with and without eye centres over 100 frames. | Median within the REQ-03 thresholds. | Each sprint | Frontend dev | ⚠️ | Measured 2026-11-17 with `python -m benchmark.browser_timing` (Chrome 157, Linux, 12 cores, 200 frames each, face in view): `detect()` median 11.4 ms without eye centres, 17.8 ms with (p95 19.1 ms). **Median ≤ 33 ms passes. Eye centres add 6.4 ms, over the ≤ 3 ms limit.** One machine, not the client's laptop. Earlier: 15.2 → 23.1 ms on a dev machine; 0.51 ms per crop in Node. |
| REQ-04 | **Network and log inspection.** Check the browser network panel during one Session, and run `tests/test_log_setup.py`. | Only protocol fields are sent, and no landmarks appear in logs. | Before demo | Whole team | ⚠️ | Log tests pass (re-run 2026-11-12). Network check not run. |
| REQ-05 | **End-to-end run.** Run frontend and backend together through one full Session, with mock mode off. | Session ends `completed` with 0 protocol errors. | Before integration demo | Whole team | ⏳ Not run yet | Not run. The old note "WebSocket endpoint not written yet" is out of date: `ws_api.py` and its tests now exist (see §3). |
| REQ-06 | **Offline benchmark.** Replay recorded calibration and reading frames through the service's pipeline with a fixed learner-level split (`python -m benchmark.run --data benchmark/data`). Report per condition: lighting, glasses, distance, webcam, head movement. | Cell accuracy at or above the threshold, no condition worse than the baseline. | Before demo | Backend dev | ⚠️ | Harness, metric and recording script are done. Measured on **one Learner, five sessions** (2026-11-17): baseline cell accuracy 19.2 % (8.6 to 34.1 %), error 17.3 % of the screen, about 3.8°. No candidate improves on it reliably (best, `clip-to-screen`, +1.4 points, below the +2 rule). Threshold **not set**: no other people to record, so no held-out Learner and no condition subgroups. Details: docs/gaze-benchmark.md. |

> Status: ⏳ not run yet · ✅ pass · ⚠️ partial · ❌ fail (say what you'll do about it in §3)

## 3. Log (one entry per project week)

> 3–5 lines: what was added or checked, what failed, what you'll change. Mention what you showed the client on Friday.

### Week of 05/10

- Added: Frontend repository and static Braille reading interface.
- Shown to client: Static web UI for Braille learners, as recorded in the previous log.
- Result: The existing quality report records the UI design and static implementation checks as passed.
- Next: Connect the frontend and backend; clarify the authentication, WebSocket, and database integration responsibilities.

Week of 26/10 — Current planning week

- Planned: Integrate the frontend with the backend's real service flow and clarify how completed reading results will be persisted in the database.
- Verification planned: Run an end-to-end session in real-service mode and verify that a result is saved and can be retrieved.
- Current limitations: The frontend README describes mock mode as the default and says the real WebSocket integration is not yet implemented. Do not mark integration checks as passed until they work.
- Friday commitment: Confirm the exact deliverable with the team, record it in the team's agreed planning location, and update this log with the work completed and evidence before the client demo.

### Week of 09/11

- Checked: re-ran both suites on 2026-11-12: `pytest` 543 passed, `npm test` 40 passed. REQ-01 and REQ-02 evidence updated (was 238 and 25).
- Added: `MATH.md` at the project root, listing every formula from the frontend to the backend.
- Found: v2 eye-centre features (`eye_features.py`) have no stored-value golden test, so REQ-01 is covered for the v1 vector and the eye-centre algorithm only. The REQ-05 evidence is out of date, since `ws_api.py` and its tests now exist.
- Not done: no end-to-end Session run (REQ-05), no browser timing re-measure (REQ-03), no network-panel check (REQ-04).
- Shown to client: _to be filled in by the team before Friday's demo._
- Next: add a golden test for the v2 vector, run the real-service Session and update REQ-05, and check the eye-centre cost (REQ-03).

### Week of 16/11

- Added: REQ-06 (gaze accuracy), an offline gaze benchmark (`benchmark/`, docs/gaze-benchmark.md: metric, replay harness that reuses the service's pipeline, fixed learner-level split, 16 candidate improvements, all off in the service) and a recording script (`benchmark/record.py`).
- Measured: one Learner, five sessions. Baseline cell accuracy 19.2 % (8.6 to 34.1 % between sessions), error about 3.8° (17.3 % of the screen), so the model often lands a Cell or more away. The error on the calibration points it was fitted on is already 11 to 16 %, and reading is no worse than an unseen calibration target. The loss is not drift, it is that the eye features cannot separate gaze positions at Cell width.
- Found: none of the 16 candidates improves it reliably. `clip-to-screen` is the only one that gains in every session (+1.4 points on average, below the +2 rule). Head pose, polynomial, kernel and v2 eye-centre options are worse or mixed. Nothing is adopted and the shipped model is unchanged.
- Not done: other people (none available), so no held-out Learner, no condition subgroups and no REQ-06 threshold. Browser timing (REQ-03) was measured afterwards, see below.
- Next: a better eye representation (pretrained backbone, ADR 0001) as a separate ticket; recordings of other people whenever possible; measure `detect()` in the browser.
- Measured (REQ-03): `detect()` in the browser takes a median 11.4 ms without eye centres and 17.8 ms with them (p95 19.1 ms), so the 33 ms median limit holds. Eye centres add 6.4 ms against the 3 ms limit, which fails. The achieved rate was 24 fps, not 30: probably the frontend's frame cap skipping frames on a 60 Hz display (not tested), not processing time.

## 4. Data & confidentiality rules

> Fill this in once and keep it up to date. It is part of Q1 (security) and protects you on CP2.

- Data that must **never** be committed (paths, file types): Image files excluding .svg and .ico
- Where the data actually lives (who has access): MySQL database
- Tools/services **not** allowed by the client (e.g. public AI services): None
- Personal data involved (GDPR) and how it is handled: Client only send calculated coordinates of points of interests to the server. No user image is stored.
- Matching `.gitignore` entries are in place: Yes
