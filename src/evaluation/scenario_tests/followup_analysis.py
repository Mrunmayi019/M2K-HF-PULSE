"""Follow-up analysis (2026-10-05), items 1-3 of the user's request. Read-only, from the
already-saved scenario-test CSVs -- no new Pulse runs, no code changes. Uses the REAL
decide_alert()/compute_baseline_high_streak()/compute_risk_score() -- same functions wired into
the live pipeline, not reimplemented.

Usage:
    PYTHONPATH=. python3 -m src.evaluation.scenario_tests.followup_analysis
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
EXERCISE_SCENARIOS = {"cardiac_stress", "acute_deterioration"}


def load_rows(patient_id: str, seed: int):
    path = RESULTS_DIR / f"daily_results_{patient_id}_seed{seed}.csv"
    with open(path) as f:
        return sorted(csv.DictReader(f), key=lambda r: int(r["day"]))


def day_record(row: dict) -> dict | None:
    """Recomputes risk_score/dominant_mechanism for one day from saved Pulse features. Returns
    None for a failed day (matches the live pipeline: no RiskAssessment is ever created then)."""
    if row["run_status"] != "complete":
        return None
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
    return {
        "day": int(row["day"]),
        "predicted_scenario": row["predicted_scenario"],
        "predicted_severity": float(row["predicted_severity"]) if row["predicted_severity"] else None,
        "exercise_fired": row["predicted_scenario"] in EXERCISE_SCENARIOS,
        "map_start": map_start,
        "map_end": float(row["pulse_map_end"]),
        "instability_flag": instability_flag,
        "risk_score": risk["risk_score"],
        "risk_bucket": risk["risk_bucket"],
        "dominant_mechanism": risk["dominant_mechanism"],
    }


def alert_series(patient_id: str, seed: int) -> list[dict]:
    """Per-day dicts with day/level/predicted_scenario/exercise_fired/risk_bucket, replaying
    decide_alert()'s real sequential state (C3 streak) exactly as the live pipeline does."""
    rows = load_rows(patient_id, seed)
    out = []
    prev_streak, prev_instability = None, None
    for row in rows:
        rec = day_record(row)
        if rec is None:
            out.append({"day": int(row["day"]), "level": None, "predicted_scenario": None,
                        "exercise_fired": None, "risk_bucket": None})
            prev_streak, prev_instability = None, None
            continue
        streak, instability_seen = compute_baseline_high_streak(
            previous_streak_days=prev_streak, previous_instability_seen=prev_instability,
            risk_bucket=rec["risk_bucket"], dominant_mechanism=rec["dominant_mechanism"],
            instability_flag=rec["instability_flag"],
        )
        view = AlertAssessmentView(
            severity=rec["predicted_severity"], risk_score=rec["risk_score"],
            risk_bucket=rec["risk_bucket"], dominant_mechanism=rec["dominant_mechanism"],
            baseline_high_streak_days=streak, instability_seen_in_streak=instability_seen,
        )
        report = decide_alert(view, "valid")
        rec["level"] = report.level
        rec["source"] = report.source
        out.append(rec)
        prev_streak, prev_instability = streak, instability_seen
    return out


# ---------------------------------------------------------------------------------------------
# Item 1: per-patient ALERT/WATCH day counts, first-day, perturbation-aware detection/false split
# ---------------------------------------------------------------------------------------------
def item1_table(seeds: tuple) -> dict:
    cohort = yaml.safe_load(COHORT_PATH.read_text())
    out = {}
    for pid in PATIENTS:
        cfg = cohort["patients"][pid]
        group = cfg["expected_group"]
        pstart = next((d["day"] for d in cfg["monitored_day_schedule"] if d.get("event")), None)
        per_seed = {}
        for seed in seeds:
            series = alert_series(pid, seed)
            alert_days = [d["day"] for d in series if d["level"] == "ALERT"]
            watch_days = [d["day"] for d in series if d["level"] == "WATCH"]
            if group == "should_stay_quiet" or pstart is None:
                # Per instruction: ALL days false for stay-quiet patients, regardless of pstart.
                detect_alert_days = []
                detect_watch_days = []
                false_alert_days = alert_days
                false_watch_days = watch_days
            else:
                detect_alert_days = [d for d in alert_days if d >= pstart]
                detect_watch_days = [d for d in watch_days if d >= pstart]
                false_alert_days = [d for d in alert_days if d < pstart]
                false_watch_days = [d for d in watch_days if d < pstart]
            per_seed[seed] = {
                "days_ALERT": len(alert_days), "days_WATCH": len(watch_days),
                "first_ALERT_day": alert_days[0] if alert_days else None,
                "first_WATCH_day": watch_days[0] if watch_days else None,
                "first_detect_ALERT_day": min(detect_alert_days) if detect_alert_days else None,
                "first_detect_WATCH_day": min(detect_watch_days) if detect_watch_days else None,
                "false_ALERT_days": false_alert_days,
                "false_WATCH_days": false_watch_days,
                "any_detect_ALERT": bool(detect_alert_days),
                "any_detect_WATCH_or_ALERT": bool(detect_alert_days or detect_watch_days),
                "any_false_ALERT": bool(false_alert_days),
                "any_false_WATCH": bool(false_watch_days),
            }
        out[pid] = {"group": group, "perturbation_start": pstart, "per_seed": per_seed}
    return out


def item1_group_totals(table: dict, seeds: tuple) -> dict:
    should_catch = [p for p, v in table.items() if v["group"] == "should_catch"]
    quiet = [p for p, v in table.items() if v["group"] == "should_stay_quiet"]

    sc_alert = sum(1 for p in should_catch if all(table[p]["per_seed"][s]["any_detect_ALERT"] for s in seeds))
    sc_watch = sum(1 for p in should_catch if all(table[p]["per_seed"][s]["any_detect_WATCH_or_ALERT"] for s in seeds))
    sq_any_alert = {p: any(table[p]["per_seed"][s]["days_ALERT"] > 0 for s in seeds) for p in quiet}
    sq_any_watch = {p: any(table[p]["per_seed"][s]["days_WATCH"] > 0 for s in seeds) for p in quiet}

    return {
        "should_catch_reaching_ALERT_on_or_after_perturbation_all_seeds": f"{sc_alert}/{len(should_catch)}",
        "should_catch_reaching_at_least_WATCH_on_or_after_perturbation_all_seeds": f"{sc_watch}/{len(should_catch)}",
        "should_stay_quiet_any_ALERT_any_day_any_seed": sq_any_alert,
        "should_stay_quiet_any_WATCH_any_day_any_seed": sq_any_watch,
    }


# ---------------------------------------------------------------------------------------------
# Item 3: scenario-label counts, first Exercise day, first MODERATE/HIGH day, for P01/P04/P05/P08
# across all 6 seeds; plus the global "every HIGH day preceded by Exercise" check.
# ---------------------------------------------------------------------------------------------
def item3_patient_seed_summary(pid: str, seed: int) -> dict:
    series = [d for d in alert_series(pid, seed)]  # includes risk_bucket, exercise_fired n/a here
    rows = load_rows(pid, seed)
    scenario_counts: dict[str, int] = {}
    first_exercise_day = None
    first_moderate_day = None
    first_high_day = None
    for row in rows:
        s = row["predicted_scenario"]
        scenario_counts[s] = scenario_counts.get(s, 0) + 1
        if s in EXERCISE_SCENARIOS and first_exercise_day is None:
            first_exercise_day = int(row["day"])
    for rec in series:
        if rec["risk_bucket"] == "MODERATE" and first_moderate_day is None:
            first_moderate_day = rec["day"]
        if rec["risk_bucket"] == "HIGH" and first_high_day is None:
            first_high_day = rec["day"]
    return {
        "scenario_counts": scenario_counts,
        "first_exercise_day": first_exercise_day,
        "first_MODERATE_day": first_moderate_day,
        "first_HIGH_day": first_high_day,
    }


def item3_global_high_preceded_by_exercise_check() -> list[dict]:
    violations = []
    for pid in PATIENTS:
        for seed in list(DEV_SEEDS) + list(HELDOUT_SEEDS):
            rows = load_rows(pid, seed)
            first_exercise_day = None
            for row in rows:
                if row["predicted_scenario"] in EXERCISE_SCENARIOS and first_exercise_day is None:
                    first_exercise_day = int(row["day"])
            series = alert_series(pid, seed)
            for rec in series:
                if rec["risk_bucket"] == "HIGH":
                    if first_exercise_day is None or rec["day"] < first_exercise_day:
                        violations.append({
                            "patient": pid, "seed": seed, "high_day": rec["day"],
                            "first_exercise_day": first_exercise_day,
                        })
    return violations


if __name__ == "__main__":
    dev_table = item1_table(DEV_SEEDS)
    heldout_table = item1_table(HELDOUT_SEEDS)
    dev_totals = item1_group_totals(dev_table, DEV_SEEDS)
    heldout_totals = item1_group_totals(heldout_table, HELDOUT_SEEDS)

    item3 = {}
    for pid in ("P01", "P04", "P05", "P08"):
        item3[pid] = {seed: item3_patient_seed_summary(pid, seed)
                      for seed in list(DEV_SEEDS) + list(HELDOUT_SEEDS)}

    violations = item3_global_high_preceded_by_exercise_check()

    out_dir = RESULTS_DIR / "posthoc"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "followup_item1_dev.json", "w") as f:
        json.dump({"table": dev_table, "totals": dev_totals}, f, indent=2, default=str)
    with open(out_dir / "followup_item1_heldout.json", "w") as f:
        json.dump({"table": heldout_table, "totals": heldout_totals}, f, indent=2, default=str)
    with open(out_dir / "followup_item3.json", "w") as f:
        json.dump({"patient_summaries": item3, "high_preceded_by_exercise_violations": violations},
                   f, indent=2, default=str)

    print("DEV TOTALS:", json.dumps(dev_totals, indent=2, default=str))
    print("HELDOUT TOTALS:", json.dumps(heldout_totals, indent=2, default=str))
    print("HIGH-preceded-by-exercise violations:", len(violations), violations)
