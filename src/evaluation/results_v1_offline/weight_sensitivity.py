"""results-v1 offline analysis (2/4): scorer weight sensitivity (+-10%, +-20%) on seeds 42-47.
Offline -- reuses the saved Pulse features from the scenario-test batches (dev 42-44, held-out
45-47), no new Pulse runs. Monkey-patches src.analytics.risk_score.WEIGHTS (module global,
restored after each perturbation) and calls the REAL compute_risk_score(); never reimplements the
weighted-sum formula. Does not modify risk_score.py itself.

Usage:
    PYTHONPATH=. python3 -m src.evaluation.results_v1_offline.weight_sensitivity
"""
from __future__ import annotations

import csv
import json
import pathlib

import yaml

import src.analytics.risk_score as risk_score_module
from src.analytics.risk_score import compute_risk_score

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "results" / "scenario_tests"
COHORT_PATH = REPO_ROOT / "config" / "scenario_tests" / "cohort.yaml"
OUT_DIR = REPO_ROOT / "results" / "results_v1_offline"

PATIENTS = [f"P{i:02d}" for i in range(1, 11)]
ALL_SEEDS = (42, 43, 44, 45, 46, 47)
BASE_WEIGHTS = dict(risk_score_module.WEIGHTS)
DELTAS = (-0.20, -0.10, 0.0, 0.10, 0.20)


def load_rows(pid: str, seed: int):
    path = RESULTS_DIR / f"daily_results_{pid}_seed{seed}.csv"
    with open(path) as f:
        return sorted(csv.DictReader(f), key=lambda r: int(r["day"]))


def day_risk_bucket(row: dict) -> str | None:
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
    return risk["risk_bucket"]


def perturbed_weights(key: str, delta: float) -> dict:
    w = dict(BASE_WEIGHTS)
    w[key] = max(0.0, w[key] * (1 + delta))
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}


def evaluate_under_weights(weights: dict) -> dict:
    risk_score_module.WEIGHTS = weights
    try:
        cohort = yaml.safe_load(COHORT_PATH.read_text())
        should_catch_detected = 0
        should_catch_total = 0
        quiet_false_alert_series = 0
        quiet_total_series = 0
        for pid in PATIENTS:
            cfg = cohort["patients"][pid]
            group = cfg["expected_group"]
            pstart = next((d["day"] for d in cfg["monitored_day_schedule"] if d.get("event")), None)
            for seed in ALL_SEEDS:
                rows = load_rows(pid, seed)
                buckets = [(int(r["day"]), day_risk_bucket(r)) for r in rows]
                if group == "should_catch":
                    should_catch_total += 1
                    if any(b == "HIGH" and d >= pstart for d, b in buckets):
                        should_catch_detected += 1
                elif group == "should_stay_quiet":
                    quiet_total_series += 1
                    if any(b == "HIGH" for _, b in buckets):
                        quiet_false_alert_series += 1
        return {
            "should_catch_detected": should_catch_detected,
            "should_catch_total": should_catch_total,
            "quiet_false_alert_series": quiet_false_alert_series,
            "quiet_total_series": quiet_total_series,
        }
    finally:
        risk_score_module.WEIGHTS = BASE_WEIGHTS


def main():
    print("Baseline weights:", BASE_WEIGHTS)
    baseline = evaluate_under_weights(dict(BASE_WEIGHTS))
    print("Baseline:", baseline)

    results = {"baseline": baseline}
    for key in BASE_WEIGHTS:
        results[key] = {}
        for delta in DELTAS:
            if delta == 0.0:
                results[key]["0%"] = baseline
                continue
            w = perturbed_weights(key, delta)
            r = evaluate_under_weights(w)
            label = f"{'+' if delta > 0 else ''}{int(delta*100)}%"
            results[key][label] = r
            print(f"{key} {label} (weight {BASE_WEIGHTS[key]:.2f} -> {w[key]:.3f}): "
                  f"should_catch {r['should_catch_detected']}/{r['should_catch_total']}, "
                  f"quiet false-alert series {r['quiet_false_alert_series']}/{r['quiet_total_series']}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "weight_sensitivity.json", "w") as f:
        json.dump(results, f, indent=2, default=str)


if __name__ == "__main__":
    main()
