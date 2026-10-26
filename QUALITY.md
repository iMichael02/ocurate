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
| REQ-01 | Braille reading web interface | Usability | The start screen, camera activation, reading-test flow, and results interface are implemented and can be navigUsabilityated in a browser. | Learners need an accessible, understandable interface to complete a Braille reading test. | ✅ Oct 9 by client   |
| REQ-02 | Frontend–backend communication | Functional suitability / compatibility | The frontend can establish a connection to the backend, complete the agreed session and calibration message flow, and display the backend's completion or error response without a mock service. | The application must use real gaze-analysis results rather than simulated responses. | ☐                    |
| REQ-03 | Database integration for reading results | Functional suitability / reliability | A completed test result can be saved to the agreed database and retrieved correctly for the corresponding learner or session. No duplicate result is created when the same completion is submitted again. | Reading results need to be available after a session so that learners' progress can be reviewed.  | ☐                    |

## 2. Verification (Q2 → Q3)

> For each requirement: **how** will you check it, **when**, and **who** owns it?
> Methods: unit/integration test, benchmark, evaluation on a held-out dataset, comparison with a baseline,
> expert review by the client, user test, checklist or audit, CI job…
> For data/ML work, describe the protocol: dataset split, no leakage, baseline, and metric defined **before** looking at the results.
> A verification is **relevant** if passing it shows the requirement is met, not just that something ran: same metric and threshold as §1, runnable before the demo.

| ID   | Verification method                            | Pass criterion                            | When (automatic / each sprint / before demo) | Owner      | Result | Evidence                                               |
| ---- | ---------------------------------------------- | ----------------------------------------- | -------------------------------------------- | ---------- | ------ | ------------------------------------------------------ |
| REQ-01 | Run the frontend in a browser and manually check the interface and its main screens. Record the client review from the previous week. | The agreed static interface is present and navigable; the previous client approval is documented. | Completed last week; recheck before demo if needed. | Whole team  | ✅     | [ocurate-fe](https://github.com/iMichael02/ocurate-fe) |
| REQ-02 | Run the frontend and backend locally in real-service mode. Test the connection, session creation, calibration flow, and completion/error responses. | The agreed end-to-end flow works without mock mode, and the browser displays the expected service responses. | Before the integration demo | Whole team | ⏳ Not run yet |  |
| REQ-03 | Complete a test session, verify its result in the database, then retrieve it again. Test repeated submission if supported by the agreed design. | The saved result matches the session result and can be retrieved correctly; repeated submission does not create a duplicate where idempotency is required. | Before the integration demo | Whole team | ⏳ Not run yet | Database verification evidence to be added after testing |

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
