"""Offline: how often the twin-based alert (decide_alert()) and the ML-severity signal
(ml_severity_alert(), severity > 0.15) disagree, per patient-day, on the saved scenario-test runs
(seeds 42-47, all 10 patients). No Pulse runs and no new thresholds -- replays the real
compute_risk_score() / compute_baseline_high_streak() / determine_simulation_status() /
decide_alert() on each saved day, in sequence, the way the live pipeline does:

  - completed day: risk + C3 streak from that day's saved Pulse features; status "valid", or
    "unstable_completed" when (predicted scenario, severity) is in the documented crash zone.
  - failed day: decide_alert(..., "unstable_failed") from the classifier severity alone; the C3
    streak resets (same convention as unified_alert_eval.py).

"Disagree" uses signals_disagree(): the twin fires at ALERT or WATCH, the ML signal at ALERT. The
breakdown also reports the stricter reading (twin fires at ALERT only) so either can be quoted.

Usage:
    PYTHONPATH=. python3 -m src.evaluation.scenario_tests.signal_disagreement_eval
"""
from __future__ import annotations

import csv
import json
import pathlib
from collections import Counter, defaultdict

from src.analytics.risk_score import compute_risk_score
from src.analytics.score_reporting import (
    AlertAssessmentView, compute_baseline_high_streak, decide_alert, determine_simulation_status,
    ml_severity_alert, signals_disagree,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "results" / "scenario_tests"
OUT_PATH = RESULTS_DIR / "posthoc" / "signal_disagreement.json"
PATIENTS = [f"P{i:02d}" for i in range(1, 11)]
SEEDS = (42, 43, 44, 45, 46, 47)
GROUP_ORDER = ("should_catch", "should_stay_quiet", "edge_case")


def replay(patient_id: str, seed: int) -> list[dict]:
    with open(RESULTS_DIR / f"daily_results_{patient_id}_seed{seed}.csv") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: int(r["day"]))
    out = []
    prev_streak, prev_instability = None, None
    for row in rows:
        severity = float(row["predicted_severity"])
        scenario = row["predicted_scenario"]
        if row["run_status"] != "complete":
            twin = decide_alert(AlertAssessmentView(severity=severity), "unstable_failed")
            prev_streak, prev_instability = None, None
            status = "failed"
        else:
            map_start = float(row["pulse_map_start"])
            co_start = float(row["pulse_co_start"])
            instability_flag = int(float(row["pulse_instability_flag"]))
            risk = compute_risk_score(
                hr_rise=float(row["pulse_hr_end"]) - float(row["pulse_hr_start"]),
                map_drop=map_start - float(row["pulse_map_end"]),
                co_drop_pct=(co_start - float(row["pulse_co_end"])) / co_start * 100 if co_start else 0.0,
                compensation_flag=int(float(row["pulse_compensation_flag"])),
                instability_flag=instability_flag, map_start=map_start,
            )
            streak, instability_seen = compute_baseline_high_streak(
                previous_streak_days=prev_streak, previous_instability_seen=prev_instability,
                risk_bucket=risk["risk_bucket"], dominant_mechanism=risk["dominant_mechanism"],
                instability_flag=instability_flag,
            )
            prev_streak, prev_instability = streak, instability_seen
            sim = determine_simulation_status(scenario, severity, pulse_attempted=True, pulse_succeeded=True)
            status = "unstable_completed" if sim == "unstable" else "valid"
            twin = decide_alert(AlertAssessmentView(
                severity=severity, risk_score=risk["risk_score"], risk_bucket=risk["risk_bucket"],
                dominant_mechanism=risk["dominant_mechanism"],
                baseline_high_streak_days=streak, instability_seen_in_streak=instability_seen,
            ), status)
        ml = ml_severity_alert(severity)
        out.append({
            "patient_id": patient_id, "seed": seed, "day": int(row["day"]),
            "expected_group": row["expected_group"], "status": status,
            "twin": twin.level, "twin_source": twin.source, "ml": ml["level"],
            "disagree": signals_disagree(twin.level, ml),
        })
    return out


def summarize(days: list[dict]) -> dict:
    n = len(days)
    combo = Counter((d["twin"], d["ml"]) for d in days)
    disagree = sum(d["disagree"] for d in days)
    ml_only = sum(d["twin"] == "NONE" and d["ml"] == "ALERT" for d in days)
    twin_only = sum(d["twin"] != "NONE" and d["ml"] == "NONE" for d in days)
    strict = sum((d["twin"] == "ALERT") != (d["ml"] == "ALERT") for d in days)
    return {
        "patient_days": n,
        "disagree": disagree, "disagree_pct": round(100 * disagree / n, 1) if n else None,
        "ml_flags_twin_none": ml_only, "twin_flags_ml_none": twin_only,
        "disagree_if_twin_fires_only_at_ALERT": strict,
        "disagree_if_twin_fires_only_at_ALERT_pct": round(100 * strict / n, 1) if n else None,
        "twin_x_ml": {f"{t}/{m}": c for (t, m), c in sorted(combo.items())},
        "failed_days": sum(d["status"] == "failed" for d in days),
        "unstable_completed_days": sum(d["status"] == "unstable_completed" for d in days),
    }


def main() -> None:
    days = [d for p in PATIENTS for s in SEEDS for d in replay(p, s)]
    by_group = defaultdict(list)
    by_patient = defaultdict(list)
    for d in days:
        by_group[d["expected_group"]].append(d)
        by_patient[d["patient_id"]].append(d)
    result = {
        "seeds": list(SEEDS),
        "definition": "signals_disagree(): twin fires at ALERT or WATCH, ML fires at ALERT (severity > 0.15)",
        "all": summarize(days),
        "by_group": {g: summarize(by_group[g]) for g in GROUP_ORDER if g in by_group},
        "by_patient": {p: {"expected_group": by_patient[p][0]["expected_group"], **summarize(by_patient[p])}
                       for p in PATIENTS},
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: result[k] for k in ("all", "by_group")}, indent=2))
    for p, s in result["by_patient"].items():
        print(p, s["expected_group"], f"disagree {s['disagree']}/{s['patient_days']}",
              f"ML-only {s['ml_flags_twin_none']}", f"twin-only {s['twin_flags_ml_none']}", s["twin_x_ml"])


if __name__ == "__main__":
    main()
