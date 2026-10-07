"""Offline evaluation of ENABLE_ALERT_HYSTERESIS (feature/wire-research-features) on the saved
scenario-test outputs, seeds 42-44 (development) and 45-47 (held-out) reported separately. No Pulse
runs and no tuning: hysteresis acts only after Pulse, so the saved per-day Pulse features are
enough.

Baseline ("current") is the exact per-day replay signal_disagreement_eval.py already uses -- the
real compute_risk_score() / compute_baseline_high_streak() / determine_simulation_status() /
decide_alert() / ml_severity_alert() in sequence, including the failed-day fallback. The
hysteresis variant runs the same replay and then applies the wired functions exactly as the live
pipeline does (score_reporting's order of operations): severity_hysteresis_state() over the
patient-seed's predicted_severity series up to that day, then apply_severity_hysteresis() and
apply_hysteresis_to_ml_alert(). Parameter values are the existing defaults.

Not evaluated here (they act before Pulse and need new simulations): scenario persistence,
continuous mode, BCG modifiers, HR baseline -- see docs/research_flags_evaluation.md.

Usage:
    PYTHONPATH=. python -m src.evaluation.scenario_tests.research_flags_eval
"""
from __future__ import annotations

import csv
import json
import pathlib
from collections import defaultdict

from src.analytics.score_reporting import (
    AlertReport, apply_hysteresis_to_ml_alert, apply_severity_hysteresis, ml_severity_alert,
    severity_hysteresis_state,
)
from src.evaluation.scenario_tests.signal_disagreement_eval import PATIENTS, RESULTS_DIR, replay

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT_PATH = REPO_ROOT / "results" / "scenario_tests" / "posthoc" / "research_flags_eval.json"
SETS = {"development (42-44)": (42, 43, 44), "held-out (45-47)": (45, 46, 47)}
GROUPS = ("should_catch", "should_stay_quiet", "edge_case")


def replay_with_hysteresis(patient_id: str, seed: int) -> list[dict]:
    days = replay(patient_id, seed)
    with open(RESULTS_DIR / f"daily_results_{patient_id}_seed{seed}.csv") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: int(r["day"]))
    severities = []
    for d, row in zip(days, rows, strict=True):
        assert int(row["day"]) == d["day"]
        d["severity"] = float(row["predicted_severity"])
        severities.append(d["severity"])
        state = severity_hysteresis_state(severities)
        twin = apply_severity_hysteresis(AlertReport(d["twin"], d["twin_source"]), state)
        ml = apply_hysteresis_to_ml_alert(ml_severity_alert(d["severity"]), state)
        d["hyst_twin"] = twin.level
        d["hyst_ml"] = ml["level"]
    return days


def _counts(days, twin_key, ml_key):
    return {
        "ALERT": sum(d[twin_key] == "ALERT" for d in days),
        "WATCH": sum(d[twin_key] == "WATCH" for d in days),
        "ml_ALERT": sum(d[ml_key] == "ALERT" for d in days),
    }


def evaluate(seeds: tuple) -> dict:
    per_patient = {}
    by_group = defaultdict(list)
    for pid in PATIENTS:
        all_days = []
        per_seed = {}
        for seed in seeds:
            days = replay_with_hysteresis(pid, seed)
            all_days += days
            per_seed[seed] = {
                "current": _counts(days, "twin", "ml"),
                "hysteresis": _counts(days, "hyst_twin", "hyst_ml"),
                "ever_alert_current": any(d["twin"] == "ALERT" for d in days),
                "ever_alert_hysteresis": any(d["hyst_twin"] == "ALERT" for d in days),
            }
        group = all_days[0]["expected_group"]
        by_group[group] += all_days
        changed = [d for d in all_days if (d["twin"], d["ml"]) != (d["hyst_twin"], d["hyst_ml"])]
        per_patient[pid] = {
            "group": group,
            "patient_days": len(all_days),
            "current": _counts(all_days, "twin", "ml"),
            "hysteresis": _counts(all_days, "hyst_twin", "hyst_ml"),
            "alert_all_seeds_current": all(per_seed[s]["ever_alert_current"] for s in seeds),
            "alert_all_seeds_hysteresis": all(per_seed[s]["ever_alert_hysteresis"] for s in seeds),
            "days_changed": len(changed),
            "twin_days_changed_by_status": {
                st: sum(1 for d in changed if d["status"] == st and d["twin"] != d["hyst_twin"])
                for st in ("failed", "unstable_completed", "valid")
            },
            "per_seed": per_seed,
        }
    groups = {
        g: {
            "patient_days": len(days),
            "current": _counts(days, "twin", "ml"),
            "hysteresis": _counts(days, "hyst_twin", "hyst_ml"),
            "failed_or_crash_zone_days": sum(d["status"] in ("failed", "unstable_completed") for d in days),
        }
        for g, days in by_group.items()
    }
    return {"groups": groups, "patients": per_patient}


def main():
    out = {label: evaluate(seeds) for label, seeds in SETS.items()}
    for label, res in out.items():
        print(f"\n=== {label} ===")
        print(f"{'group':18s} {'days':>5s} {'ALERT now->hyst':>16s} {'WATCH now->hyst':>16s} {'ML ALERT now->hyst':>19s} {'fail/crash days':>16s}")
        for g in GROUPS:
            r = res["groups"][g]
            c, h = r["current"], r["hysteresis"]
            print(f"{g:18s} {r['patient_days']:5d} {c['ALERT']:>7d} -> {h['ALERT']:<6d} {c['WATCH']:>7d} -> {h['WATCH']:<6d} "
                  f"{c['ml_ALERT']:>8d} -> {h['ml_ALERT']:<8d} {r['failed_or_crash_zone_days']:>10d}")
        for pid, p in res["patients"].items():
            if p["days_changed"]:
                print(f"  {pid} ({p['group']}): ALERT {p['current']['ALERT']}->{p['hysteresis']['ALERT']}, "
                      f"ML ALERT {p['current']['ml_ALERT']}->{p['hysteresis']['ml_ALERT']}, "
                      f"alert in all seeds {p['alert_all_seeds_current']}->{p['alert_all_seeds_hysteresis']}, "
                      f"twin changes by status {p['twin_days_changed_by_status']}")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nwrote {OUT_PATH}")


if __name__ == "__main__":
    main()
