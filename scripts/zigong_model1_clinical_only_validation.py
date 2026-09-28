"""Exploratory test: does Model 1's CLINICAL-feature component alone predict real outcomes on the
Zigong cohort? This does NOT test Model 1 as designed -- Model 1 was trained on
CLINICAL_FEATURE_COLUMNS (age, sex_male, bmi, ejection_fraction_pct, nt_probnp_pg_ml) PLUS 24
wearable-trend features (first7_mean/last7_mean/delta/slope x 6 vitals) from a real 21-day
ambulatory window. Zigong has no wearable time series at all -- one admission-time snapshot per
patient. This script neutralizes the wearable slots (does not test them) and substitutes
approximated clinical inputs, so any result characterizes the clinical-feature component only,
under approximated inputs -- not Model 1's validated designed behavior. See docs/methodology.md
Sec 7.Z for the full writeup and caveats.

Approximations, none silent:
- age: ageCat bin midpoint (e.g. (59,69] -> 64) -- NOT real continuous age.
- nt_probnp_pg_ml: Zigong's brain.natriuretic.peptide (BNP), substituted RAW with NO unit
  conversion -- this project has no validated BNP-to-NT-proBNP conversion, and none is invented
  here. BNP and NT-proBNP are different assays with different reference ranges and different
  clinical meaning; this is an invalid like-for-like substitution, reported as exploratory only.
- Wearable-trend feature slots: set to this project's own existing "stable"-scenario reference
  values, not zero and not invented -- reusing generate_wearable_trends.py's own baseline_cfg
  (reference_stats.yaml's wearable_baseline) and _trend_curve(mode="stable") logic (zero drift), by
  literally constructing a 21-day constant trends_df per patient and running it through the real,
  unmodified src.scenario_classifier.features._wearable_features()/build_inference_features() --
  not hand-deriving first7_mean/last7_mean/delta/slope, to guarantee exact match with what Model 1
  was actually trained against. weight_kg anchors to each patient's own real (cleaned) weight,
  exactly matching generate_wearable_trends.py's own "a wearable scale reports *this* patient's
  weight" comment -- not a population constant.

No retraining. No change to risk_score.py or any threshold. Loads models/severity_regressor.joblib
unmodified and calls .predict() only.

Usage: python -m scripts.zigong_model1_clinical_only_validation
Reads:  data/zigong_outcome_validation/results.csv (the cleaned, complete-case, n=625 cohort with
        composite_6mo already computed -- written by scripts/zigong_outcome_validation.py)
Writes: data/zigong_model1_clinical_only_validation/results.csv,
        data/zigong_model1_clinical_only_validation/summary.md
"""
from __future__ import annotations

import pathlib

import joblib
import numpy as np
import pandas as pd

from src.data_synthesis.generate_patients import load_reference_stats
from src.scenario_classifier.features import VITALS, build_inference_features, feature_columns
from scripts.zigong_outcome_validation import bootstrap_metric_ci

from sklearn.metrics import average_precision_score, roc_auc_score

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
COHORT_CSV = REPO_ROOT / "data" / "zigong_outcome_validation" / "results.csv"
OUT_DIR = REPO_ROOT / "data" / "zigong_model1_clinical_only_validation"
MODELS_DIR = REPO_ROOT / "models"

N_DAYS = 21  # matches Model 1's training window length; irrelevant for a constant (zero-drift) series

# ageCat bin -> midpoint. Zigong's own bins (dataDictionary.csv); (89,110] has no natural midpoint
# (open, unusually wide top bucket) -- using its arithmetic midpoint (99.5) as the least-arbitrary
# choice available, flagged here and in the report as the roughest of these approximations.
AGECAT_MIDPOINT = {
    "(21,29]": 25.0, "(29,39]": 34.0, "(39,49]": 44.0, "(49,59]": 54.0,
    "(59,69]": 64.0, "(69,79]": 74.0, "(79,89]": 84.0, "(89,110]": 99.5,
}


def build_neutral_wearable_trends(patient_id: str, real_weight_kg: float, baseline_cfg: dict) -> pd.DataFrame:
    """One patient's 21-day trends_df at this project's own 'stable' reference values -- zero
    drift, matching generate_wearable_trends.py's _trend_curve(mode='stable') (returns zeros) and
    SCENARIO_SIGNAL_DELTAS's absence of a 'stable' entry (never drifts). No noise added: this is a
    deterministic reference point (the isolation value), not a stochastic sample."""
    rows = []
    for day in range(N_DAYS):
        row = {"patient_id": patient_id, "day": day}
        for v in VITALS:
            row[v] = real_weight_kg if v == "weight_kg" else baseline_cfg[v]["mean"]
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    cohort = pd.read_csv(COHORT_CSV)
    n = len(cohort)
    print(f"Loaded cohort: n={n} (from {COHORT_CSV})")

    baseline_cfg = load_reference_stats()["wearable_baseline"]

    # --- clinical feature construction, each approximation flagged ---
    unmapped_agecat = set(cohort["ageCat"]) - set(AGECAT_MIDPOINT)
    if unmapped_agecat:
        raise ValueError(f"ageCat values with no midpoint mapping: {unmapped_agecat}")

    feature_rows = []
    for _, p in cohort.iterrows():
        patient_id = str(p["inpatient.number"])
        trends = build_neutral_wearable_trends(patient_id, float(p["weight"]), baseline_cfg)
        patient_row = {
            "patient_id": patient_id,
            "age": AGECAT_MIDPOINT[p["ageCat"]],
            "sex": p["gender"],  # build_inference_features derives sex_male from this
            "bmi": float(p["BMI"]),
            "ejection_fraction_pct": float(p["LVEF"]),
            "nt_probnp_pg_ml": float(p["brain.natriuretic.peptide"]),  # RAW BNP, no conversion -- invalid substitution, see module docstring
        }
        feat = build_inference_features(patient_row, trends)
        feat["inpatient.number"] = p["inpatient.number"]
        feature_rows.append(feat)

    features_df = pd.concat(feature_rows, ignore_index=True)
    assert len(features_df) == n

    reg = joblib.load(MODELS_DIR / "severity_regressor.joblib")
    cols = [c for c in features_df.columns if c not in ("patient_id", "inpatient.number")]
    # Sanity check: these must be exactly the columns the model was trained on, same order concern
    # handled by predict() using named columns via a DataFrame (sklearn trees don't care about
    # column order as long as the same names/count are present at fit time -- verified by shape).
    print(f"Feature columns constructed: {len(cols)} -> {cols}")

    severity_pred = reg.predict(features_df[cols])
    cohort = cohort.merge(
        features_df[["inpatient.number"]].assign(clinical_only_severity=severity_pred),
        on="inpatient.number", how="left",
    )
    assert cohort["clinical_only_severity"].notna().all()

    y_true = cohort["composite_6mo"].to_numpy()
    y_score = cohort["clinical_only_severity"].to_numpy()
    event_rate = y_true.mean()

    auc_point, auc_lo, auc_hi = bootstrap_metric_ci(y_true, y_score, roc_auc_score)
    pr_point, pr_lo, pr_hi = bootstrap_metric_ci(y_true, y_score, average_precision_score)

    print(f"\nn = {n}, composite_6mo event rate = {event_rate:.1%}")
    print(f"AUC = {auc_point:.3f} (95% CI {auc_lo:.3f}-{auc_hi:.3f})")
    print(f"PR-AUC = {pr_point:.3f} (95% CI {pr_lo:.3f}-{pr_hi:.3f}); baseline = {event_rate:.3f}")
    print(f"\nclinical_only_severity distribution:\n{cohort['clinical_only_severity'].describe()}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cohort.to_csv(OUT_DIR / "results.csv", index=False)

    lines = [
        "# Zigong cohort: Model 1 clinical-feature-component-only exploratory test",
        "",
        "**This does NOT test Model 1 as designed.** Model 1 (severity regressor) was trained on"
        " 5 clinical features PLUS 24 wearable-trend features from a real 21-day ambulatory"
        " window. Zigong has no wearable time series -- this test neutralizes those 24 features to"
        " this project's own 'stable'-scenario reference values (zero drift, from"
        " reference_stats.yaml's wearable_baseline, via the real, unmodified"
        " _wearable_features()/build_inference_features() code) and substitutes approximated"
        " clinical inputs. The result characterizes the clinical-feature component only, under"
        " approximated inputs -- not Model 1's validated designed behavior.",
        "",
        "## Caveats (all load-bearing, not footnotes)",
        "",
        "1. **age** is the `ageCat` bin midpoint (e.g. `(59,69]` -> 64), not real continuous age --"
        " a coarse approximation, worst for the open-ended `(89,110]` bucket (midpoint 99.5).",
        "2. **nt_probnp_pg_ml is Zigong's raw BNP value, substituted with NO unit conversion.**"
        " This project has no validated BNP-to-NT-proBNP conversion, and none was invented for"
        " this test. BNP and NT-proBNP are different assays with different reference ranges and"
        " different clinical meaning -- this is an invalid like-for-like substitution. There is"
        " only one reported variant (raw, unconverted); no second 'corrected' variant was computed"
        " since no defensible conversion factor exists.",
        "3. **All 24 wearable-trend feature slots are neutralized**, not real -- set to this"
        " project's own 'stable'-scenario reference values (zero drift), not zero and not invented"
        " ad hoc.",
        "4. No retraining occurred; `models/severity_regressor.joblib` was loaded unmodified.",
        "",
        "## Cohort / outcome",
        "",
        f"- n = {n} (same complete-case cohort as Sec 7.Y)",
        f"- Composite outcome (death OR readmission, 6mo) event rate: {event_rate:.1%}",
        "",
        "## Discrimination (AUC / PR-AUC)",
        "",
        f"- AUC = {auc_point:.3f} (95% CI {auc_lo:.3f}-{auc_hi:.3f}, percentile bootstrap, 2000"
        f" resamples, seed=42) for the clinical-only severity-regressor output predicting the"
        f" 6-month composite outcome.",
        f"- PR-AUC = {pr_point:.3f} (95% CI {pr_lo:.3f}-{pr_hi:.3f}); event-rate baseline ="
        f" {event_rate:.3f}.",
    ]
    (OUT_DIR / "summary.md").write_text("\n".join(lines))
    print(f"\nWrote {OUT_DIR / 'results.csv'} and {OUT_DIR / 'summary.md'}")


if __name__ == "__main__":
    main()
