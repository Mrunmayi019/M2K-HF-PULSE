"""EXPLORATORY, STANDALONE external benchmark -- NOT part of HeartGuard AI's production pipeline.
Same treatment as docs/methodology.md Sec 7.BB: does not feed into, replace, or get called by
risk_score.py, Model 1, or the Pulse simulation layer.

Computes "MAGGIC-11" (also written "MAGGIC-adapted (missing smoker status, HF duration)") on the
Zigong cohort -- an 11-of-13-variable ADAPTATION of the published MAGGIC risk score (Pocock SJ, et
al. "Predicting survival in heart failure: a risk score based on 39 372 patients from 30 studies
worldwide." Eur Heart J. 2013;34(19):1404-1413), NOT the validated 13-variable score. Two of
MAGGIC's 13 predictors -- current smoker status, and whether HF was first diagnosed >=18 months
ago -- are entirely absent from this dataset (checked directly against dataDictionary.csv's 166
columns and dat_md.csv's medication list; no derivation path exists for either). Per the explicit
decision this script was built from: these two are NOT defaulted/assumed. MAGGIC-11's result must
NEVER be compared against MAGGIC's own published AUC range as if it were the same score --
see docs/methodology.md Sec 7.CC.

NEVER call this "MAGGIC" or "the MAGGIC score" unqualified anywhere -- always "MAGGIC-11" or
"MAGGIC-adapted (missing smoker status, HF duration)", to avoid any reader confusing it with the
real, validated, 13-variable published score.

How the 2 missing predictors are excluded (not defaulted): src/analytics/benchmark_scores.py's
compute_maggic_score() is called UNMODIFIED (reused, not reimplemented) with current_smoker=False
and hf_duration_18mo_plus=False -- the one parameter value for each that makes its own point
contribution exactly zero (1 if current_smoker else 0; 2 if hf_duration_18mo_plus else 0), the same
"pick the neutral value that structurally excludes a term" pattern already used for
risk_score.py's isolation trick in scripts/mimic_outcome_validation.py /
scripts/zigong_outcome_validation.py. This is NOT "assuming non-smoker" or "assuming recent
diagnosis" -- both keys are stripped out of the reported component breakdown below, specifically so
a 0 here is never misread as a measured true-negative.

The other 11 fields are ALL real, per-patient Zigong values (not project-standard ASSUMED_*
defaults) -- a stronger real-world test than the original scripts/benchmark_comparison.py ever ran
(which used 6 fixed constants on synthetic data): age (ageCat bin-midpoint approximation, flagged),
sex, BMI, systolic BP, LVEF, creatinine (already in umol/L, MAGGIC's native unit -- no conversion
needed here, unlike the synthetic pipeline's mg/dL-sourced default), diabetes, COPD, NYHA class
(all real per-patient fields), and beta-blocker / ACEI-ARB use (derived from dat_md.csv's
medication list -- 2007/2008 patients have >=1 drug record, so a non-match is a confident
true-negative, not missing data).

Usage: python -m scripts.zigong_maggic11_validation
Reads:  the dataset directory (DATA_DIR below, outside the repo), and
        data/zigong_outcome_validation/results.csv is NOT reused here (different cohort gating --
        MAGGIC-11 requires LVEF+creatinine+NYHA+diabetes+COPD+drug-record, not
        LVEF+NYHA+BNP+outcomes) -- built fresh from dat.csv/dat_md.csv.
Writes: data/zigong_maggic11_validation/results.csv, data/zigong_maggic11_validation/summary.md
"""
from __future__ import annotations

import pathlib

import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from scripts.zigong_outcome_validation import bootstrap_metric_ci
from src.analytics.benchmark_scores import compute_maggic_score

DATA_DIR = pathlib.Path(
    r"D:\5th sem notes\capstone\Dataset\hospitalized-patients-with-heart-failure-integrating-"
    r"electronic-healthcare-records-and-external-outcome-data-1.3"
)
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "zigong_maggic11_validation"

BMI_CEILING = 60.0
HEIGHT_FLOOR_M = 1.0

AGECAT_MIDPOINT = {
    "(21,29]": 25.0, "(29,39]": 34.0, "(39,49]": 44.0, "(49,59]": 54.0,
    "(59,69]": 64.0, "(69,79]": 74.0, "(79,89]": 84.0, "(89,110]": 99.5,
}

BETA_BLOCKER_DRUG_NAMES = ["Metoprolol Succinate Sustained-release tablet", "metoprolol tartrate injection"]
ACEI_ARB_DRUG_NAMES = ["Benazepril hydrochloride tablet", "Valsartan Dispersible tablet"]


def compute_maggic11(patient_row: dict) -> dict:
    """MAGGIC-11: reuses compute_maggic_score() unmodified, current_smoker and
    hf_duration_18mo_plus fixed at False (their zero-contribution value -- exclusion, not a
    default guess). Returns {"maggic11_score": int, "component_points": {...11 keys...}}."""
    result = compute_maggic_score(
        age=patient_row["age"],
        sex=patient_row["sex"],
        ejection_fraction_pct=patient_row["ejection_fraction_pct"],
        nyha_class=patient_row["nyha_class"],
        bmi=patient_row["bmi"],
        systolic_bp_mmhg=patient_row["systolic_bp_mmhg"],
        serum_creatinine_umol_l=patient_row["serum_creatinine_umol_l"],
        diabetes=patient_row["diabetes"],
        copd=patient_row["copd"],
        current_smoker=False,  # excluded, not assumed -- see module docstring
        hf_duration_18mo_plus=False,  # excluded, not assumed -- see module docstring
        on_beta_blocker=patient_row["on_beta_blocker"],
        on_acei_arb=patient_row["on_acei_arb"],
    )
    assert result["component_points"]["current_smoker"] == 0
    assert result["component_points"]["hf_duration_18mo_plus"] == 0
    components = {k: v for k, v in result["component_points"].items() if k not in ("current_smoker", "hf_duration_18mo_plus")}
    return {"maggic11_score": sum(components.values()), "component_points": components}


def main() -> None:
    dat = pd.read_csv(DATA_DIR / "dat.csv")
    md = pd.read_csv(DATA_DIR / "dat_md.csv")

    drop_mask = (
        (dat["pulse"] == 0) | (dat["respiration"] == 0) | (dat["systolic.blood.pressure"] == 0)
        | (dat["height"] < HEIGHT_FLOOR_M) | (dat["BMI"] > BMI_CEILING)
    )
    dat_clean = dat[~drop_mask].copy()
    n_clean = len(dat_clean)
    print(f"n raw = {len(dat)}, n cleaned = {n_clean}")

    dat_clean["composite_6mo"] = (
        (dat_clean["death.within.6.months"] == 1) | (dat_clean["re.admission.within.6.months"] == 1)
    ).astype(int)

    patients_with_any_drug = set(md["inpatient.number"])
    bb_patients = set(md[md["Drug_name"].isin(BETA_BLOCKER_DRUG_NAMES)]["inpatient.number"])
    acei_arb_patients = set(md[md["Drug_name"].isin(ACEI_ARB_DRUG_NAMES)]["inpatient.number"])
    dat_clean["has_any_drug_record"] = dat_clean["inpatient.number"].isin(patients_with_any_drug)
    dat_clean["on_beta_blocker"] = dat_clean["inpatient.number"].isin(bb_patients)
    dat_clean["on_acei_arb"] = dat_clean["inpatient.number"].isin(acei_arb_patients)

    core_fields = [
        "ageCat", "gender", "BMI", "systolic.blood.pressure", "LVEF",
        "creatinine.enzymatic.method", "diabetes", "Chronic.obstructive.pulmonary.disease",
        "NYHA.cardiac.function.classification",
    ]
    complete_mask = dat_clean[core_fields].notna().all(axis=1) & dat_clean["has_any_drug_record"]
    cohort = dat_clean[complete_mask].copy()
    n_cohort = len(cohort)
    print(f"\nMAGGIC-11 complete-case cohort (11 available/derivable fields, no imputation): n={n_cohort} / {n_clean}")

    unmapped = set(cohort["ageCat"]) - set(AGECAT_MIDPOINT)
    if unmapped:
        raise ValueError(f"ageCat values with no midpoint mapping: {unmapped}")

    scores = []
    for _, p in cohort.iterrows():
        patient_row = {
            "age": AGECAT_MIDPOINT[p["ageCat"]],
            "sex": p["gender"],
            "ejection_fraction_pct": float(p["LVEF"]),
            "nyha_class": p["NYHA.cardiac.function.classification"],
            "bmi": float(p["BMI"]),
            "systolic_bp_mmhg": float(p["systolic.blood.pressure"]),
            "serum_creatinine_umol_l": float(p["creatinine.enzymatic.method"]),
            "diabetes": bool(p["diabetes"]),
            "copd": bool(p["Chronic.obstructive.pulmonary.disease"]),
            "on_beta_blocker": bool(p["on_beta_blocker"]),
            "on_acei_arb": bool(p["on_acei_arb"]),
        }
        scores.append(compute_maggic11(patient_row)["maggic11_score"])
    cohort["maggic11_score"] = scores

    print(f"\nMAGGIC-11 score distribution (n={n_cohort}):")
    print(cohort["maggic11_score"].describe())

    y_true = cohort["composite_6mo"].to_numpy()
    y_score = cohort["maggic11_score"].to_numpy()
    event_rate = y_true.mean()

    auc_point, auc_lo, auc_hi = bootstrap_metric_ci(y_true, y_score, roc_auc_score)
    pr_point, pr_lo, pr_hi = bootstrap_metric_ci(y_true, y_score, average_precision_score)

    print(f"\ncomposite_6mo event rate: {event_rate:.1%}")
    print(f"AUC = {auc_point:.3f} (95% CI {auc_lo:.3f}-{auc_hi:.3f})")
    print(f"PR-AUC = {pr_point:.3f} (95% CI {pr_lo:.3f}-{pr_hi:.3f}); baseline = {event_rate:.3f}")

    cohort["score_decile"] = pd.qcut(cohort["maggic11_score"], q=10, duplicates="drop")
    calibration = (
        cohort.groupby("score_decile", observed=True)
        .agg(n=("composite_6mo", "size"), mean_score=("maggic11_score", "mean"),
             observed_event_rate=("composite_6mo", "mean"))
        .reset_index(drop=True)
    )
    print("\nCalibration (decile bins):")
    print(calibration.round(4).to_string(index=False))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cohort.to_csv(OUT_DIR / "results.csv", index=False)

    lines = [
        "# Zigong cohort: MAGGIC-11 (MAGGIC-adapted, missing smoker status + HF duration) -- EXPLORATORY, standalone",
        "",
        "NOT the validated 13-variable MAGGIC score. 11 of 13 predictors used, all real per-patient",
        "Zigong values (age via ageCat bin-midpoint; beta-blocker/ACEI-ARB derived from dat_md.csv).",
        "current_smoker and hf_duration_18mo_plus are structurally absent from this dataset and are",
        "EXCLUDED (zero-contribution), not defaulted/assumed.",
        "",
        f"Cleaning: n raw={len(dat)} -> n cleaned={n_clean} (same 5 rules as Sec 7.Y).",
        f"MAGGIC-11 complete-case cohort (11 fields, no imputation): n={n_cohort}",
        f"Composite outcome (death OR readmission, 6mo) event rate: {event_rate:.1%}",
        "",
        "## Discrimination (AUC / PR-AUC)",
        "",
        f"- AUC = {auc_point:.3f} (95% CI {auc_lo:.3f}-{auc_hi:.3f}, percentile bootstrap, 2000",
        f"  resamples, seed=42)",
        f"- PR-AUC = {pr_point:.3f} (95% CI {pr_lo:.3f}-{pr_hi:.3f}); event-rate baseline = {event_rate:.3f}",
        "",
        "## Calibration (decile bins)",
        "",
        "```",
        calibration.round(4).to_string(index=False),
        "```",
    ]
    (OUT_DIR / "summary.md").write_text("\n".join(lines))
    print(f"\nWrote {OUT_DIR / 'results.csv'} and {OUT_DIR / 'summary.md'}")


if __name__ == "__main__":
    main()
