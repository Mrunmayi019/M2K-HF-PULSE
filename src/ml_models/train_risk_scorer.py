"""Phase 5, secondary/experimental risk scorer: XGBoost regressor.

Per the locked decision in CLAUDE.md ("Risk scorer"), this is explicitly NOT the primary model --
src/analytics/risk_score.py's hand-tuned weighted score is primary. This exists as a
secondary/experimental comparison only, trained on the 117-row Phase 4 batch simulation dataset,
which is too small for a reliable black-box model (see models/model_card.md for the full
reasoning and the class-imbalance caveat).

No held-out train/test split: 117 rows split three ways would leave ~17-23 test rows, too few for
a meaningful point estimate. Uses stratified (by scenario_type) k-fold cross-validation instead
and reports mean/std MAE and R^2 across folds.
"""
from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import mean_absolute_error, r2_score
from xgboost import XGBRegressor

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FEATURES_DATASET_CSV = REPO_ROOT / "data" / "simulation_runs" / "features_dataset.csv"
MODELS_DIR = REPO_ROOT / "models"

FEATURE_COLUMNS = ["hr_rise", "map_drop", "co_drop_pct", "compensation_flag", "instability_flag"]
TARGET_COLUMN = "severity"

N_FOLDS = 5


def cross_validate(df: pd.DataFrame, n_folds: int = N_FOLDS, seed: int = 42) -> dict:
    """Stratified k-fold CV (by scenario_type). Returns per-fold and aggregate MAE/R^2."""
    x = df[FEATURE_COLUMNS]
    y = df[TARGET_COLUMN]
    strata = df["scenario_type"]

    skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=seed)
    fold_mae, fold_r2 = [], []

    for train_idx, val_idx in skf.split(x, strata):
        model = XGBRegressor(n_estimators=100, max_depth=3, random_state=seed)
        model.fit(x.iloc[train_idx], y.iloc[train_idx])
        pred = model.predict(x.iloc[val_idx])
        fold_mae.append(mean_absolute_error(y.iloc[val_idx], pred))
        fold_r2.append(r2_score(y.iloc[val_idx], pred))

    return {
        "n_folds": n_folds,
        "fold_mae": fold_mae,
        "fold_r2": fold_r2,
        "mean_mae": float(np.mean(fold_mae)),
        "std_mae": float(np.std(fold_mae)),
        "mean_r2": float(np.mean(fold_r2)),
        "std_r2": float(np.std(fold_r2)),
    }


def train_final_model(df: pd.DataFrame, seed: int = 42) -> XGBRegressor:
    """Fits on the full 117-row dataset (no holdout) -- the CV above is the generalization
    estimate; this is the artifact saved for anyone who wants to actually call .predict()."""
    model = XGBRegressor(n_estimators=100, max_depth=3, random_state=seed)
    model.fit(df[FEATURE_COLUMNS], df[TARGET_COLUMN])
    return model


if __name__ == "__main__":
    import joblib

    df = pd.read_csv(FEATURES_DATASET_CSV)
    cv_results = cross_validate(df)
    model = train_final_model(df)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODELS_DIR / "risk_scorer_xgb.joblib")

    scenario_counts = df["scenario_type"].value_counts().to_dict()
    report_lines = [
        "Phase 5 -- secondary/experimental XGBoost risk scorer, cross-validation report",
        "=" * 75,
        "SECONDARY/EXPERIMENTAL ONLY -- see models/model_card.md for why this is not the",
        "primary risk scorer (src/analytics/risk_score.py is primary, per CLAUDE.md).",
        "",
        f"Dataset: {FEATURES_DATASET_CSV.relative_to(REPO_ROOT)}, n={len(df)}",
        "Scenario counts: " + ", ".join(f"{k}={v}" for k, v in scenario_counts.items()),
        "",
        f"{N_FOLDS}-fold stratified (by scenario_type) cross-validation, no held-out test split",
        f"(n=117 is too small to spare a reliable holdout -- see model_card.md):",
        f"  MAE: {cv_results['mean_mae']:.4f} +/- {cv_results['std_mae']:.4f}",
        f"  R^2: {cv_results['mean_r2']:.4f} +/- {cv_results['std_r2']:.4f}",
        f"  per-fold MAE: {[round(v, 4) for v in cv_results['fold_mae']]}",
        f"  per-fold R^2: {[round(v, 4) for v in cv_results['fold_r2']]}",
    ]
    (MODELS_DIR / "phase5_xgb_cv_report.txt").write_text("\n".join(report_lines))

    print("\n".join(report_lines))
    print(f"\nWrote {MODELS_DIR / 'risk_scorer_xgb.joblib'}")
    print(f"Wrote {MODELS_DIR / 'phase5_xgb_cv_report.txt'}")
