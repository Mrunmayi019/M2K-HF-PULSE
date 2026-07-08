"""Phase 3: train and evaluate ML Model 1 (scenario classifier + severity regressor).

Two RandomForest models share one feature matrix (src/scenario_classifier/features.py):
  - RandomForestClassifier predicts `scenario_type` (5-class).
  - RandomForestRegressor predicts `severity` (0-1 continuous).

Split is patient-level (one patient's 21 wearable days never straddle two folds -- they already
don't, since features.py collapses each patient to one row) and stratified by `scenario_type` so
all 5 classes are represented in the 15% test fold.

Run as a script (`python3 -m src.scenario_classifier.train`) to train on the full
data/synthetic/ dataset and write artifacts to models/. Import `run()` to train on an arbitrary
patients_df/trends_df (used by tests with a small n for speed).
"""
from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    mean_absolute_error,
    mean_squared_error,
)
from sklearn.model_selection import train_test_split

from src.data_synthesis.generate_patients import DEFAULT_OUTPUT_PATH as PATIENTS_CSV
from src.data_synthesis.generate_wearable_trends import DEFAULT_OUTPUT_PATH as TRENDS_CSV
from src.scenario_classifier.features import TARGET_COLUMNS, build_features, feature_columns

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
MODELS_DIR = REPO_ROOT / "models"

SCENARIO_TYPES = ["stable", "fluid_overload", "cardiac_stress", "deconditioning", "acute_deterioration"]


def split_patients(features_df: pd.DataFrame, seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Patient-level 70/15/15 split, stratified by scenario_type."""
    train_df, temp_df = train_test_split(
        features_df, test_size=0.30, stratify=features_df["scenario_type"], random_state=seed
    )
    val_df, test_df = train_test_split(
        temp_df, test_size=0.50, stratify=temp_df["scenario_type"], random_state=seed
    )
    return train_df, val_df, test_df


def train_models(
    train_df: pd.DataFrame, feature_cols: list[str], seed: int = 42
) -> tuple[RandomForestClassifier, RandomForestRegressor]:
    x_train = train_df[feature_cols]
    clf = RandomForestClassifier(n_estimators=300, max_depth=None, random_state=seed, n_jobs=-1)
    clf.fit(x_train, train_df["scenario_type"])

    reg = RandomForestRegressor(n_estimators=300, max_depth=None, random_state=seed, n_jobs=-1)
    reg.fit(x_train, train_df["severity"])
    return clf, reg


def evaluate(
    clf: RandomForestClassifier, reg: RandomForestRegressor, df: pd.DataFrame, feature_cols: list[str]
) -> dict:
    x = df[feature_cols]
    y_scenario = df["scenario_type"]
    y_severity = df["severity"]

    scenario_pred = clf.predict(x)
    severity_pred = reg.predict(x)

    per_scenario_mae = (
        pd.DataFrame({"scenario_type": y_scenario, "abs_err": np.abs(y_severity - severity_pred)})
        .groupby("scenario_type")["abs_err"]
        .mean()
        .to_dict()
    )

    return {
        "accuracy": accuracy_score(y_scenario, scenario_pred),
        "classification_report": classification_report(y_scenario, scenario_pred, labels=SCENARIO_TYPES),
        "confusion_matrix": confusion_matrix(y_scenario, scenario_pred, labels=SCENARIO_TYPES),
        "severity_mae": mean_absolute_error(y_severity, severity_pred),
        "severity_rmse": mean_squared_error(y_severity, severity_pred) ** 0.5,
        "severity_mae_by_scenario": per_scenario_mae,
    }


def _save_confusion_matrix_plot(cm: np.ndarray, path: pathlib.Path) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(SCENARIO_TYPES)), SCENARIO_TYPES, rotation=45, ha="right")
    ax.set_yticks(range(len(SCENARIO_TYPES)), SCENARIO_TYPES)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    ax.set_title("Scenario classifier -- test set confusion matrix")
    for i in range(len(SCENARIO_TYPES)):
        for j in range(len(SCENARIO_TYPES)):
            ax.text(j, i, str(cm[i, j]), ha="center", va="center")
    fig.colorbar(im, ax=ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _save_feature_importance_plot(clf: RandomForestClassifier, feature_cols: list[str], path: pathlib.Path) -> None:
    import matplotlib.pyplot as plt

    importances = pd.Series(clf.feature_importances_, index=feature_cols).sort_values()
    fig, ax = plt.subplots(figsize=(7, 8))
    importances.plot.barh(ax=ax)
    ax.set_title("Scenario classifier -- feature importances")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def run(patients_df: pd.DataFrame, trends_df: pd.DataFrame, seed: int = 42, models_dir: pathlib.Path | None = None) -> dict:
    """Build features, split, train, evaluate. If `models_dir` is given, persist artifacts there."""
    features_df = build_features(patients_df, trends_df)
    cols = feature_columns(features_df)

    train_df, val_df, test_df = split_patients(features_df, seed=seed)
    clf, reg = train_models(train_df, cols, seed=seed)

    val_metrics = evaluate(clf, reg, val_df, cols)
    test_metrics = evaluate(clf, reg, test_df, cols)

    result = {
        "feature_columns": cols,
        "classifier": clf,
        "regressor": reg,
        "val_metrics": val_metrics,
        "test_metrics": test_metrics,
    }

    if models_dir is not None:
        import joblib

        models_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(clf, models_dir / "scenario_classifier.joblib")
        joblib.dump(reg, models_dir / "severity_regressor.joblib")
        _save_confusion_matrix_plot(test_metrics["confusion_matrix"], models_dir / "confusion_matrix.png")
        _save_feature_importance_plot(clf, cols, models_dir / "feature_importances.png")

        report_lines = [
            "Phase 3 -- ML Model 1 (scenario classifier + severity regressor) evaluation",
            "=" * 70,
            f"Train/val/test sizes: {len(train_df)}/{len(val_df)}/{len(test_df)}",
            "",
            "-- Validation set --",
            f"Scenario accuracy: {val_metrics['accuracy']:.3f}",
            f"Severity MAE: {val_metrics['severity_mae']:.3f}  RMSE: {val_metrics['severity_rmse']:.3f}",
            "",
            "-- Test set --",
            f"Scenario accuracy: {test_metrics['accuracy']:.3f}",
            test_metrics["classification_report"],
            f"Severity MAE: {test_metrics['severity_mae']:.3f}  RMSE: {test_metrics['severity_rmse']:.3f}",
            "Severity MAE by scenario_type:",
            *[f"  {k}: {v:.3f}" for k, v in test_metrics["severity_mae_by_scenario"].items()],
            "",
            "Confusion matrix (rows=actual, cols=predicted), order = " + ", ".join(SCENARIO_TYPES),
            str(test_metrics["confusion_matrix"]),
        ]
        (models_dir / "phase3_eval_report.txt").write_text("\n".join(report_lines))

    return result


if __name__ == "__main__":
    patients_df = pd.read_csv(PATIENTS_CSV)
    trends_df = pd.read_csv(TRENDS_CSV)

    result = run(patients_df, trends_df, models_dir=MODELS_DIR)

    print(f"Train/val/test: stratified 70/15/15 split, {len(patients_df)} patients total")
    print(f"Validation accuracy: {result['val_metrics']['accuracy']:.3f}")
    print(f"Test accuracy: {result['test_metrics']['accuracy']:.3f}")
    print(result["test_metrics"]["classification_report"])
    print(f"Severity MAE: {result['test_metrics']['severity_mae']:.3f}  RMSE: {result['test_metrics']['severity_rmse']:.3f}")
    print(f"Artifacts written to {MODELS_DIR}")
