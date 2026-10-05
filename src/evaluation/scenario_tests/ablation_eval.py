"""Alert-system ablation on the saved pre-registered scenario-test runs (no new Pulse runs).

Compares five alert definitions on the identical saved 21-day data, so any difference is due to
the alert definition alone:

  weight_rule   >= 2.0 kg weight gain within a 3-day window (simple clinical heuristic)
  rf_severity   classifier severity > STABLE_SEVERITY_CAP (0.15) -- ML only, no physiology
  pulse_high    real compute_risk_score() on the saved Pulse output, risk_bucket == HIGH
  decide_alert  the deployed decide_alert() level == ALERT (includes the C3 component guard)
  decide_watch  the deployed decide_alert() level in {ALERT, WATCH}

Metrics, per seed set (dev 42-44, held-out 45-47, all six):
  - pre-registered: should-catch patients alerting in all 3 seeds; stay-quiet patients silent in
    all 3 seeds (only for the 3-seed sets)
  - per-series sensitivity: should-catch patient-seed series with >= 1 alert on/after the story's
    onset day (first scheduled event), Wilson 95% CI
  - per-series specificity: stay-quiet series with zero alert days, Wilson 95% CI
  - false alerts per 100 patient-days in the stay-quiet group, percentile-bootstrap 95% CI over
    series (2000 resamples, seed 42)
  - pre-onset alert days in the should-catch group (alerts before anything was designed to happen)
Failed Pulse days are scored two ways for the physiology-based systems: as an alert (the deployed
fallback path) and as no alert.

Usage (scenario-test CSVs and cohort.yaml live on feature/scenario-testing):
    PYTHONPATH=. python3 -m src.evaluation.scenario_tests.ablation_eval \
        --results-dir <dir with daily_results_P??_seed??.csv> --cohort <cohort.yaml> --out <json>
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib

import numpy as np
import yaml

from src.analytics.risk_score import compute_risk_score
from src.analytics.score_reporting import (
    AlertAssessmentView, compute_baseline_high_streak, decide_alert,
)

PATIENTS = [f"P{i:02d}" for i in range(1, 11)]
SEED_SETS = {"dev": (42, 43, 44), "heldout": (45, 46, 47), "all": (42, 43, 44, 45, 46, 47)}
SEVERITY_ALERT = 0.15  # STABLE_SEVERITY_CAP
WEIGHT_GAIN_KG, WEIGHT_WINDOW_DAYS = 2.0, 3
SYSTEMS = ["weight_rule", "rf_severity", "pulse_high", "decide_alert", "decide_watch"]
PHYSIOLOGY_SYSTEMS = {"pulse_high", "decide_alert", "decide_watch"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def onset_day(patient: dict) -> int | None:
    days = [d["day"] for d in patient["monitored_day_schedule"] if d.get("event")]
    return min(days) if days else None


def series(results_dir: pathlib.Path, pid: str, seed: int, failed_as_alert: bool) -> dict[str, list]:
    """Per-day alert booleans for every system, plus the day numbers."""
    with open(results_dir / f"daily_results_{pid}_seed{seed}.csv") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: int(r["day"]))
    out = {s: [] for s in SYSTEMS}
    out["day"] = [int(r["day"]) for r in rows]
    weights = [float(r["wearable_weight_kg"]) for r in rows]
    prev_streak, prev_instab = None, None
    for i, r in enumerate(rows):
        lo = max(0, i - (WEIGHT_WINDOW_DAYS - 1))
        out["weight_rule"].append(weights[i] - min(weights[lo:i + 1]) >= WEIGHT_GAIN_KG)
        sev = float(r["predicted_severity"]) if r["predicted_severity"] else None
        out["rf_severity"].append(sev is not None and sev > SEVERITY_ALERT)
        if r["run_status"] != "complete":
            for s in PHYSIOLOGY_SYSTEMS:
                out[s].append(failed_as_alert)
            prev_streak, prev_instab = None, None
            continue
        map_start = float(r["pulse_map_start"])
        co_start = float(r["pulse_co_start"])
        instab = int(float(r["pulse_instability_flag"]))
        risk = compute_risk_score(
            hr_rise=float(r["pulse_hr_end"]) - float(r["pulse_hr_start"]),
            map_drop=map_start - float(r["pulse_map_end"]),
            co_drop_pct=(co_start - float(r["pulse_co_end"])) / co_start * 100 if co_start else 0.0,
            compensation_flag=int(float(r["pulse_compensation_flag"])), instability_flag=instab,
            map_start=map_start,
        )
        streak, seen = compute_baseline_high_streak(
            previous_streak_days=prev_streak, previous_instability_seen=prev_instab,
            risk_bucket=risk["risk_bucket"], dominant_mechanism=risk["dominant_mechanism"],
            instability_flag=instab,
        )
        level = decide_alert(AlertAssessmentView(
            severity=sev, risk_score=risk["risk_score"], risk_bucket=risk["risk_bucket"],
            dominant_mechanism=risk["dominant_mechanism"], baseline_high_streak_days=streak,
            instability_seen_in_streak=seen,
        ), "valid").level
        out["pulse_high"].append(risk["risk_bucket"] == "HIGH")
        out["decide_alert"].append(level == "ALERT")
        out["decide_watch"].append(level in ("ALERT", "WATCH"))
        prev_streak, prev_instab = streak, seen
    return out


def evaluate(results_dir, cohort, seeds, failed_as_alert):
    rng = np.random.default_rng(42)
    res = {}
    groups = {pid: cohort["patients"][pid]["expected_group"] for pid in PATIENTS}
    onsets = {pid: onset_day(cohort["patients"][pid]) for pid in PATIENTS}
    data = {(pid, s): series(results_dir, pid, s, failed_as_alert) for pid in PATIENTS for s in seeds}
    for sysname in SYSTEMS:
        catch = [p for p in PATIENTS if groups[p] == "should_catch"]
        quiet = [p for p in PATIENTS if groups[p] == "should_stay_quiet"]
        det, lead, pre_onset = [], [], 0
        for p in catch:
            for s in seeds:
                d = data[(p, s)]
                post = [day for day, a in zip(d["day"], d[sysname]) if a and day >= onsets[p]]
                pre_onset += sum(1 for day, a in zip(d["day"], d[sysname]) if a and day < onsets[p])
                det.append(bool(post))
                if post:
                    lead.append(post[0] - onsets[p])
        quiet_series = [data[(p, s)][sysname] for p in quiet for s in seeds]
        fa = np.array([sum(x) for x in quiet_series]); days = np.array([len(x) for x in quiet_series])
        boots = []
        for _ in range(2000):
            idx = rng.integers(0, len(fa), len(fa))
            boots.append(100 * fa[idx].sum() / days[idx].sum())
        k_det, n_det = sum(det), len(det)
        k_spec = int(sum(1 for x in quiet_series if not any(x)))
        entry = {
            "sensitivity_series": [k_det, n_det, *wilson(k_det, n_det)],
            "specificity_series": [k_spec, len(quiet_series), *wilson(k_spec, len(quiet_series))],
            "false_alerts_per_100pd": [100 * fa.sum() / days.sum(), *np.percentile(boots, [2.5, 97.5])],
            "median_days_onset_to_first_alert": float(np.median(lead)) if lead else None,
            "pre_onset_alert_days_should_catch": pre_onset,
        }
        if len(seeds) == 3:
            entry["prereg_caught"] = [p for p in catch if all(
                any(a and day >= onsets[p] for day, a in zip(data[(p, s)]["day"], data[(p, s)][sysname]))
                for s in seeds)]
            entry["prereg_quiet"] = [p for p in quiet if all(not any(data[(p, s)][sysname]) for s in seeds)]
        res[sysname] = entry
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", type=pathlib.Path, required=True)
    ap.add_argument("--cohort", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    a = ap.parse_args()
    cohort = yaml.safe_load(a.cohort.read_text())
    out = {}
    for fa_mode in (True, False):
        key = "failed_as_alert" if fa_mode else "failed_as_no_alert"
        out[key] = {name: evaluate(a.results_dir, cohort, seeds, fa_mode) for name, seeds in SEED_SETS.items()}
    n_failed = 0
    for pid in PATIENTS:
        for s in SEED_SETS["all"]:
            with open(a.results_dir / f"daily_results_{pid}_seed{s}.csv") as f:
                n_failed += sum(1 for r in csv.DictReader(f) if r["run_status"] != "complete")
    out["failed_pulse_days_total"] = n_failed
    out["onset_days"] = {pid: onset_day(cohort["patients"][pid]) for pid in PATIENTS}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, indent=2, default=float))
    for key in ("failed_as_alert", "failed_as_no_alert"):
        print(f"\n##### {key}")
        for name in SEED_SETS:
            print(f"--- {name}")
            for sysname, e in out[key][name].items():
                s, sp, fa = e["sensitivity_series"], e["specificity_series"], e["false_alerts_per_100pd"]
                pre = f" prereg caught={e['prereg_caught']} quiet={e['prereg_quiet']}" if "prereg_caught" in e else ""
                print(f"{sysname:13s} sens {s[0]}/{s[1]} [{s[2]:.2f},{s[3]:.2f}]  spec {sp[0]}/{sp[1]} "
                      f"[{sp[2]:.2f},{sp[3]:.2f}]  FA/100pd {fa[0]:.1f} [{fa[1]:.1f},{fa[2]:.1f}]  "
                      f"lead {e['median_days_onset_to_first_alert']}  pre-onset {e['pre_onset_alert_days_should_catch']}{pre}")
    print("failed Pulse days:", n_failed, "onsets:", out["onset_days"])


if __name__ == "__main__":
    main()
