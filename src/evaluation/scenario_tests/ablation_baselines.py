"""Fairer classifier-only baselines for the alert ablation, and the scenario-label confusion matrix.

Answers two review questions on the saved pre-registered scenario-test runs (no new Pulse runs):
  1. Does the Pulse layer beat the classifier when the classifier's own alert threshold is tuned,
     and does it beat a rule that uses only the predicted label (exertion scenarios) -- i.e. is the
     filtering effect physiological or just label gating?
  2. What does the classifier actually predict day by day (confusion matrix), and how does the
     predicted label relate to the Pulse risk bucket?

Usage:
    PYTHONPATH=. python3 -m src.evaluation.scenario_tests.ablation_baselines \
        --results-dir <dir with daily_results_P??_seed??.csv> --cohort <cohort.yaml> --out <json>
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
from collections import Counter

import numpy as np
import yaml

from src.evaluation.scenario_tests.ablation_eval import PATIENTS, onset_day, series, wilson

SEEDS = (42, 43, 44, 45, 46, 47)
EXPECTED_LABEL = {"P01": "stable", "P02": "stable", "P03": "stable", "P04": "fluid_overload",
                  "P05": "deconditioning", "P06": "cardiac_stress", "P07": "acute_deterioration",
                  "P08": "stable", "P09": "stable", "P10": "acute_deterioration"}
LABELS = ["stable", "fluid_overload", "cardiac_stress", "deconditioning", "acute_deterioration"]
EXERTION = {"cardiac_stress", "acute_deterioration"}


def load(results_dir, pid, seed):
    with open(results_dir / f"daily_results_{pid}_seed{seed}.csv") as f:
        return sorted(csv.DictReader(f), key=lambda r: int(r["day"]))


def metrics(alerts: dict, groups: dict, onsets: dict, rng) -> dict:
    """alerts[(pid, seed)] = list of (day, bool)."""
    det, quiet = [], []
    for (pid, seed), days in alerts.items():
        if groups[pid] == "should_catch":
            det.append(any(a and d >= onsets[pid] for d, a in days))
        elif groups[pid] == "should_stay_quiet":
            quiet.append([a for _, a in days])
    fa = np.array([sum(q) for q in quiet]); n = np.array([len(q) for q in quiet])
    boots = [100 * fa[i].sum() / n[i].sum() for i in (rng.integers(0, len(fa), len(fa)) for _ in range(2000))]
    k = sum(det)
    return {"sens": [k, len(det), *wilson(k, len(det))], "fa_per_100pd": [100 * fa.sum() / n.sum(), *np.percentile(boots, [2.5, 97.5])],
            "quiet_series_silent": int(sum(1 for q in quiet if not any(q)))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", type=pathlib.Path, required=True)
    ap.add_argument("--cohort", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    a = ap.parse_args()
    cohort = yaml.safe_load(a.cohort.read_text())
    groups = {p: cohort["patients"][p]["expected_group"] for p in PATIENTS}
    onsets = {p: onset_day(cohort["patients"][p]) for p in PATIENTS}
    rows = {(p, s): load(a.results_dir, p, s) for p in PATIENTS for s in SEEDS}
    deployed = {(p, s): series(a.results_dir, p, s, True) for p in PATIENTS for s in SEEDS}
    out = {}

    # 1a. classifier severity threshold sweep
    sweep = []
    for thr in np.round(np.arange(0.15, 0.96, 0.05), 2):
        al = {k: [(int(r["day"]), bool(r["predicted_severity"]) and float(r["predicted_severity"]) > thr) for r in v]
              for k, v in rows.items()}
        sweep.append({"threshold": float(thr), **metrics(al, groups, onsets, np.random.default_rng(42))})
    out["severity_threshold_sweep"] = sweep

    # 1b. label-only and label+severity rules, and the deployed system for reference
    def rule(fn):
        return {k: [(int(r["day"]), fn(r)) for r in v] for k, v in rows.items()}
    rules = {
        "label_exertion": rule(lambda r: r["predicted_scenario"] in EXERTION),
        "label_exertion_and_sev>0.15": rule(lambda r: r["predicted_scenario"] in EXERTION and float(r["predicted_severity"] or 0) > 0.15),
        "label_not_deconditioning_or_stable_and_sev>0.15": rule(lambda r: r["predicted_scenario"] not in ("stable", "deconditioning") and float(r["predicted_severity"] or 0) > 0.15),
        "pulse_high": {k: list(zip(v["day"], v["pulse_high"])) for k, v in deployed.items()},
        "deployed_decide_alert": {k: list(zip(v["day"], v["decide_alert"])) for k, v in deployed.items()},
    }
    out["rules"] = {name: metrics(al, groups, onsets, np.random.default_rng(42)) for name, al in rules.items()}

    # 1c. agreement between label_exertion and pulse_high, day by day
    agree = Counter()
    for k in rows:
        for (d1, x), (d2, y) in zip(rules["label_exertion"][k], rules["pulse_high"][k]):
            agree[(bool(x), bool(y))] += 1
    out["label_exertion_vs_pulse_high_days"] = {f"label={x},high={y}": c for (x, y), c in sorted(agree.items())}

    # 2. confusion matrices (story label for all days; and onset-aware: pre-onset days expected stable)
    cm_all, cm_onset = Counter(), Counter()
    high_by_label, n_by_label = Counter(), Counter()
    for (p, s), v in rows.items():
        for r in v:
            pred = r["predicted_scenario"]
            cm_all[(EXPECTED_LABEL[p], pred)] += 1
            exp = EXPECTED_LABEL[p] if (onsets[p] is not None and int(r["day"]) >= onsets[p]) else "stable"
            cm_onset[(exp, pred)] += 1
            if r["run_status"] == "complete":
                n_by_label[pred] += 1
                high_by_label[pred] += r["risk_bucket"] == "HIGH"
    def mat(cm):
        return {t: {p_: cm[(t, p_)] for p_ in LABELS} for t in LABELS}
    out["confusion_story_label"] = mat(cm_all)
    out["confusion_onset_aware"] = mat(cm_onset)
    out["accuracy_story_label"] = sum(cm_all[(l, l)] for l in LABELS) / sum(cm_all.values())
    out["accuracy_onset_aware"] = sum(cm_onset[(l, l)] for l in LABELS) / sum(cm_onset.values())
    out["predicted_label_share"] = {l: sum(cm_all[(t, l)] for t in LABELS) / sum(cm_all.values()) for l in LABELS}
    out["p_high_given_label"] = {l: [high_by_label[l], n_by_label[l]] for l in LABELS}

    a.out.write_text(json.dumps(out, indent=2, default=float))
    print("SWEEP thr: sens  FA/100pd  quiet_silent")
    for e in sweep:
        print(f"  {e['threshold']:.2f}: {e['sens'][0]}/{e['sens'][1]}  {e['fa_per_100pd'][0]:5.1f} [{e['fa_per_100pd'][1]:.1f},{e['fa_per_100pd'][2]:.1f}]  {e['quiet_series_silent']}/18")
    print("RULES")
    for k, e in out["rules"].items():
        print(f"  {k:48s} sens {e['sens'][0]}/{e['sens'][1]}  FA {e['fa_per_100pd'][0]:.1f} [{e['fa_per_100pd'][1]:.1f},{e['fa_per_100pd'][2]:.1f}]  silent {e['quiet_series_silent']}/18")
    print("label_exertion vs pulse_high days:", out["label_exertion_vs_pulse_high_days"])
    print("acc story/onset:", round(out["accuracy_story_label"], 4), round(out["accuracy_onset_aware"], 4))
    print("pred share:", {k: round(v, 3) for k, v in out["predicted_label_share"].items()})
    print("P(HIGH|label):", out["p_high_given_label"])
    for name in ("confusion_story_label", "confusion_onset_aware"):
        print(name)
        for t in LABELS:
            print(f"  {t:20s}", [out[name][t][p] for p in LABELS])


if __name__ == "__main__":
    main()


def dev_heldout_threshold(results_dir: pathlib.Path, cohort_path: pathlib.Path) -> dict:
    """Select the classifier-severity threshold on dev seeds only, then evaluate once on held-out
    seeds -- the same protocol used to select C3. Selection rule (fixed before looking at held-out):
    the lowest threshold whose dev false-alert rate is <= the deployed system's dev rate (5.82 per
    100 patient-days), i.e. matched specificity, maximum sensitivity."""
    cohort = yaml.safe_load(cohort_path.read_text())
    groups = {p: cohort["patients"][p]["expected_group"] for p in PATIENTS}
    onsets = {p: onset_day(cohort["patients"][p]) for p in PATIENTS}
    res = {}
    for name, seeds in (("dev", (42, 43, 44)), ("heldout", (45, 46, 47))):
        rows = {(p, s): load(results_dir, p, s) for p in PATIENTS for s in seeds}
        dep = {(p, s): series(results_dir, p, s, True) for p in PATIENTS for s in seeds}
        res[name] = {"deployed": metrics({k: list(zip(v["day"], v["decide_alert"])) for k, v in dep.items()}, groups, onsets, np.random.default_rng(42))}
        for thr in np.round(np.arange(0.15, 0.96, 0.01), 2):
            al = {k: [(int(r["day"]), bool(r["predicted_severity"]) and float(r["predicted_severity"]) > thr) for r in v] for k, v in rows.items()}
            res[name][f"{thr:.2f}"] = metrics(al, groups, onsets, np.random.default_rng(42))
    target = res["dev"]["deployed"]["fa_per_100pd"][0]
    chosen = min(float(t) for t, m in res["dev"].items() if t != "deployed" and m["fa_per_100pd"][0] <= target)
    return {"selection_rule": "lowest threshold with dev FA <= deployed dev FA", "deployed_dev_fa": target,
            "chosen_threshold": chosen, "dev": {"classifier": res["dev"][f"{chosen:.2f}"], "deployed": res["dev"]["deployed"]},
            "heldout": {"classifier": res["heldout"][f"{chosen:.2f}"], "deployed": res["heldout"]["deployed"]}}
