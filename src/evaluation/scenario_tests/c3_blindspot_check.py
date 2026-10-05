"""Checks C3 (results/scenario_tests/alert_fix_plan.md) against the fluid_overload blind-spot
cases referenced in docs/methodology.md Sec 6.1: data/simulation_runs/features_dataset.csv (30
fluid_overload rows, one Pulse encounter per synthetic patient -- cross-sectional, not a day-by-
day trajectory). Also re-derives, per day, which of P04's (scenario-test cohort) alert days in
seeds 42-44 were baseline-only vs instability-driven, and whether C3 would have suppressed any of
them. Read-only; no scorer/pipeline changes.

Usage:
    PYTHONPATH=. python3 -m src.evaluation.scenario_tests.c3_blindspot_check
"""
from __future__ import annotations

import csv
import pathlib

from src.analytics.risk_score import compute_risk_score

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
FEATURES_DATASET = REPO_ROOT / "data" / "simulation_runs" / "features_dataset.csv"
# The scenario-test batch's saved CSVs live in the OTHER worktree (feature/scenario-testing) --
# read-only copy brought into this worktree's results dir for this check only.
SCENARIO_TEST_RESULTS = REPO_ROOT / "results" / "scenario_tests"


def check_features_dataset():
    print("=== Original fluid_overload blind-spot dataset (data/simulation_runs/features_dataset.csv) ===")
    with open(FEATURES_DATASET) as f:
        rows = [r for r in csv.DictReader(f) if r["scenario_type"] == "fluid_overload"]
    print(f"{len(rows)} fluid_overload rows (one Pulse encounter per synthetic patient -- "
          f"cross-sectional, NOT a day-by-day trajectory).")
    bucket_counts = {}
    baseline_no_instability = 0
    for r in rows:
        hr_rise = float(r["hr_rise"])
        map_drop = float(r["map_drop"])
        co_drop_pct = float(r["co_drop_pct"])
        compensation_flag = int(float(r["compensation_flag"]))
        instability_flag = int(float(r["instability_flag"]))
        map_start = float(r["map_start"])
        score = compute_risk_score(
            hr_rise=hr_rise, map_drop=map_drop, co_drop_pct=co_drop_pct,
            compensation_flag=compensation_flag, instability_flag=instability_flag,
            map_start=map_start,
        )
        bucket_counts[score["risk_bucket"]] = bucket_counts.get(score["risk_bucket"], 0) + 1
        if score["risk_bucket"] == "HIGH" and score["dominant_mechanism"] == "baseline" and not instability_flag:
            baseline_no_instability += 1
    print("risk_bucket distribution:", bucket_counts)
    print(f"Of these, {baseline_no_instability} are HIGH, baseline-dominant, AND instability_flag==0 "
          f"-- the only shape C3's guard could ever act on.")
    print(
        "C3 ALSO requires a streak of >3 CONSECUTIVE DAYS of that shape before it downgrades "
        "anything. This dataset has no day dimension at all -- one row per patient, a single "
        "encounter, not a trajectory. C3's persistence condition is STRUCTURALLY UNEVALUABLE "
        "here: there is no 'day 2', 'day 3' for any of these patients to carry a streak across. "
        "Whatever its single-encounter risk_bucket is, C3 cannot suppress a single isolated day "
        "(streak length 1 can never exceed the >3 threshold)."
    )
    print()


def check_p04(results_dir: pathlib.Path):
    print("=== P04 (scenario-test cohort), seeds 42-44: per-day baseline-only vs instability-driven ===")
    for seed in (42, 43, 44):
        path = results_dir / f"daily_results_P04_seed{seed}.csv"
        if not path.exists():
            print(f"  seed {seed}: {path} not found in this worktree -- skipped")
            continue
        with open(path) as f:
            rows = sorted(csv.DictReader(f), key=lambda r: int(r["day"]))
        baseline_streak = 0
        instability_seen = False
        print(f" seed={seed}")
        for row in rows:
            if row["run_status"] != "complete":
                print(f"  day {row['day']:>2}: FAILED")
                baseline_streak = 0
                instability_seen = False
                continue
            hr_rise = float(row["pulse_hr_end"]) - float(row["pulse_hr_start"])
            map_start = float(row["pulse_map_start"])
            map_drop = map_start - float(row["pulse_map_end"])
            co_start = float(row["pulse_co_start"])
            co_drop_pct = (co_start - float(row["pulse_co_end"])) / co_start * 100 if co_start else 0.0
            compensation_flag = int(row["pulse_compensation_flag"])
            instability_flag = int(row["pulse_instability_flag"])
            score = compute_risk_score(
                hr_rise=hr_rise, map_drop=map_drop, co_drop_pct=co_drop_pct,
                compensation_flag=compensation_flag, instability_flag=instability_flag,
                map_start=map_start,
            )
            high = score["risk_bucket"] == "HIGH"
            baseline_only_today = high and score["dominant_mechanism"] == "baseline" and not instability_flag
            if high and score["dominant_mechanism"] == "baseline":
                baseline_streak += 1
            else:
                baseline_streak = 0
                instability_seen = False
            if instability_flag:
                instability_seen = True
            c3_suppressed = high and baseline_streak > 3 and not instability_seen
            kind = (
                "instability-driven" if (high and instability_flag) else
                "baseline-only" if baseline_only_today else
                ("not HIGH" if not high else "mixed")
            )
            flag = "  <-- C3 WOULD SUPPRESS THIS DAY" if c3_suppressed else ""
            print(f"  day {row['day']:>2}: risk={score['risk_score']:.3f} {score['risk_bucket']:>8} "
                  f"dominant={score['dominant_mechanism']:>8} instability_flag={instability_flag} "
                  f"({kind}){flag}")
    print()


if __name__ == "__main__":
    check_features_dataset()
    check_p04(SCENARIO_TEST_RESULTS)
