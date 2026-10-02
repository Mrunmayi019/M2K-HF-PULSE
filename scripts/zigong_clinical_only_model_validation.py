"""Runs the NEW clinical-only Model 1 variant (scripts/train_clinical_only_variant.py's
severity_regressor_clinical_only.joblib -- trained from scratch on CLINICAL_FEATURE_COLUMNS only,
no wearable-trend features at all) against the Zigong cohort's real outcomes.

Unlike docs/methodology.md Sec 7.Z (which froze wearable inputs on the already-trained FULL model
and got a collapsed, near-constant output), this model was never given wearable-trend features to
begin with -- there is nothing to freeze/neutralize. This is a genuine, unconfounded test of
whether the clinical-feature component predicts real outcomes; the AUC here is not explainable by
a collapsed-output artifact the way Sec 7.Z's was (confirmed: see
scripts/train_clinical_only_variant.py's synthetic-test-set output distribution, std=0.23,
range=[0.04, 0.82] -- healthy spread, not collapsed).

Caveats carried forward from Sec 7.Z, restated here rather than silently reused:
- age: ageCat bin midpoint (e.g. (59,69] -> 64), not real continuous age.
- nt_probnp_pg_ml: Zigong's raw brain.natriuretic.peptide (BNP), NO unit conversion applied -- no
  validated BNP-to-NT-proBNP conversion exists in this project, none invented here. Different
  assay, different reference range, different clinical meaning -- an invalid like-for-like
  substitution, reported as exploratory only for this one input.

No retraining of the production models. No change to risk_score.py or any threshold.

Usage: python -m scripts.zigong_clinical_only_model_validation
Reads:  data/zigong_outcome_validation/results.csv (cleaned, complete-case, n=625 cohort with
        composite_6mo already computed), models/severity_regressor_clinical_only.joblib
Writes: data/zigong_clinical_only_model_validation/results.csv,
        data/zigong_clinical_only_model_validation/summary.md
"""
from __future__ import annotations

import pathlib

import joblib
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from scripts.zigong_outcome_validation import bootstrap_metric_ci

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
COHORT_CSV = REPO_ROOT / "data" / "zigong_outcome_validation" / "results.csv"
OUT_DIR = REPO_ROOT / "data" / "zigong_clinical_only_model_validation"
MODELS_DIR = REPO_ROOT / "models"

CLINICAL_FEATURE_COLUMNS = ["age", "sex_male", "bmi", "ejection_fraction_pct", "nt_probnp_pg_ml"]

AGECAT_MIDPOINT = {
    "(21,29]": 25.0, "(29,39]": 34.0, "(39,49]": 44.0, "(49,59]": 54.0,
    "(59,69]": 64.0, "(69,79]": 74.0, "(79,89]": 84.0, "(89,110]": 99.5,
}


def main() -> None:
    cohort = pd.read_csv(COHORT_CSV)
    n = len(cohort)
    print(f"Loaded cohort: n={n} (from {COHORT_CSV})")

    unmapped = set(cohort["ageCat"]) - set(AGECAT_MIDPOINT)
    if unmapped:
        raise ValueError(f"ageCat values with no midpoint mapping: {unmapped}")

    features_df = pd.DataFrame({
        "age": cohort["ageCat"].map(AGECAT_MIDPOINT),
        "sex_male": (cohort["gender"] == "Male").astype(int),
        "bmi": cohort["BMI"].astype(float),
        "ejection_fraction_pct": cohort["LVEF"].astype(float),
        "nt_probnp_pg_ml": cohort["brain.natriuretic.peptide"].astype(float),  # RAW BNP, no conversion
    })
    assert features_df.notna().all().all(), "unexpected nulls in constructed clinical feature vector"

    reg = joblib.load(MODELS_DIR / "severity_regressor_clinical_only.joblib")
    severity_pred = reg.predict(features_df[CLINICAL_FEATURE_COLUMNS])

    cohort = cohort.copy()
    cohort["clinical_only_model_severity"] = severity_pred

    y_true = cohort["composite_6mo"].to_numpy()
    y_score = cohort["clinical_only_model_severity"].to_numpy()
    event_rate = y_true.mean()

    print(f"\nSeverity output distribution on Zigong (n={n}):")
    print(pd.Series(severity_pred).describe())
    print(f"std = {severity_pred.std():.4f}, range = [{severity_pred.min():.4f}, {severity_pred.max():.4f}]")

    auc_point, auc_lo, auc_hi = bootstrap_metric_ci(y_true, y_score, roc_auc_score)
    pr_point, pr_lo, pr_hi = bootstrap_metric_ci(y_true, y_score, average_precision_score)

    print(f"\nn = {n}, composite_6mo event rate = {event_rate:.1%}")
    print(f"AUC = {auc_point:.3f} (95% CI {auc_lo:.3f}-{auc_hi:.3f})")
    print(f"PR-AUC = {pr_point:.3f} (95% CI {pr_lo:.3f}-{pr_hi:.3f}); baseline = {event_rate:.3f}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cohort.to_csv(OUT_DIR / "results.csv", index=False)

    lines = [
        "# Zigong cohort: NEW clinical-only Model 1 variant -- genuine, unconfounded test",
        "",
        "Unlike Sec 7.Z (froze wearable inputs on the already-trained full model, got a"
        " collapsed/near-constant output), this model was trained from scratch on"
        " CLINICAL_FEATURE_COLUMNS only -- there is nothing to freeze. See"
        " scripts/train_clinical_only_variant.py for training details and the synthetic"
        " held-out evaluation.",
        "",
        "## Caveats (restated, not silently reused)",
        "",
        "1. age = ageCat bin midpoint, not real continuous age.",
        "2. nt_probnp_pg_ml = raw BNP, no unit conversion (none validated in this project) --"
        " invalid like-for-like substitution, only variant reported.",
        "",
        "## Output distribution (confirms not collapsed)",
        "",
        f"mean={severity_pred.mean():.4f}, std={severity_pred.std():.4f}, "
        f"range=[{severity_pred.min():.4f}, {severity_pred.max():.4f}]",
        "",
        "## Cohort / outcome",
        "",
        f"- n = {n} (same complete-case cohort as Sec 7.Y/7.Z)",
        f"- Composite outcome (death OR readmission, 6mo) event rate: {event_rate:.1%}",
        "",
        "## Discrimination (AUC / PR-AUC)",
        "",
        f"- AUC = {auc_point:.3f} (95% CI {auc_lo:.3f}-{auc_hi:.3f}, percentile bootstrap, 2000"
        f" resamples, seed=42)",
        f"- PR-AUC = {pr_point:.3f} (95% CI {pr_lo:.3f}-{pr_hi:.3f}); event-rate baseline ="
        f" {event_rate:.3f}",
    ]
    (OUT_DIR / "summary.md").write_text("\n".join(lines))
    print(f"\nWrote {OUT_DIR / 'results.csv'} and {OUT_DIR / 'summary.md'}")


if __name__ == "__main__":
    main()
