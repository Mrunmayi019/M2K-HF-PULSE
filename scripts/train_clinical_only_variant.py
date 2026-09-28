"""Trains a CLINICAL-ONLY variant of Model 1 -- same synthetic training data, split_patients()
logic, seed=42, and RandomForest hyperparameters as the production scenario_classifier.joblib /
severity_regressor.joblib, but restricted to CLINICAL_FEATURE_COLUMNS only (age, sex_male, bmi,
ejection_fraction_pct, nt_probnp_pg_ml) -- none of the 24 wearable-trend features.

Purpose: a genuine, unconfounded answer to "does the clinical-feature component alone predict
anything" -- unlike docs/methodology.md Sec 7.Z (which froze wearable-trend inputs on the
already-trained full model and got a collapsed, near-constant output), this model is trained from
scratch to make its best prediction from clinical features alone. See docs/methodology.md Sec 7.AA
for the full writeup.

Does NOT touch models/scenario_classifier.joblib or models/severity_regressor.joblib (the
production artifacts) or src/analytics/risk_score.py. Writes new, clearly-separate files:
models/scenario_classifier_clinical_only.joblib, models/severity_regressor_clinical_only.joblib.

Usage: python -m scripts.train_clinical_only_variant
"""
from __future__ import annotations

import pathlib

import joblib
import pandas as pd

from src.data_synthesis.generate_patients import DEFAULT_OUTPUT_PATH as PATIENTS_CSV
from src.data_synthesis.generate_wearable_trends import DEFAULT_OUTPUT_PATH as TRENDS_CSV
from src.scenario_classifier.features import CLINICAL_FEATURE_COLUMNS, build_features
from src.scenario_classifier.train import evaluate, split_patients, train_models

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MODELS_DIR = REPO_ROOT / "models"
SEED = 42


def main() -> None:
    patients_df = pd.read_csv(PATIENTS_CSV)
    trends_df = pd.read_csv(TRENDS_CSV)

    # Full feature set, purely to reproduce the EXACT same patient-level split the production
    # model used (split_patients stratifies on scenario_type from this same features_df) -- the
    # wearable columns it also contains are simply not used as feature_cols below.
    features_df = build_features(patients_df, trends_df)
    train_df, val_df, test_df = split_patients(features_df, seed=SEED)

    clinical_cols = list(CLINICAL_FEATURE_COLUMNS)
    print(f"Clinical-only feature columns ({len(clinical_cols)}): {clinical_cols}")

    clf, reg = train_models(train_df, clinical_cols, seed=SEED)

    val_metrics = evaluate(clf, reg, val_df, clinical_cols)
    test_metrics = evaluate(clf, reg, test_df, clinical_cols)

    print(f"\nTrain/val/test sizes: {len(train_df)}/{len(val_df)}/{len(test_df)}")
    print(f"\n-- Validation set --")
    print(f"Scenario accuracy: {val_metrics['accuracy']:.3f}")
    print(f"Severity MAE: {val_metrics['severity_mae']:.3f}  RMSE: {val_metrics['severity_rmse']:.3f}")
    print(f"\n-- Test set (SAME 300 held-out patients as the production model) --")
    print(f"Scenario accuracy: {test_metrics['accuracy']:.3f}")
    print(test_metrics["classification_report"])
    print(f"Severity MAE: {test_metrics['severity_mae']:.3f}  RMSE: {test_metrics['severity_rmse']:.3f}")
    print("Confusion matrix:")
    print(test_metrics["confusion_matrix"])

    severity_pred_test = reg.predict(test_df[clinical_cols])
    print(f"\n-- Severity regressor output distribution on the held-out test set (n={len(test_df)}) --")
    print(pd.Series(severity_pred_test).describe())
    print(f"std = {severity_pred_test.std():.4f}, range = [{severity_pred_test.min():.4f}, {severity_pred_test.max():.4f}]")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(clf, MODELS_DIR / "scenario_classifier_clinical_only.joblib")
    joblib.dump(reg, MODELS_DIR / "severity_regressor_clinical_only.joblib")
    print(f"\nWrote models/scenario_classifier_clinical_only.joblib and models/severity_regressor_clinical_only.joblib")

    report_lines = [
        "Clinical-only Model 1 variant -- evaluation (docs/methodology.md Sec 7.AA)",
        "=" * 70,
        f"Feature columns ({len(clinical_cols)}): {clinical_cols}",
        f"Train/val/test sizes: {len(train_df)}/{len(val_df)}/{len(test_df)} (SAME split as production Model 1, seed={SEED})",
        "",
        "-- Validation set --",
        f"Scenario accuracy: {val_metrics['accuracy']:.3f}",
        f"Severity MAE: {val_metrics['severity_mae']:.3f}  RMSE: {val_metrics['severity_rmse']:.3f}",
        "",
        "-- Test set --",
        f"Scenario accuracy: {test_metrics['accuracy']:.3f}",
        test_metrics["classification_report"],
        f"Severity MAE: {test_metrics['severity_mae']:.3f}  RMSE: {test_metrics['severity_rmse']:.3f}",
        "",
        "Confusion matrix (rows=actual, cols=predicted):",
        str(test_metrics["confusion_matrix"]),
        "",
        f"Severity regressor output distribution on held-out test set: "
        f"mean={severity_pred_test.mean():.4f}, std={severity_pred_test.std():.4f}, "
        f"range=[{severity_pred_test.min():.4f}, {severity_pred_test.max():.4f}]",
    ]
    (MODELS_DIR / "phase3_clinical_only_eval_report.txt").write_text("\n".join(report_lines))


if __name__ == "__main__":
    main()
