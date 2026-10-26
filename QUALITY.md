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

| ID   | Requirement                | Characteristic                         | Metric & threshold | Why it matters (client need)                                                                             | Validated by client? |
| ---- | -------------------------- | -------------------------------------- | ------------------ | -------------------------------------------------------------------------------------------------------- | -------------------- |
| REQ-01 | Correct features | Functional suitability | Server feature vector matches stored expected values within 1e-6; browser eye centre matches the server's Python reference (1e-6 position, 1e-3 confidence) | A wrong feature silently ruins every gaze prediction. | ☐ |
| REQ-02 | Robust to bad input | Reliability | Missing or malformed landmark/matrix → "no face" (100 %); model fitted only with ≥ 12 of 16 targets and every row and column covered | Webcams drop faces; a poor Calibration gives wrong Reading Speed. | ☐ |
| REQ-03 | Real-time capture | Performance efficiency | Median ≤ 33 ms per frame; eye centres add ≤ 3 ms (client's laptop) | Slow frames mean fewer samples. | ☐ |
| REQ-04 | Privacy | Security & confidentiality | 0 images, crops or landmarks stored or logged | Faces are biometric data; client forbids storing user images. | ☐ |
| REQ-05 | Interoperability | Compatibility | Full Session without mock: 0 protocol errors, ends `completed` | Results must come from the real service. | ☐ |

## 2. Verification (Q2 → Q3)

> For each requirement: **how** will you check it, **when**, and **who** owns it?
> Methods: unit/integration test, benchmark, evaluation on a held-out dataset, comparison with a baseline,
> expert review by the client, user test, checklist or audit, CI job…
> For data/ML work, describe the protocol: dataset split, no leakage, baseline, and metric defined **before** looking at the results.
> A verification is **relevant** if passing it shows the requirement is met, not just that something ran: same metric and threshold as §1, runnable before the demo.

| ID   | Verification method                            | Pass criterion                            | When (automatic / each sprint / before demo) | Owner      | Result | Evidence                                               |
| ---- | ---------------------------------------------- | ----------------------------------------- | -------------------------------------------- | ---------- | ------ | ------------------------------------------------------ |
| REQ-01 | Golden tests: `tests/test_eye_features.py`, `test/eye-centre.test.js` | All cases within tolerance | Automatic | Backend / frontend dev | ✅ | `pytest` 238 and `npm test` 25 passed, 2026-10-26 |
| REQ-02 | Unit tests: bad landmark/matrix; Calibration at 11 vs 12 targets, missing row/column, retry | All pass | Automatic | Backend dev | ✅ | `pytest` 238 passed, 2026-10-26 |
| REQ-03 | Time `detect()` with/without eye centres over 100 frames in the browser | Within threshold | Each sprint | Frontend dev | ⚠️ | Dev machine, before optimisation: 15.2 → 23.1 ms; now 0.51 ms per crop (Node). Browser not re-measured |
| REQ-04 | Inspect network panel for one Session; run `tests/test_log_setup.py` | Only protocol fields sent; no landmarks in logs | Before demo | Whole team | ⚠️ | Log tests pass; network check not run |
| REQ-05 | Run frontend and backend together through a full Session | Passes in one run | Before integration demo | Whole team | ⏳ Not run yet | WebSocket endpoint not written yet |

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

## 4. Data & confidentiality rules

> Fill this in once and keep it up to date. It is part of Q1 (security) and protects you on CP2.

- Data that must **never** be committed (paths, file types): Image files excluding .svg and .ico
- Where the data actually lives (who has access): MySQL database
- Tools/services **not** allowed by the client (e.g. public AI services): None
- Personal data involved (GDPR) and how it is handled: Client only send calculated coordinates of points of interests to the server. No user image is stored.
- Matching `.gitignore` entries are in place: Yes
