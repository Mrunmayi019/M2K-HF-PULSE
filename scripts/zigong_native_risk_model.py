"""EXPLORATORY, STANDALONE analysis -- NOT part of HeartGuard AI's production pipeline.

Does not feed into, replace, or get called by src/analytics/risk_score.py, the scenario
classifier/severity regressor (Model 1), or the Pulse simulation layer. Purpose: check whether
Zigong's richer, well-populated fields (not just the 5 sparse clinical-snapshot ones already
tested in docs/methodology.md Sec 7.Z/7.AA) can reach discrimination closer to literature-reported
readmission/mortality risk-model baselines (LACE index ~0.56-0.65; richer ML models ~0.72-0.76) on
the same 6-month death-or-readmission composite outcome. See docs/methodology.md Sec 7.BB for the
full writeup, comparison table, and caveats.

Base population: the full CLEANED cohort (n=2001, same 5 cleaning rules as
scripts/zigong_outcome_validation.py), NOT the complete-case n=625 -- deliberately avoids
restricting to patients who happened to get an echo.

Feature selection discipline: pull only fields with <15% missingness in this cohort, checked
individually and printed before any modeling; drop the rest rather than imputing heavily. LVEF
(68.38% missing in this cohort) is excluded outright for this reason. brain.natriuretic.peptide
(BNP) is NOT excluded -- checked, not assumed: it is only 1.74% missing here, comfortably under
the 15% bar, so it is included as a real feature (correcting an initial assumption that it would
likely be dropped like LVEF).

Split: single stratified 80/20 train/test split on composite_6mo, random_state=42, BEFORE any
model selection. A small hyperparameter grid is tuned via 5-fold cross-validation on the training
portion ONLY; the held-out test set is touched exactly once, at the end, for the reported number.

Usage: python -m scripts.zigong_native_risk_model
Reads:  the dataset directory (DATA_DIR below), outside the repo (DUA-signed restricted data).
Writes: data/zigong_native_risk_model/{train_features.csv, test_features.csv, summary.md}
"""
from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GridSearchCV, StratifiedKFold, train_test_split

from scripts.zigong_outcome_validation import bootstrap_metric_ci

DATA_DIR = pathlib.Path(
    r"D:\5th sem notes\capstone\Dataset\hospitalized-patients-with-heart-failure-integrating-"
    r"electronic-healthcare-records-and-external-outcome-data-1.3"
)
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "zigong_native_risk_model"

MISSINGNESS_THRESHOLD_PCT = 15.0
BMI_CEILING = 60.0
HEIGHT_FLOOR_M = 1.0

CANDIDATE_FIELDS = {
    "vitals": [
        "pulse", "respiration", "systolic.blood.pressure", "diastolic.blood.pressure",
        "map", "weight", "height", "BMI",
    ],
    "hf_classification": ["NYHA.cardiac.function.classification", "Killip.grade", "type.of.heart.failure"],
    "charlson": [
        "myocardial.infarction", "congestive.heart.failure", "peripheral.vascular.disease",
        "cerebrovascular.disease", "dementia", "Chronic.obstructive.pulmonary.disease",
        "connective.tissue.disease", "peptic.ulcer.disease", "diabetes",
        "moderate.to.severe.chronic.kidney.disease", "hemiplegia", "leukemia",
        "malignant.lymphoma", "solid.tumor", "liver.disease", "AIDS", "CCI.score",
        "type.II.respiratory.failure",
    ],
    "cbc": [
        "white.blood.cell", "monocyte.ratio", "monocyte.count", "red.blood.cell",
        "coefficient.of.variation.of.red.blood.cell.distribution.width",
        "standard.deviation.of.red.blood.cell.distribution.width", "mean.corpuscular.volume",
        "hematocrit", "lymphocyte.count", "mean.hemoglobin.volume", "mean.hemoglobin.concentration",
        "mean.platelet.volume", "basophil.ratio", "basophil.count", "eosinophil.ratio",
        "eosinophil.count", "hemoglobin", "platelet", "platelet.distribution.width",
        "platelet.hematocrit", "neutrophil.ratio", "neutrophil.count",
    ],
    "coagulation": [
        "D.dimer", "international.normalized.ratio", "activated.partial.thromboplastin.time",
        "thrombin.time", "prothrombin.activity", "prothrombin.time.ratio", "fibrinogen",
    ],
    "renal_chem": ["creatinine.enzymatic.method", "urea", "uric.acid", "glomerular.filtration.rate", "cystatin"],
    "other": ["admission.way", "visit.times"],
    "biomarker_candidate": ["brain.natriuretic.peptide", "LVEF"],  # checked, not assumed -- see docstring
}


def clean(dat: pd.DataFrame) -> pd.DataFrame:
    drop_mask = (
        (dat["pulse"] == 0) | (dat["respiration"] == 0) | (dat["systolic.blood.pressure"] == 0)
        | (dat["height"] < HEIGHT_FLOOR_M) | (dat["BMI"] > BMI_CEILING)
    )
    return dat[~drop_mask].copy()


def main() -> None:
    dat = pd.read_csv(DATA_DIR / "dat.csv")
    n_raw = len(dat)
    dat_clean = clean(dat)
    n_clean = len(dat_clean)
    print(f"n raw = {n_raw}, n cleaned = {n_clean}")

    dat_clean["composite_6mo"] = (
        (dat_clean["death.within.6.months"] == 1) | (dat_clean["re.admission.within.6.months"] == 1)
    ).astype(int)

    # --- Step 2: missingness check per candidate field, individually, threshold applied ---
    all_candidates = [f for group in CANDIDATE_FIELDS.values() for f in group]
    miss = (dat_clean[all_candidates].isna().mean() * 100).round(2).sort_values(ascending=False)
    nunique = dat_clean[all_candidates].nunique()
    print(f"\n=== Missingness per candidate field (n={n_clean}), threshold <{MISSINGNESS_THRESHOLD_PCT}% ===")
    for f in miss.index:
        flag = "DROP (missingness)" if miss[f] >= MISSINGNESS_THRESHOLD_PCT else (
            "DROP (zero variance)" if nunique[f] <= 1 else "keep"
        )
        print(f"{f:65s} missing={miss[f]:6.2f}%  n_unique={nunique[f]:4d}  -> {flag}")

    kept_fields = [
        f for f in all_candidates
        if miss[f] < MISSINGNESS_THRESHOLD_PCT and nunique[f] > 1
    ]
    dropped_fields = [f for f in all_candidates if f not in kept_fields]
    print(f"\nKept {len(kept_fields)} fields, dropped {len(dropped_fields)}: {dropped_fields}")

    # --- Feature construction ---
    df = dat_clean[["inpatient.number", "composite_6mo"] + kept_fields].copy()

    # Categorical encodings
    if "NYHA.cardiac.function.classification" in df.columns:
        df["NYHA.cardiac.function.classification"] = df["NYHA.cardiac.function.classification"].map(
            {"I": 1, "II": 2, "III": 3, "IV": 4}
        )
    if "Killip.grade" in df.columns:
        df["Killip.grade"] = df["Killip.grade"].map({"I": 1, "II": 2, "III": 3, "IV": 4})
    if "admission.way" in df.columns:
        df["admission.way"] = (df["admission.way"] == "Emergency").astype(int)
    if "type.II.respiratory.failure" in df.columns:
        df["type.II.respiratory.failure"] = (df["type.II.respiratory.failure"] == "TypeII").astype(int)
    if "type.of.heart.failure" in df.columns:
        df = pd.get_dummies(df, columns=["type.of.heart.failure"], prefix="hf_type", drop_first=True)

    feature_cols = [c for c in df.columns if c not in ("inpatient.number", "composite_6mo")]

    # Light imputation (median) for the sparse remaining per-row gaps in these already
    # low-missingness fields -- NOT the heavy imputation ruled out for high-missingness fields.
    rows_with_any_missing = df[feature_cols].isna().any(axis=1).sum()
    print(f"\nRows with >=1 missing value among the {len(feature_cols)} kept/encoded features: "
          f"{rows_with_any_missing} / {len(df)} ({rows_with_any_missing/len(df)*100:.1f}%) -- median-imputed")
    for c in feature_cols:
        if df[c].isna().any():
            df[c] = df[c].fillna(df[c].median())

    print(f"\nFinal feature matrix: {len(feature_cols)} columns, n={len(df)}")
    print(f"Composite outcome event rate: {df['composite_6mo'].mean():.1%}")

    # --- Step 3: stratified 80/20 split, BEFORE any model selection ---
    train_df, test_df = train_test_split(
        df, test_size=0.20, stratify=df["composite_6mo"], random_state=42
    )
    print(f"\nSplit: stratified 80/20 on composite_6mo, random_state=42")
    print(f"train n={len(train_df)} (event rate {train_df['composite_6mo'].mean():.1%}), "
          f"test n={len(test_df)} (event rate {test_df['composite_6mo'].mean():.1%})")

    X_train, y_train = train_df[feature_cols], train_df["composite_6mo"]
    X_test, y_test = test_df[feature_cols], test_df["composite_6mo"]

    # --- Step 4: small hyperparameter grid, tuned via 5-fold CV on TRAIN ONLY ---
    param_grid = {"n_estimators": [300], "max_depth": [4, 8, None], "min_samples_leaf": [1, 5, 20]}
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    search = GridSearchCV(
        RandomForestClassifier(random_state=42, n_jobs=-1), param_grid, scoring="roc_auc", cv=cv,
    )
    search.fit(X_train, y_train)
    print(f"\nBest params (5-fold CV AUC on train only): {search.best_params_} "
          f"(CV AUC = {search.best_score_:.3f})")

    model = search.best_estimator_

    # --- Step 5: report train and test performance SEPARATELY ---
    train_score = model.predict_proba(X_train)[:, 1]
    test_score = model.predict_proba(X_test)[:, 1]

    train_auc = roc_auc_score(y_train, train_score)
    train_pr_auc = average_precision_score(y_train, train_score)
    print(f"\n-- Train-set performance (in-sample, expected optimistic) --")
    print(f"AUC = {train_auc:.3f}, PR-AUC = {train_pr_auc:.3f}")

    test_auc, test_auc_lo, test_auc_hi = bootstrap_metric_ci(y_test.to_numpy(), test_score, roc_auc_score)
    test_pr, test_pr_lo, test_pr_hi = bootstrap_metric_ci(y_test.to_numpy(), test_score, average_precision_score)
    print(f"\n-- HELD-OUT TEST SET performance (touched once, this is the number that counts) --")
    print(f"AUC = {test_auc:.3f} (95% CI {test_auc_lo:.3f}-{test_auc_hi:.3f})")
    print(f"PR-AUC = {test_pr:.3f} (95% CI {test_pr_lo:.3f}-{test_pr_hi:.3f}); "
          f"baseline = {y_test.mean():.3f}")
    print(f"Train/test AUC gap: {train_auc - test_auc:.3f}")

    # --- Step 6: feature importances ---
    importances = pd.Series(model.feature_importances_, index=feature_cols).sort_values(ascending=False)
    print(f"\n=== Top 15 feature importances ===")
    print(importances.head(15).to_string())

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    train_df.to_csv(OUT_DIR / "train_features.csv", index=False)
    test_df.to_csv(OUT_DIR / "test_features.csv", index=False)

    lines = [
        "# Zigong-native risk model -- EXPLORATORY, standalone (not part of HeartGuard AI's pipeline)",
        "",
        f"n raw={n_raw}, n cleaned={n_clean}. Composite outcome (death OR readmission, 6mo) event"
        f" rate: {df['composite_6mo'].mean():.1%}.",
        "",
        "## Feature selection",
        "",
        f"Kept {len(kept_fields)}/{len(all_candidates)} candidate fields (<{MISSINGNESS_THRESHOLD_PCT}%"
        f" missing, non-constant). Dropped: {dropped_fields}.",
        "LVEF excluded (68.38% missing, above threshold). brain.natriuretic.peptide (BNP) INCLUDED"
        " -- checked at 1.74% missing, well under the bar, correcting an initial assumption it"
        " would be dropped like LVEF.",
        f"{rows_with_any_missing}/{len(df)} rows needed median imputation on at least one already"
        f" low-missingness field (light imputation only, not applied to any excluded"
        f" high-missingness field).",
        "",
        "## Split & model selection",
        "",
        "Stratified 80/20 train/test split on composite_6mo, random_state=42, BEFORE any model"
        " selection. 5-fold CV on the training portion only for hyperparameter selection"
        f" (RandomForestClassifier; grid: {param_grid}). Best: {search.best_params_}"
        f" (CV AUC={search.best_score_:.3f}). Test set touched exactly once, after selection.",
        "",
        "## Results",
        "",
        f"- Train (in-sample): AUC={train_auc:.3f}, PR-AUC={train_pr_auc:.3f}",
        f"- **Held-out test (n={len(test_df)}): AUC={test_auc:.3f} (95% CI {test_auc_lo:.3f}-"
        f"{test_auc_hi:.3f}), PR-AUC={test_pr:.3f} (95% CI {test_pr_lo:.3f}-{test_pr_hi:.3f}),"
        f" baseline={y_test.mean():.3f}**",
        f"- Train/test AUC gap: {train_auc - test_auc:.3f}",
        "",
        "## Top 15 feature importances",
        "",
        "```",
        importances.head(15).to_string(),
        "```",
    ]
    (OUT_DIR / "summary.md").write_text("\n".join(lines))
    print(f"\nWrote outputs to {OUT_DIR}")


if __name__ == "__main__":
    main()
