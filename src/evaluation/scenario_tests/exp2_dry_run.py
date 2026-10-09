"""Experiment 2 classifier-only dry run (no Pulse). Disclosed in
results/scenario_tests/exp2/PREREGISTRATION.md.

The day's scenario label and severity depend only on the wearable readings and the clinical
report, never on Pulse output (continuous_state_pipeline.py: the 21 most recent readings ->
build_inference_features() -> frozen classifier/regressor). This script regenerates the exact
readings run_patient_seed.py would store -- same sha256-derived RNG, same draw order, same
population-calibrated noise -- and classifies every monitored day.

Faithfulness check: with --cohort config/scenario_tests/cohort.yaml --seeds 42 43 44 45 46 47
--validate-dir results/scenario_tests, it must reproduce every saved Experiment 1 label.

Usage:
    PYTHONPATH=. python3 -m src.evaluation.scenario_tests.exp2_dry_run \
        --cohort config/scenario_tests/cohort_exp2.yaml --seeds 42 43 44 --out <json>
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import warnings
from collections import Counter

import joblib
import numpy as np
import pandas as pd
import yaml

from src.data_synthesis.generate_patients import load_reference_stats
from src.scenario_classifier.features import build_inference_features, feature_columns

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MODELS_DIR = REPO_ROOT / "artifacts" / "results-v1" / "models"
BASELINE_DAYS = 21
WINDOW = 21
# Mirrors run_patient_seed.py (NOISE_SD_FRACTION, WEIGHT_NOISE_SD_KG, _derive_rng_seed).
NOISE_SD_FRACTION = 0.15
WEIGHT_NOISE_SD_KG = 0.3
VITALS = ["resting_hr_bpm", "spo2_pct", "weight_kg", "steps_per_day", "sleep_hours", "hrv_rmssd_ms"]
EXPECTED_LABEL = {"P01": "stable", "P02": "stable", "P03": "stable", "P04": "fluid_overload",
                  "P05": "deconditioning", "P06": "cardiac_stress", "P07": "acute_deterioration",
                  "P08": "stable", "P09": "stable", "P10": "acute_deterioration"}
EXERTION = {"cardiac_stress", "acute_deterioration"}


def noise_sds():
    wb = load_reference_stats()["wearable_baseline"]
    return {v: wb[v]["sd"] * NOISE_SD_FRACTION for v in
            ("resting_hr_bpm", "steps_per_day", "hrv_rmssd_ms", "spo2_pct", "sleep_hours")}


def rng_for(pid, seed):
    digest = hashlib.sha256(f"{pid}:{seed}".encode("utf-8")).digest()
    return np.random.default_rng(int.from_bytes(digest[:4], "big"))


def reading(level, spo2_base, rng, sd):
    """Same draw order as run_patient_seed.add_baseline_window/add_monitored_reading."""
    return {
        "resting_hr_bpm": level["resting_hr_bpm"] + rng.normal(0, sd["resting_hr_bpm"]),
        "spo2_pct": min(100.0, spo2_base + rng.normal(0, sd["spo2_pct"])),
        "weight_kg": level["weight_kg"] + rng.normal(0, WEIGHT_NOISE_SD_KG),
        "steps_per_day": max(0.0, level["steps_per_day"] + rng.normal(0, sd["steps_per_day"])),
        "sleep_hours": max(0.0, level["sleep_hours"] + rng.normal(0, sd["sleep_hours"])),
        "hrv_rmssd_ms": max(1.0, level["hrv_rmssd_ms"] + rng.normal(0, sd["hrv_rmssd_ms"])),
    }


def run_series(pid, cfg, seed, warmup_days, clf, reg, sd):
    rng = rng_for(pid, seed)
    base = cfg["baseline_wearable"]
    readings = [reading(base, base["spo2_pct"], rng, sd) for _ in range(BASELINE_DAYS)]
    for _ in range(warmup_days):
        readings.append(reading(base, base["spo2_pct"], rng, sd))
    demo, clin = cfg["demographics"], cfg["baseline_clinical_report"]
    ml_row = {"patient_id": pid, "age": demo["age"], "sex": demo["sex"],
              "bmi": demo["weight_kg"] / (demo["height_cm"] / 100.0) ** 2,
              "ejection_fraction_pct": clin["ejection_fraction_pct"], "nt_probnp_pg_ml": clin["nt_probnp_pg_ml"]}
    out = []
    for day_row in cfg["monitored_day_schedule"]:
        readings.append(reading(day_row, base["spo2_pct"], rng, sd))
        window = readings[-WINDOW:]
        trends = pd.DataFrame([{"patient_id": pid, "day": i, **{v: r[v] for v in VITALS}} for i, r in enumerate(window)])
        x = build_inference_features(ml_row, trends)
        cols = feature_columns(x)
        out.append({"day": day_row["day"], "label": str(clf.predict(x[cols])[0]),
                    "severity": round(float(reg.predict(x[cols])[0]), 4), "event": day_row.get("event")})
    return out


def onset_day(cfg):
    days = [d["day"] for d in cfg["monitored_day_schedule"] if d.get("event")]
    return min(days) if days else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", type=pathlib.Path, required=True)
    ap.add_argument("--seeds", type=int, nargs="+", required=True)
    ap.add_argument("--out", type=pathlib.Path)
    ap.add_argument("--validate-dir", type=pathlib.Path, help="compare labels against saved daily_results CSVs")
    a = ap.parse_args()

    warnings.filterwarnings("ignore")
    cohort = yaml.safe_load(a.cohort.read_text())
    warmup = int(cohort["meta"].get("warmup_days", 0))
    clf = joblib.load(MODELS_DIR / "scenario_classifier.joblib")
    reg = joblib.load(MODELS_DIR / "severity_regressor.joblib")
    sd = noise_sds()

    series = {(pid, s): run_series(pid, cfg, s, warmup, clf, reg, sd)
              for pid, cfg in cohort["patients"].items() for s in a.seeds}

    if a.validate_dir:
        match = total = 0
        for (pid, s), days in series.items():
            with open(a.validate_dir / f"daily_results_{pid}_seed{s}.csv") as f:
                saved = {int(r["day"]): r["predicted_scenario"] for r in csv.DictReader(f)}
            for d in days:
                total += 1
                match += saved[d["day"]] == d["label"]
        print(f"VALIDATION: {match}/{total} labels match the saved runs")

    summary = {"cohort": str(a.cohort), "seeds": a.seeds, "warmup_days": warmup, "per_patient": {}}
    all_days = correct = 0
    for pid, cfg in cohort["patients"].items():
        onset = onset_day(cfg)
        labels = [d["label"] for s in a.seeds for d in series[(pid, s)]]
        post = [d["label"] for s in a.seeds for d in series[(pid, s)] if onset and d["day"] >= onset]
        exertion_days = [[d["day"] for d in series[(pid, s)] if d["label"] in EXERTION] for s in a.seeds]
        n_ok = sum(l == EXPECTED_LABEL[pid] for l in labels)
        all_days += len(labels); correct += n_ok
        summary["per_patient"][pid] = {
            "expected": EXPECTED_LABEL[pid], "onset_day": onset, "label_counts": dict(Counter(labels)),
            "label_counts_from_onset": dict(Counter(post)) if onset else None,
            "label_accuracy": round(n_ok / len(labels), 3),
            "exertion_label_days_per_seed": exertion_days,
            "seeds_with_any_exertion_label": sum(bool(e) for e in exertion_days),
            "seeds_with_exertion_label_from_onset": sum(any(d >= onset for d in e) for e in exertion_days) if onset else None,
            "seeds_with_exertion_label_before_onset": sum(any(d < onset for d in e) for e in exertion_days) if onset else sum(bool(e) for e in exertion_days),
            "daily": {str(s): [(d["day"], d["label"], d["severity"]) for d in series[(pid, s)]] for s in a.seeds},
        }
    summary["overall_label_accuracy"] = round(correct / all_days, 4)
    for pid, p in summary["per_patient"].items():
        print(f"{pid} expect={p['expected']:<19} acc={p['label_accuracy']:.2f} counts={p['label_counts']} "
              f"exertion seeds: any={p['seeds_with_any_exertion_label']} from_onset={p['seeds_with_exertion_label_from_onset']} "
              f"pre_onset={p['seeds_with_exertion_label_before_onset']}")
    print("overall label accuracy:", summary["overall_label_accuracy"])
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
