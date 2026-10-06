"""results-v1 offline analysis (1/4): ML metrics on the 70/15/15 test split -- evaluates the
FROZEN models/*.joblib (verified by SHA-256 against artifacts/results-v1/models/ before this
runs) against the exact same test split src/scenario_classifier/train.py's own split_patients()
produces, using that module's own build_features()/evaluate() -- not reimplemented. Does NOT
retrain and does NOT overwrite models/*.joblib (train.py's run() is not called with models_dir
set to the real models/ directory, since that would retrain-and-clobber the frozen artifacts).

Usage:
    PYTHONPATH=. python3 -m src.evaluation.results_v1_offline.ml_metrics
"""
from __future__ import annotations

import hashlib
import json
import pathlib

import joblib
import pandas as pd

from src.data_synthesis.generate_patients import DEFAULT_OUTPUT_PATH as PATIENTS_CSV
from src.data_synthesis.generate_wearable_trends import DEFAULT_OUTPUT_PATH as TRENDS_CSV
from src.scenario_classifier.features import build_features, feature_columns
from src.scenario_classifier.train import evaluate, split_patients

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MODELS_DIR = REPO_ROOT / "models"
FROZEN_DIR = REPO_ROOT / "artifacts" / "results-v1" / "models"
OUT_DIR = REPO_ROOT / "results" / "results_v1_offline"

EXPECTED_HASHES = {
    "scenario_classifier.joblib": "2157cb21991390e6b2417ff8793c2b62a32eeef7467963b94d5058cc37d05a49",
    "severity_regressor.joblib": "4b7afeab6210464b2e3730bf54248362db0ecc83ed58626a488fd3d47cb79f0e",
}


def verify_hashes():
    for name, expected in EXPECTED_HASHES.items():
        for d in (MODELS_DIR, FROZEN_DIR):
            path = d / name
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                raise SystemExit(f"Hash mismatch for {path}: expected {expected}, got {actual}")
    print("Model hashes verified: models/, artifacts/results-v1/models/, and the recorded "
          "RESULTS.md hashes all agree.")


def main():
    verify_hashes()

    patients_df = pd.read_csv(PATIENTS_CSV)
    trends_df = pd.read_csv(TRENDS_CSV)
    features_df = build_features(patients_df, trends_df)
    cols = feature_columns(features_df)

    train_df, val_df, test_df = split_patients(features_df, seed=42)
    print(f"Train/val/test sizes: {len(train_df)}/{len(val_df)}/{len(test_df)} "
          f"(patient-level 70/15/15, stratified, seed=42 -- train.py's own split_patients())")

    clf = joblib.load(MODELS_DIR / "scenario_classifier.joblib")
    reg = joblib.load(MODELS_DIR / "severity_regressor.joblib")

    test_metrics = evaluate(clf, reg, test_df, cols)
    val_metrics = evaluate(clf, reg, val_df, cols)

    print("\n-- Test set (frozen results-v1 model) --")
    print(f"Scenario accuracy: {test_metrics['accuracy']:.4f}")
    print(test_metrics["classification_report"])
    print(f"Severity MAE: {test_metrics['severity_mae']:.4f}  RMSE: {test_metrics['severity_rmse']:.4f}")
    print("Severity MAE by scenario_type:")
    for k, v in test_metrics["severity_mae_by_scenario"].items():
        print(f"  {k}: {v:.4f}")
    print("\nConfusion matrix (rows=actual, cols=predicted):")
    print(test_metrics["confusion_matrix"])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = {
        "train_val_test_sizes": [len(train_df), len(val_df), len(test_df)],
        "test_accuracy": test_metrics["accuracy"],
        "test_severity_mae": test_metrics["severity_mae"],
        "test_severity_rmse": test_metrics["severity_rmse"],
        "test_severity_mae_by_scenario": test_metrics["severity_mae_by_scenario"],
        "test_confusion_matrix": test_metrics["confusion_matrix"].tolist(),
        "val_accuracy": val_metrics["accuracy"],
        "val_severity_mae": val_metrics["severity_mae"],
        "val_severity_rmse": val_metrics["severity_rmse"],
    }
    with open(OUT_DIR / "ml_metrics.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    (OUT_DIR / "ml_metrics_classification_report.txt").write_text(test_metrics["classification_report"])


if __name__ == "__main__":
    main()
