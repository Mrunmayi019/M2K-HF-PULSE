"""Evaluates the 3 candidates from results/scenario_tests/alert_fix_plan.md (written and
committed BEFORE this was run) on dev seeds 42-44, then (separately invoked once that batch
exists) on held-out seeds 45-47. Post-hoc, read-only re-analysis of saved daily_results_*.csv --
no new Pulse runs beyond what the frozen harness already produced, no scorer/pipeline changes.

Usage:
    PYTHONPATH=. python3 -m src.evaluation.scenario_tests.alert_fix_eval {dev,heldout}
"""
from __future__ import annotations

import csv
import json
import pathlib
import sys

import yaml

from src.analytics.risk_score import compute_risk_score

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "results" / "scenario_tests"
COHORT_PATH = REPO_ROOT / "config" / "scenario_tests" / "cohort.yaml"
POSTHOC_DIR = RESULTS_DIR / "posthoc"

DEV_SEEDS = (42, 43, 44)
HELDOUT_SEEDS = (45, 46, 47)
RISK_HIGH = 0.65
RISK_MODERATE = 0.35


def load(pid: str, seed: int):
    path = RESULTS_DIR / f"daily_results_{pid}_seed{seed}.csv"
    with open(path) as f:
        return list(csv.DictReader(f))


def day_components(row: dict):
    if row["run_status"] != "complete":
        return None
    hr_start, hr_end = float(row["pulse_hr_start"]), float(row["pulse_hr_end"])
    map_start, map_end = float(row["pulse_map_start"]), float(row["pulse_map_end"])
    co_start, co_end = float(row["pulse_co_start"]), float(row["pulse_co_end"])
    hr_rise = hr_end - hr_start
    map_drop = map_start - map_end
    co_drop_pct = (co_start - co_end) / co_start * 100 if co_start else 0.0
    compensation_flag = int(row["pulse_compensation_flag"])
    instability_flag = int(row["pulse_instability_flag"])
    r = compute_risk_score(
        hr_rise=hr_rise, map_drop=map_drop, co_drop_pct=co_drop_pct,
        compensation_flag=compensation_flag, instability_flag=instability_flag,
        map_start=map_start,
    )
    r["instability_flag"] = instability_flag
    r["day"] = int(row["day"])
    return r


def build_series(pid: str, seed: int):
    """Returns a day-ordered list of dicts (risk_score, risk_bucket, dominant_mechanism,
    instability_flag) for one patient-seed, None entries for failed days."""
    rows = sorted(load(pid, seed), key=lambda r: int(r["day"]))
    return [day_components(r) for r in rows]


def apply_candidate(series: list, candidate: str) -> list:
    """Returns a list of booleans (one per day, None days -> False) for whether the candidate's
    alert fires that day."""
    out = []
    baseline_streak = 0
    instability_seen_in_streak = False
    above_streak = [False, False, False]  # last 3 days' "above 0.65" state, for C1 (R2-style)
    for day in series:
        if day is None:
            out.append(False)
            baseline_streak = 0
            instability_seen_in_streak = False
            above_streak = [False, False, False]
            continue
        high = day["risk_score"] >= RISK_HIGH
        if candidate == "baseline":
            out.append(high)
        elif candidate == "C1":
            out.append(high and above_streak[-1] and above_streak[-2])
        elif candidate == "C2":
            # Two-level: HIGH is unchanged/urgent; sustained MODERATE is a separate "watch" tier
            # that does NOT feed the primary alert signal evaluated here (see alert_fix_plan.md).
            out.append(high)
        elif candidate == "C3":
            if high and day["dominant_mechanism"] == "baseline":
                baseline_streak += 1
            else:
                baseline_streak = 0
                instability_seen_in_streak = False
            if day["instability_flag"]:
                instability_seen_in_streak = True
            if high and baseline_streak > 3 and not instability_seen_in_streak:
                out.append(False)  # downgraded to watch -- not counted as the primary alert
            else:
                out.append(high)
        else:
            raise ValueError(candidate)
        above_streak = above_streak[1:] + [high]
    return out


def alerted_all_seeds(pid: str, seeds: tuple, candidate: str, cohort: dict):
    firsts = []
    for seed in seeds:
        series = build_series(pid, seed)
        alerts = apply_candidate(series, candidate)
        day_nums = [d["day"] for d in series if d is not None]
        first = next((day_nums[i] for i, a in enumerate(alerts) if a and series[i] is not None), None)
        firsts.append(first)
    return all(f is not None for f in firsts), firsts


def evaluate(candidate: str, seeds: tuple) -> dict:
    cohort = yaml.safe_load(COHORT_PATH.read_text())
    should_catch = [pid for pid, c in cohort["patients"].items() if c["expected_group"] == "should_catch"]
    quiet = [pid for pid, c in cohort["patients"].items() if c["expected_group"] == "should_stay_quiet"]

    caught = 0
    lead_times = []
    detail = {}
    for pid in should_catch:
        alerted, firsts = alerted_all_seeds(pid, seeds, candidate, cohort)
        detail[pid] = {"alerted_all_seeds": alerted, "first_alert_day_by_seed": firsts}
        if alerted:
            caught += 1
            cfg = cohort["patients"][pid]
            story_start = next((d["day"] for d in cfg["monitored_day_schedule"] if d.get("event")), 1)
            lead_times.append(min(f - story_start for f in firsts))

    total_quiet_days = 0
    false_days = 0
    for pid in quiet:
        for seed in seeds:
            series = build_series(pid, seed)
            alerts = apply_candidate(series, candidate)
            total_quiet_days += len(series)
            false_days += sum(1 for a in alerts if a)

    return {
        "candidate": candidate,
        "should_catch_detected": caught,
        "should_catch_total": len(should_catch),
        "should_catch_detail": detail,
        "mean_lead_time_days": round(sum(lead_times) / len(lead_times), 2) if lead_times else None,
        "false_alerts_per_100_patient_days": round(false_days / total_quiet_days * 100, 2) if total_quiet_days else 0.0,
    }


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "dev"
    seeds = DEV_SEEDS if which == "dev" else HELDOUT_SEEDS
    results = {c: evaluate(c, seeds) for c in ("baseline", "C1", "C2", "C3")}
    out_path = POSTHOC_DIR / f"alert_fix_eval_{which}.json"
    POSTHOC_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    for c, r in results.items():
        print(c, {k: v for k, v in r.items() if k != "should_catch_detail"})


if __name__ == "__main__":
    main()
