"""Offline evaluation of decide_alert() (fix/unified-alert-decision) against the already-saved
scenario-test CSVs (feature/scenario-testing) -- no new Pulse runs, since risk_score itself is
unchanged. Recomputes, per patient-seed-day, the real compute_risk_score() + the real
compute_baseline_high_streak()/decide_alert() in sequence (the exact same functions now wired
into the live pipeline), and reports ALERT/WATCH rates for all 10 patients, dev (42-44) and
held-out (45-47) seeds separately.

Usage:
    PYTHONPATH=. python3 -m src.evaluation.scenario_tests.unified_alert_eval
"""
from __future__ import annotations

import csv
import json
import pathlib

import yaml

from src.analytics.risk_score import compute_risk_score
from src.analytics.score_reporting import (
    AlertAssessmentView, compute_baseline_high_streak, decide_alert,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "results" / "scenario_tests"
COHORT_PATH = REPO_ROOT / "config" / "scenario_tests" / "cohort.yaml"

PATIENTS = [f"P{i:02d}" for i in range(1, 11)]
DEV_SEEDS = (42, 43, 44)
HELDOUT_SEEDS = (45, 46, 47)


def decide_alert_series(patient_id: str, seed: int) -> list[str | None]:
    """Returns the per-day decide_alert() level for one patient-seed, replaying the real
    pipeline's sequential state (compute_baseline_high_streak() reads only the PREVIOUS day,
    exactly as the live DB-backed version does) -- None for a failed day (no assessment exists,
    same as the live pipeline; the classifier-only fallback is a separate, already-tested path
    this offline replay doesn't need to re-prove)."""
    path = RESULTS_DIR / f"daily_results_{patient_id}_seed{seed}.csv"
    with open(path) as f:
        rows = sorted(csv.DictReader(f), key=lambda r: int(r["day"]))

    levels = []
    prev_streak, prev_instability = None, None
    for row in rows:
        if row["run_status"] != "complete":
            levels.append(None)
            prev_streak, prev_instability = None, None  # pipeline resumes fresh after a failure
            continue
        hr_rise = float(row["pulse_hr_end"]) - float(row["pulse_hr_start"])
        map_start = float(row["pulse_map_start"])
        map_drop = map_start - float(row["pulse_map_end"])
        co_start = float(row["pulse_co_start"])
        co_drop_pct = (co_start - float(row["pulse_co_end"])) / co_start * 100 if co_start else 0.0
        compensation_flag = int(float(row["pulse_compensation_flag"]))
        instability_flag = int(float(row["pulse_instability_flag"]))
        risk = compute_risk_score(
            hr_rise=hr_rise, map_drop=map_drop, co_drop_pct=co_drop_pct,
            compensation_flag=compensation_flag, instability_flag=instability_flag,
            map_start=map_start,
        )
        streak, instability_seen = compute_baseline_high_streak(
            previous_streak_days=prev_streak, previous_instability_seen=prev_instability,
            risk_bucket=risk["risk_bucket"], dominant_mechanism=risk["dominant_mechanism"],
            instability_flag=instability_flag,
        )
        view = AlertAssessmentView(
            severity=float(row["predicted_severity"]) if row["predicted_severity"] else None,
            risk_score=risk["risk_score"], risk_bucket=risk["risk_bucket"],
            dominant_mechanism=risk["dominant_mechanism"],
            baseline_high_streak_days=streak, instability_seen_in_streak=instability_seen,
        )
        report = decide_alert(view, "valid")
        levels.append(report.level)
        prev_streak, prev_instability = streak, instability_seen
    return levels


def evaluate(seeds: tuple) -> dict:
    cohort = yaml.safe_load(COHORT_PATH.read_text())
    out = {}
    for pid in PATIENTS:
        group = cohort["patients"][pid]["expected_group"]
        per_seed = {}
        for seed in seeds:
            levels = decide_alert_series(pid, seed)
            per_seed[seed] = {
                "alert_days": sum(1 for l in levels if l == "ALERT"),
                "watch_days": sum(1 for l in levels if l == "WATCH"),
                "none_days": sum(1 for l in levels if l == "NONE"),
                "failed_days": sum(1 for l in levels if l is None),
                "ever_alert": "ALERT" in levels,
                "ever_watch_or_alert": any(l in ("ALERT", "WATCH") for l in levels),
            }
        out[pid] = {
            "group": group,
            "alerted_all_seeds": all(per_seed[s]["ever_alert"] for s in seeds),
            "watch_or_alert_all_seeds": all(per_seed[s]["ever_watch_or_alert"] for s in seeds),
            "per_seed": per_seed,
        }
    return out


def summarize(results: dict, label: str):
    print(f"\n=== {label} ===")
    should_catch = [p for p, v in results.items() if v["group"] == "should_catch"]
    quiet = [p for p, v in results.items() if v["group"] == "should_stay_quiet"]

    reach_alert = sum(1 for p in should_catch if results[p]["alerted_all_seeds"])
    reach_watch_or_alert = sum(1 for p in should_catch if results[p]["watch_or_alert_all_seeds"])
    print(f"should_catch: {reach_alert}/{len(should_catch)} reach ALERT (all seeds); "
          f"{reach_watch_or_alert}/{len(should_catch)} reach at least WATCH (all seeds)")
    for p in should_catch:
        print(f"  {p}: alerted_all_seeds={results[p]['alerted_all_seeds']} "
              f"watch_or_alert_all_seeds={results[p]['watch_or_alert_all_seeds']}")

    print("should_stay_quiet:")
    for p in quiet:
        v = results[p]
        print(f"  {p}: ALERT in all seeds={v['alerted_all_seeds']}, "
              f"WATCH-or-ALERT in all seeds={v['watch_or_alert_all_seeds']}")

    print("edge cases:")
    for p, v in results.items():
        if v["group"] == "edge_case":
            print(f"  {p}: ALERT in all seeds={v['alerted_all_seeds']}, "
                  f"WATCH-or-ALERT in all seeds={v['watch_or_alert_all_seeds']}")


if __name__ == "__main__":
    dev = evaluate(DEV_SEEDS)
    heldout = evaluate(HELDOUT_SEEDS)
    summarize(dev, "DEV (seeds 42-44)")
    summarize(heldout, "HELD-OUT (seeds 45-47)")

    out_dir = RESULTS_DIR / "posthoc"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "unified_alert_eval_dev.json", "w") as f:
        json.dump(dev, f, indent=2, default=str)
    with open(out_dir / "unified_alert_eval_heldout.json", "w") as f:
        json.dump(heldout, f, indent=2, default=str)
