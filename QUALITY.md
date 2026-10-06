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

| ID   | Requirement | Characteristic | Metric & threshold | Why it matters (client need) | Validated by client? |
| ---- | ----------- | -------------- | ------------------ | ---------------------------- | -------------------- |
| Q-01 |             |                |                    |                              | ☐ (date / who)       |
| Q-02 |             |                |                    |                              | ☐                    |
| Q-03 |             |                |                    |                              | ☐                    |

## 2. Verification (Q2 → Q3)

> For each requirement: **how** will you check it, **when**, and **who** owns it?
> Methods: unit/integration test, benchmark, evaluation on a held-out dataset, comparison with a baseline,
> expert review by the client, user test, checklist or audit, CI job…
> For data/ML work, describe the protocol: dataset split, no leakage, baseline, and metric defined **before** looking at the results.
> A verification is **relevant** if passing it shows the requirement is met, not just that something ran: same metric and threshold as §1, runnable before the demo.

| ID   | Verification method | Pass criterion | When (automatic / each sprint / before demo) | Owner | Result            | Evidence                                       |
| ---- | ------------------- | -------------- | -------------------------------------------- | ----- | ----------------- | ---------------------------------------------- |
| Q-01 |                     |                |                                              |       | ⏳ / ✅ / ⚠️ / ❌ | link to test, CI run, notebook, report, commit |
| Q-02 |                     |                |                                              |       |                   |                                                |
| Q-03 |                     |                |                                              |       |                   |                                                |

> Status: ⏳ not run yet · ✅ pass · ⚠️ partial · ❌ fail (say what you'll do about it in §3)

## 3. Log (one entry per project week)

> 3–5 lines: what was added or checked, what failed, what you'll change. Mention what you showed the client on Friday.

### Week of DD/MM

- Added:
- Checked:
- Shown to client:
- Next:

## 4. Data & confidentiality rules

> Fill this in once and keep it up to date. It is part of Q1 (security) and protects you on CP2.

- Data that must **never** be committed (paths, file types): …
- Where the data actually lives (who has access): …
- Tools/services **not** allowed by the client (e.g. public AI services): …
- Personal data involved (GDPR) and how it is handled: …
- Matching `.gitignore` entries are in place: ☐
