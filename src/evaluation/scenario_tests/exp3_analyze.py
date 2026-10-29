"""Experiment 3 analysis against results/scenario_tests/exp3/PREREGISTRATION.md. Experiment 2 (same
cohort and seeds, flag off) is the control arm. No Pulse runs; reads the saved daily_results CSVs.

Usage:
    PYTHONPATH=. python3 -m src.evaluation.scenario_tests.exp3_analyze
"""
from __future__ import annotations

import json
import pathlib

import numpy as np
import yaml

from src.evaluation.scenario_tests.ablation_eval import onset_day
from src.evaluation.scenario_tests.exp2_analyze import (
    CATCH, EXERTION, QUIET, alerts_by_system, label_accuracy, load_rows, system_metrics,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
EXP2_DIR = REPO_ROOT / "results/scenario_tests/exp2"
EXP3_DIR = REPO_ROOT / "results/scenario_tests/exp3"
COHORT_PATH = REPO_ROOT / "config/scenario_tests/cohort_exp3.yaml"
OUT = EXP3_DIR / "exp3_analysis.json"
SEEDS = range(48, 54)
FIRST_REFRESH_DAY = 7  # nominal; a failed day shifts later refreshes (the CSV records the real ones)
PULSE_COLS = ("pulse_hr_end", "pulse_map_end", "pulse_co_end", "risk_score")


def _f(x):
    return float(x) if x not in (None, "") else None


def _true(x):
    return str(x).lower() == "true"


def integrity(patients):
    """I1 classifier output identical to Exp 2 on every day; I2 Pulse output identical on days
    before the first refresh; I3 refreshes performed vs due."""
    label_diff = sev_diff = 0
    pre_days = pre_mismatch = 0
    pre_max_abs = {c: 0.0 for c in PULSE_COLS}
    performed = due = 0
    errors = []
    for pid in patients:
        for s in SEEDS:
            a, b = load_rows(EXP2_DIR, pid, s), load_rows(EXP3_DIR, pid, s)
            assert [r["day"] for r in a] == [r["day"] for r in b], (pid, s)
            for ra, rb in zip(a, b):
                d = int(rb["day"])
                label_diff += ra["predicted_scenario"] != rb["predicted_scenario"]
                sev_diff += _f(ra["predicted_severity"]) != _f(rb["predicted_severity"])
                if d <= FIRST_REFRESH_DAY and ra["run_status"] == rb["run_status"] == "complete":
                    pre_days += 1
                    diffs = {c: abs(_f(ra[c]) - _f(rb[c])) for c in PULSE_COLS}
                    pre_mismatch += any(v > 0 for v in diffs.values())
                    for c, v in diffs.items():
                        pre_max_abs[c] = max(pre_max_abs[c], v)
                if rb["refresh_performed"] != "":
                    due += 1
                    performed += _true(rb["refresh_performed"])
                    if rb["refresh_error"]:
                        errors.append([pid, s, d, rb["refresh_error"]])
    return {
        "I1_label_days_differing": label_diff, "I1_severity_days_differing": sev_diff,
        "I2_days_compared": pre_days, "I2_days_differing": pre_mismatch,
        "I2_max_abs_diff": {c: round(v, 6) for c, v in pre_max_abs.items()},
        "I3_refreshes_due": due, "I3_refreshes_performed": performed, "I3_refresh_errors": errors,
    }


def drift_groups(patients):
    """P1. Each refresh day goes in one group by the Exercise its chain carried:
    A = no Exercise in the chain before the refresh day and none that day; B = Exercise earlier in
    the chain, none that day; C = Exercise on the refresh day itself."""
    groups = {"A": [], "B": [], "C": []}
    for pid in patients:
        for s in SEEDS:
            rows = load_rows(EXP3_DIR, pid, s)
            chain_ex = False
            for r in rows:
                ex_today = r["run_status"] == "complete" and _true(r["exercise_applied"])
                if r["refresh_performed"] != "" and _true(r["refresh_performed"]):
                    g = "C" if ex_today else ("B" if chain_ex else "A")
                    groups[g].append({"pid": pid, "seed": s, "day": int(r["day"]),
                                      "hr": _f(r["drift_hr_bpm"]), "map": _f(r["drift_map_mmhg"]),
                                      "co": _f(r["drift_co_ml_min"])})
                    chain_ex = False  # the next day resumes from the fresh state
                else:
                    chain_ex = chain_ex or ex_today

    def summary(items, key):
        v = np.array([i[key] for i in items])
        if not len(v):
            return None
        return {"median": round(float(np.median(v)), 2), "q25": round(float(np.percentile(v, 25)), 2),
                "q75": round(float(np.percentile(v, 75)), 2), "min": round(float(v.min()), 2), "max": round(float(v.max()), 2)}

    return {g: {"n": len(items), "hr_bpm": summary(items, "hr"), "map_mmhg": summary(items, "map"),
                "co_ml_min": summary(items, "co"),
                "share_map_le_minus15": round(float(np.mean([i["map"] <= -15 for i in items])), 3) if items else None,
                "share_hr_le_minus10": round(float(np.mean([i["hr"] <= -10 for i in items])), 3) if items else None}
            for g, items in groups.items()}


def alert_days(results_dir, onsets):
    """P2 / P4: deployed and Pulse-HIGH alert days, post-onset in should_catch series and on days
    8-21 by group."""
    out = {"catch_post_onset_deployed": 0, "catch_post_onset_pulse_high": 0,
           "days8_21_deployed": {"catch": 0, "quiet": 0}, "days8_21_pulse_high": {"catch": 0, "quiet": 0},
           "catch_post_onset_deployed_per_patient": {}}
    for pid in CATCH + QUIET:
        grp = "catch" if pid in CATCH else "quiet"
        for s in SEEDS:
            days, al = alerts_by_system(results_dir, pid, s, False)
            for d, dep, hi in zip(days, al["deployed"], al["pulse_high"]):
                if d >= 8:
                    out["days8_21_deployed"][grp] += dep
                    out["days8_21_pulse_high"][grp] += hi
                if grp == "catch" and d >= onsets[pid]:
                    out["catch_post_onset_deployed"] += dep
                    out["catch_post_onset_pulse_high"] += hi
                    pp = out["catch_post_onset_deployed_per_patient"]
                    pp[pid] = pp.get(pid, 0) + dep
    return out


def reset_eligible_check(onsets):
    """Secondary: of the Exp 2 deployed alert days on days 8-21 that fall after a refresh with no
    exertion label since it (the days the hypothesis says a refresh clears), how many are still
    alerts in Exp 3; and the same count for the non-eligible days."""
    res = {"eligible_exp2_alert_days": 0, "eligible_still_alert_exp3": 0,
           "other_exp2_alert_days": 0, "other_still_alert_exp3": 0}
    for pid in CATCH + QUIET:
        for s in SEEDS:
            days, a2 = alerts_by_system(EXP2_DIR, pid, s, False)
            _, a4 = alerts_by_system(EXP3_DIR, pid, s, False)
            ex = {int(r["day"]): r["predicted_scenario"] in EXERTION for r in load_rows(EXP3_DIR, pid, s)}
            for d, x2, x4 in zip(days, a2["deployed"], a4["deployed"]):
                if d < 8 or not x2:
                    continue
                r = 7 if d < 15 else 14
                key = "eligible" if not any(ex[k] for k in range(r + 1, d + 1)) else "other"
                res[f"{key}_exp2_alert_days"] += 1
                res[f"{key}_still_alert_exp3"] += bool(x4)
    return res


def stuck_state(results_dir, patients):
    """Secondary: Pulse-HIGH days and the share with end-of-encounter HR < 50 bpm; and (Amendment 1)
    collapse days, completed days with end HR < 30 bpm or end MAP < 50 mmHg."""
    high = low_hr = collapse = 0
    collapse_series = set()
    for pid in patients:
        for s in SEEDS:
            for r in load_rows(results_dir, pid, s):
                if r["risk_bucket"] == "HIGH":
                    high += 1
                    low_hr += _f(r["pulse_hr_end"]) < 50
                if r["run_status"] == "complete" and (_f(r["pulse_hr_end"]) < 30 or _f(r["pulse_map_end"]) < 50):
                    collapse += 1
                    collapse_series.add((pid, s))
    return {"high_days": high, "high_days_hr_end_below_50": low_hr,
            "collapse_days": collapse, "collapse_series": len(collapse_series)}


def anchor_on_high_days(patients):
    """Secondary: MAP drop against the chain baseline on Pulse-HIGH days."""
    v = [_f(r["anchor_map_drop_mmhg"]) for pid in patients for s in SEEDS
         for r in load_rows(EXP3_DIR, pid, s) if r["risk_bucket"] == "HIGH" and r["anchor_map_drop_mmhg"] != ""]
    return {"n": len(v), "median_map_drop_vs_baseline": round(float(np.median(v)), 2) if v else None,
            "share_ge_20": round(float(np.mean([x >= 20 for x in v])), 3) if v else None}


def main():
    cohort = yaml.safe_load(COHORT_PATH.read_text())
    patients = list(cohort["patients"])
    onsets = {pid: onset_day(cfg) for pid, cfg in cohort["patients"].items()}
    result = {"integrity": integrity(patients), "P1_drift": drift_groups(patients)}
    for name, d in (("exp2", EXP2_DIR), ("exp3", EXP3_DIR)):
        acc, acc_onset, total = label_accuracy(d, cohort, SEEDS, onsets)
        r = {"label_accuracy": acc, "label_accuracy_pre_onset_stable": acc_onset, "patient_days": total,
             "failed_pulse_days": sum(row["run_status"] != "complete" for pid in patients for s in SEEDS
                                      for row in load_rows(d, pid, s)),
             "alert_days": alert_days(d, onsets), "stuck_state": stuck_state(d, patients)}
        for mode in (False, True):
            data = {(pid, s): alerts_by_system(d, pid, s, mode) for pid in CATCH + QUIET for s in SEEDS}
            r["failed_as_alert" if mode else "failed_as_no_alert"] = system_metrics(data, onsets, np.random.default_rng(42))
        result[name] = r
    result["reset_eligible_check"] = reset_eligible_check(onsets)
    result["anchor_on_high_days"] = anchor_on_high_days(patients)
    OUT.write_text(json.dumps(result, indent=1, default=str))

    print(json.dumps(result["integrity"], indent=1))
    print("P1 drift:", json.dumps(result["P1_drift"], indent=1))
    for name in ("exp2", "exp3"):
        r = result[name]; m = r["failed_as_no_alert"]["deployed"]
        print(f"== {name}: label acc {r['label_accuracy']}, failed days {r['failed_pulse_days']}, "
              f"sens {m['sensitivity'][0]}/30, pre-onset {m['pre_onset_alerts_per_100']}/100 ({m['pre_onset_series'][0]}/30), "
              f"strict {m['strict'][0]}/30, FA {m['fa_per_100pd']}, silent {m['quiet_silent'][0]}/18")
        print("   alert days:", r["alert_days"], "stuck:", r["stuck_state"])
    print("reset-eligible check:", result["reset_eligible_check"])
    print("anchor on HIGH days:", result["anchor_on_high_days"])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
