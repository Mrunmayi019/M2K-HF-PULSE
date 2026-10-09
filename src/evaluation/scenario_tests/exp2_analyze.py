"""Experiment 2 analysis against results/scenario_tests/exp2/PREREGISTRATION.md, with Experiment 1
computed the same way. No Pulse runs; reads the saved daily_results CSVs only.

Usage:
    PYTHONPATH=. python3 -m src.evaluation.scenario_tests.exp2_analyze
"""
from __future__ import annotations

import csv
import json
import pathlib

import numpy as np
import yaml

from src.evaluation.scenario_tests.ablation_eval import onset_day, series, wilson

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
EXPERIMENTS = {
    "exp1": (REPO_ROOT / "results/scenario_tests", REPO_ROOT / "config/scenario_tests/cohort.yaml", range(42, 48)),
    "exp2": (REPO_ROOT / "results/scenario_tests/exp2", REPO_ROOT / "config/scenario_tests/cohort_exp2.yaml", range(48, 54)),
}
OUT = REPO_ROOT / "results/scenario_tests/exp2/exp2_analysis.json"
CATCH = ["P04", "P05", "P06", "P07", "P10"]
QUIET = ["P01", "P08", "P09"]
EXPECTED_LABEL = {"P01": "stable", "P02": "stable", "P03": "stable", "P04": "fluid_overload",
                  "P05": "deconditioning", "P06": "cardiac_stress", "P07": "acute_deterioration",
                  "P08": "stable", "P09": "stable", "P10": "acute_deterioration"}
EXERTION = {"cardiac_stress", "acute_deterioration"}
RF_THRESHOLD = 0.55


def load_rows(results_dir, pid, seed):
    with open(results_dir / f"daily_results_{pid}_seed{seed}.csv") as f:
        return sorted(csv.DictReader(f), key=lambda r: int(r["day"]))


def alerts_by_system(results_dir, pid, seed, failed_as_alert):
    s = series(results_dir, pid, seed, failed_as_alert)
    rows = load_rows(results_dir, pid, seed)
    sev = [float(r["predicted_severity"]) if r["predicted_severity"] else None for r in rows]
    return s["day"], {
        "deployed": s["decide_alert"],
        "pulse_high": s["pulse_high"],
        "rf_0.55": [v is not None and v > RF_THRESHOLD for v in sev],
        "rf_0.15": s["rf_severity"],
        "label_rule": [r["predicted_scenario"] in EXERTION for r in rows],
        "weight_rule": s["weight_rule"],
    }


def system_metrics(data, onsets, rng):
    out = {}
    for system in next(iter(data.values()))[1]:
        loose = strict = pre_series = pre_days = pre_n = 0
        fa, n, silent, per_patient = [], [], 0, {}
        for (pid, seed), (days, al) in data.items():
            a = al[system]
            hits = [d for d, x in zip(days, a) if x]
            if pid in CATCH:
                on = onsets[pid]
                caught = any(d >= on for d in hits)
                loose += caught
                strict += bool(hits) and hits[0] >= on
                pre = [x for d, x in zip(days, a) if d < on]
                pre_series += any(pre); pre_days += sum(pre); pre_n += len(pre)
                per_patient[pid] = per_patient.get(pid, 0) + caught
            elif pid in QUIET:
                fa.append(sum(a)); n.append(len(a)); silent += not any(a)
                per_patient[pid] = per_patient.get(pid, 0) + (not any(a))
        fa, n = np.array(fa), np.array(n)
        boots = [100 * fa[i].sum() / n[i].sum() for i in (rng.integers(0, len(fa), len(fa)) for _ in range(2000))]
        out[system] = {
            "sensitivity": [loose, 30, *[round(x, 3) for x in wilson(loose, 30)]],
            "pre_onset_alerts_per_100": round(100 * pre_days / pre_n, 1), "pre_onset_days": [pre_days, pre_n],
            "pre_onset_series": [pre_series, 30],
            "strict": [strict, 30],
            "fa_per_100pd": [round(100 * fa.sum() / n.sum(), 1), *[round(x, 1) for x in np.percentile(boots, [2.5, 97.5])]],
            "quiet_silent": [silent, 18],
            "per_patient": per_patient,  # catch: series caught (loose); quiet: series silent
        }
    return out


def label_accuracy(results_dir, cohort, seeds, onsets):
    ok = ok_onset = total = 0
    for pid, cfg in cohort["patients"].items():
        on = onsets.get(pid)
        for s in seeds:
            for r in load_rows(results_dir, pid, s):
                d, lab = int(r["day"]), r["predicted_scenario"]
                total += 1
                ok += lab == EXPECTED_LABEL[pid]
                ok_onset += lab == ("stable" if on is None or d < on else EXPECTED_LABEL[pid])
    return round(ok / total, 4), round(ok_onset / total, 4), total


def failed_days(results_dir, cohort, seeds):
    return sum(r["run_status"] != "complete" for pid in cohort["patients"] for s in seeds
               for r in load_rows(results_dir, pid, s))


def main():
    result = {}
    for name, (results_dir, cohort_path, seeds) in EXPERIMENTS.items():
        cohort = yaml.safe_load(cohort_path.read_text())
        onsets = {pid: onset_day(cfg) for pid, cfg in cohort["patients"].items()}
        acc, acc_onset, total = label_accuracy(results_dir, cohort, seeds, onsets)
        result[name] = {"label_accuracy": acc, "label_accuracy_pre_onset_stable": acc_onset, "patient_days": total,
                        "failed_pulse_days": failed_days(results_dir, cohort, seeds)}
        for mode in (False, True):
            data = {(pid, s): alerts_by_system(results_dir, pid, s, mode)
                    for pid in CATCH + QUIET for s in seeds}
            result[name]["failed_as_alert" if mode else "failed_as_no_alert"] = system_metrics(
                data, onsets, np.random.default_rng(42))
    OUT.write_text(json.dumps(result, indent=1))
    for name in EXPERIMENTS:
        r = result[name]; m = r["failed_as_no_alert"]
        print(f"== {name}: label acc {r['label_accuracy']} (pre-onset=stable {r['label_accuracy_pre_onset_stable']}), "
              f"failed Pulse days {r['failed_pulse_days']}")
        for system, v in m.items():
            print(f"  {system:<11} sens {v['sensitivity'][0]}/30  pre-onset {v['pre_onset_alerts_per_100']}/100 "
                  f"({v['pre_onset_series'][0]}/30 series)  strict {v['strict'][0]}/30  FA {v['fa_per_100pd']}  "
                  f"silent {v['quiet_silent'][0]}/18  {v['per_patient']}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
