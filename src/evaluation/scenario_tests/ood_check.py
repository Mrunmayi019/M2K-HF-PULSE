"""Item 2 (2026-10-07 follow-up): is the scenario cohort out-of-distribution for the classifier?
Builds each of the 10 patients' monitored-day-1 feature vector from their 21 FLAT (noiseless)
baseline_wearable days (before any story), via the real build_inference_features(), and compares
against the real training data's per-feature distribution for "stable" and "deconditioning".
Also reports the frozen classifier's own prediction on these baseline-only vectors. Read-only,
no code changes, no new Pulse runs.

Usage:
    PYTHONPATH=. python3 -m src.evaluation.scenario_tests.ood_check
"""
from __future__ import annotations

import json
import pathlib

import joblib
import numpy as np
import pandas as pd
import yaml

from src.scenario_classifier.features import build_features, build_inference_features, feature_columns

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
COHORT_PATH = REPO_ROOT / "config" / "scenario_tests" / "cohort.yaml"
PATIENTS_CSV = REPO_ROOT / "data" / "synthetic" / "patients.csv"
TRENDS_CSV = REPO_ROOT / "data" / "synthetic" / "wearable_trends.csv"
OUT_DIR = REPO_ROOT / "results" / "scenario_tests" / "posthoc"

VITALS = ["resting_hr_bpm", "spo2_pct", "weight_kg", "steps_per_day", "sleep_hours", "hrv_rmssd_ms"]
BASELINE_DAYS = 21


def build_patient_day1_features(pid: str, cfg: dict) -> pd.DataFrame:
    demo = cfg["demographics"]
    clin = cfg["baseline_clinical_report"]
    bw = cfg["baseline_wearable"]
    bmi = demo["weight_kg"] / (demo["height_cm"] / 100.0) ** 2
    patient_row = {
        "patient_id": pid, "age": demo["age"], "sex": demo["sex"], "bmi": bmi,
        "ejection_fraction_pct": clin["ejection_fraction_pct"], "nt_probnp_pg_ml": clin["nt_probnp_pg_ml"],
    }
    # FLAT, noiseless baseline -- the generator's own intended stable starting point, before any
    # per-day noise or story event. One row per day, same value every day (slope = 0 by
    # construction for every vital).
    trends_rows = [{"patient_id": pid, "day": d, **{v: bw[v] for v in VITALS}} for d in range(BASELINE_DAYS)]
    trends_df = pd.DataFrame(trends_rows)
    return build_inference_features(patient_row, trends_df)


def main():
    cohort = yaml.safe_load(COHORT_PATH.read_text())
    clf = joblib.load(REPO_ROOT / "models" / "scenario_classifier.joblib")
    reg = joblib.load(REPO_ROOT / "models" / "severity_regressor.joblib")

    # Training distribution, per scenario_type, same real feature pipeline.
    patients_df = pd.read_csv(PATIENTS_CSV)
    trends_df_train = pd.read_csv(TRENDS_CSV)
    train_features = build_features(patients_df, trends_df_train)
    cols = feature_columns(train_features)

    stats = {}
    for label in ("stable", "deconditioning"):
        sub = train_features[train_features["scenario_type"] == label]
        stats[label] = {"mean": sub[cols].mean(), "std": sub[cols].std()}

    results = {}
    for pid, cfg in cohort["patients"].items():
        feats = build_patient_day1_features(pid, cfg)
        x = feats[cols]
        pred_scenario = clf.predict(x)[0]
        pred_severity = float(reg.predict(x)[0])
        z_stable = {c: round(float((x[c].iloc[0] - stats["stable"]["mean"][c]) / stats["stable"]["std"][c]), 3)
                    for c in cols}
        z_deconditioning = {c: round(float((x[c].iloc[0] - stats["deconditioning"]["mean"][c]) / stats["deconditioning"]["std"][c]), 3)
                             for c in cols}
        results[pid] = {
            "predicted_scenario_day1_baseline": pred_scenario,
            "predicted_severity_day1_baseline": round(pred_severity, 4),
            "raw_values": {c: round(float(x[c].iloc[0]), 3) for c in cols},
            "z_vs_stable": z_stable,
            "z_vs_deconditioning": z_deconditioning,
        }
        print(f"{pid}: predicted={pred_scenario} severity={pred_severity:.4f}")
        worst = sorted(z_stable.items(), key=lambda kv: abs(kv[1]), reverse=True)[:5]
        print(f"  top |z vs stable|: {worst}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "ood_check.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    # Training-distribution summary for the 6 raw wearable vitals' FIRST7_MEAN (closest analogue
    # to "baseline level") and SLOPE (closest analogue to "day-to-day structure"), stable class.
    print("\nTraining data, scenario_type=stable, first7_mean + slope (mean +- std):")
    for v in VITALS:
        m1, s1 = stats["stable"]["mean"][f"{v}_first7_mean"], stats["stable"]["std"][f"{v}_first7_mean"]
        m2, s2 = stats["stable"]["mean"][f"{v}_slope"], stats["stable"]["std"][f"{v}_slope"]
        print(f"  {v}: first7_mean {m1:.2f}+-{s1:.2f}, slope {m2:.4f}+-{s2:.4f}")


if __name__ == "__main__":
    main()
