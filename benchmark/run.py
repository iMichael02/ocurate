"""Runs the gaze benchmark: baseline and candidates over recordings, with a fixed learner-level split.

    venv/bin/python -m benchmark.run --data benchmark/data          # real recordings (consented, not in git)
    venv/bin/python -m benchmark.run --synthetic                    # simulated Learners: harness check only

Tuning choices are made on the dev learners and every number reported for a decision comes from the held-out
test learners, so no Learner is in both (docs/gaze-benchmark.md). Nothing is written except what `--json` asks for.
"""

import argparse
import hashlib
import json
import math
import sys

import numpy as np

from benchmark.candidates import BASELINE, CANDIDATES
from benchmark.metrics import share, summarize
from benchmark.pipeline import replay
from benchmark.recording import load_directory
from benchmark.synthetic import generate_cohort

TEST_SHARE = 0.5
MIN_GAIN = 0.02            # "X": cell accuracy must improve by at least this much (2 points) to be adopted
SUBGROUP_TOLERANCE = 0.01  # a subgroup may not get worse than this in cell accuracy
MIN_GROUP_LEARNERS = 3     # a subgroup with fewer test learners is reported but cannot veto: too noisy to judge
FRAME_MS_LIMIT = 33.0      # REQ-03: median processing time per frame


def split_learners(recordings, test_share=TEST_SHARE):
    """(dev, test), decided by a hash of the learner id so the split never changes between runs or when
    recordings are added. A Learner is entirely in one side."""

    dev, test = [], []
    for recording in recordings:
        bucket = int.from_bytes(hashlib.sha256(recording.learner.encode()).digest()[:4], "big") % 100
        (test if bucket < test_share * 100 else dev).append(recording)

    return dev, test


def evaluate(recordings, config):
    """Replays every recording under `config`. Returns the per-recording ReplayResults."""

    return [replay(recording, config) for recording in recordings]


def aggregate(results):
    """Pooled metrics over a list of ReplayResults (calibration failures counted, not hidden)."""

    scored = [r for r in results if r.calibrated]

    return {
        "learners": len({r.learner for r in results}),   # people, not sessions: one Learner may have several recordings
        "calibration_success": share([r.calibrated for r in results]),
        "cell_accuracy": share([hit for r in scored for hit in r.cell_hits]),
        "error_fraction": summarize([e for r in scored for e in r.errors_fraction]),
        "error_cm": summarize([e for r in scored for e in r.errors_cm]),
        "error_degrees": summarize([e for r in scored for e in r.errors_degrees]),
        "frame_ms_median": float(np.median([m for r in scored for m in r.frame_ms])) if scored else math.nan,
        "rejected_share": (sum(r.rejected for r in scored) / max(1, sum(r.frames for r in scored))),
    }


def by_condition(results):
    """Aggregates per condition value, e.g. {"lighting=dim": {...}}. Conditions that never vary are skipped."""

    keys = sorted({k for r in results for k in r.conditions})
    groups = {}

    for key in keys:
        values = {r.conditions.get(key) for r in results}
        if len(values) < 2:
            continue
        for value in sorted(v for v in values if v is not None):
            groups[f"{key}={value}"] = aggregate([r for r in results if r.conditions.get(key) == value])

    return groups


def compare(baseline, candidate, min_gain=MIN_GAIN, tolerance=SUBGROUP_TOLERANCE):
    """Decision of the acceptance criteria for one candidate against the baseline, both as
    {"overall": aggregate, "groups": by_condition}. Adopt only if overall cell accuracy improves by at least
    `min_gain`, no subgroup (of at least MIN_GROUP_LEARNERS learners) gets worse by more than `tolerance`,
    calibration success does not drop and the median frame time stays within REQ-03."""

    gain = candidate["overall"]["cell_accuracy"] - baseline["overall"]["cell_accuracy"]
    worse = [
        name for name, group in candidate["groups"].items()
        if group["learners"] >= MIN_GROUP_LEARNERS
        and group["cell_accuracy"] < baseline["groups"][name]["cell_accuracy"] - tolerance
    ]
    calibration_drop = candidate["overall"]["calibration_success"] < baseline["overall"]["calibration_success"]
    too_slow = candidate["overall"]["frame_ms_median"] > FRAME_MS_LIMIT

    reasons = []
    if math.isnan(gain):
        reasons.append("no held-out test Learner: cannot decide")
    elif not gain >= min_gain:
        reasons.append(f"gain {gain:+.3f} < {min_gain}")
    if worse:
        reasons.append("worse in " + ", ".join(worse))
    if calibration_drop:
        reasons.append("calibration success dropped")
    if too_slow:
        reasons.append("frame time over REQ-03")

    return {"gain": gain, "adopt": not reasons, "reasons": reasons}


def report(recordings, candidates=CANDIDATES, baseline_config=BASELINE):
    """Evaluates baseline and candidates on the held-out test learners. Returns a JSON-able dict."""

    dev, test = split_learners(recordings)

    def run(config, learners):
        results = evaluate(learners, config)
        return {"overall": aggregate(results), "groups": by_condition(results)}

    baseline = run(baseline_config, test)
    out = {
        "synthetic": all(r.synthetic for r in recordings),
        "dev_learners": sorted({r.learner for r in dev}),
        "test_learners": sorted({r.learner for r in test}),
        "baseline": baseline,
        "candidates": {},
    }

    for name, config in candidates.items():
        candidate = run(config, test)
        out["candidates"][name] = {**candidate, "decision": compare(baseline, candidate)}

    return out


def _fmt(value, digits=3):

    return "n/a" if value is None or (isinstance(value, float) and math.isnan(value)) else f"{value:.{digits}f}"


def format_report(data):

    lines = []
    if data["synthetic"]:
        lines.append("SYNTHETIC DATA: this checks the harness only. It says nothing about real accuracy.\n")
    lines.append(f"{len(data['test_learners'])} held-out test learners, {len(data['dev_learners'])} dev learners.\n")
    if not data["test_learners"]:
        lines.append("NO HELD-OUT LEARNER: the split put every Learner on the dev side, so nothing can be decided. "
                     "Record more different people.\n")
    lines.append("| Config | Cell accuracy | Error (degrees) | Error (% screen) | Calibration ok | Frame ms | Decision |")
    lines.append("|---|---|---|---|---|---|---|")

    def row(name, entry, decision):
        o = entry["overall"]
        lines.append(f"| {name} | {_fmt(o['cell_accuracy'])} | {_fmt(o['error_degrees']['mean'], 2)} | "
                     f"{_fmt(100 * o['error_fraction']['mean'], 1)} | {_fmt(o['calibration_success'], 2)} | "
                     f"{_fmt(o['frame_ms_median'], 2)} | {decision} |")

    row("baseline", data["baseline"], "")
    for name, entry in data["candidates"].items():
        d = entry["decision"]
        verdict = "adopt" if d["adopt"] else "no: " + "; ".join(d["reasons"])
        row(name, entry, f"({verdict}; synthetic, not a decision)" if data["synthetic"] else verdict)

    lines.append("\nBaseline by condition (cell accuracy / mean error in degrees):\n")
    for name, group in data["baseline"]["groups"].items():
        lines.append(f"- {name}: {_fmt(group['cell_accuracy'])} / {_fmt(group['error_degrees']['mean'], 2)} "
                     f"({group['learners']} learners)")

    return "\n".join(lines)


def main(argv=None):

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--data", help="directory of recording .json files")
    source.add_argument("--synthetic", action="store_true", help="simulated Learners (harness check only)")
    parser.add_argument("--seed", type=int, default=0, help="seed of the synthetic cohort")
    parser.add_argument("--learners-per-condition", type=int, default=6)
    parser.add_argument("--json", help="also write the full report to this file")
    args = parser.parse_args(argv)

    recordings = (generate_cohort(args.learners_per_condition, args.seed) if args.synthetic
                  else load_directory(args.data))

    if len(recordings) < 2:
        print("Need at least two recordings.", file=sys.stderr)
        return 1

    data = report(recordings)
    print(format_report(data))

    if args.json:
        with open(args.json, "w") as f:
            json.dump(data, f, indent=2)

    return 0


if __name__ == "__main__":
    sys.exit(main())
