"""Computes real reference statistics from the raw datasets in data/raw/, so every number in
reference_stats.yaml traces back to something reproducible rather than a hand-typed guess.

Sources (all gitignored under data/raw/ -- never committed, per data use terms):
  - data/raw/mimic/hf_patient_features_clean.csv
      MIMIC-IV heart-failure admissions, extracted via BigQuery (physionet-data project).
      Requires PhysioNet credentialing to reproduce -- not redownloadable by this script.
  - data/raw/kaggle/andrewmvd_clinical/heart_failure_clinical_records_dataset.csv
      Chicco & Jurman 2020 heart failure clinical records (n=299). Canonical, peer-reviewed,
      most-cited HF Kaggle dataset (184k+ downloads). Only source here with ejection_fraction.
  - data/raw/kaggle/fedesoriano_prediction/heart.csv
      General cardiovascular risk dataset (n=918, combined Cleveland/Hungarian/Switzerland/VA +
      Statlog). Not HF-specific -- used only for general age/BP/HR cross-check, not EF/BNP.
  - data/raw/kaggle/cdc_nhanes/{demographic,examination}.csv
      Official CDC NHANES survey (demographic.csv has RIAGENDR/RIDAGEYR, examination.csv has
      BMXWT/BMXHT/BMXBMI). General US adult population, not HF-specific -- used only for
      height/weight/BMI by sex, since no other acquired source has anthropometrics at all.

Rejected: data/raw/kaggle/aadarshvelu_clinical/ (n=5000) -- checked and found to be a resampled/
augmented version of the same small underlying pool as andrewmvd (only 203 unique platelet
values across 5000 rows, 3680 exact duplicate rows, near-identical mean/SD to andrewmvd's 299
rows). Using it alongside andrewmvd would double-count the same ~300 real patients while implying
a larger independent sample, so it's excluded rather than treated as a third source.

Run from repo root: python3 -m src.data_synthesis.reference_extraction
"""
from __future__ import annotations

import pathlib

import pandas as pd

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "data" / "raw"

MIMIC_PATH = RAW / "mimic" / "hf_patient_features_clean.csv"
ANDREWMVD_PATH = RAW / "kaggle" / "andrewmvd_clinical" / "heart_failure_clinical_records_dataset.csv"
FEDESORIANO_PATH = RAW / "kaggle" / "fedesoriano_prediction" / "heart.csv"
NHANES_DEMO_PATH = RAW / "kaggle" / "cdc_nhanes" / "demographic.csv"
NHANES_EXAM_PATH = RAW / "kaggle" / "cdc_nhanes" / "examination.csv"


def _describe(series: pd.Series) -> dict:
    return {"mean": round(float(series.mean()), 2), "sd": round(float(series.std()), 2),
            "min": round(float(series.min()), 2), "max": round(float(series.max()), 2)}


def extract_mimic_stats() -> dict:
    df = pd.read_csv(MIMIC_PATH)
    return {
        "n_admissions": len(df),
        "n_unique_patients": int(df["subject_id"].nunique()),
        "age": _describe(df["age"]),
        "sex_male_fraction": round(float((df["gender"] == "M").mean()), 3),
        "resting_hr_bpm": _describe(df["mean_hr"]),
        "sbp_mmhg": _describe(df["mean_sbp"]),
        "dbp_mmhg": _describe(df["mean_dbp"]),
        "creatinine_mg_dl": _describe(df["creatinine"]),
        "sodium_meq_l": _describe(df["sodium"]),
    }


def extract_andrewmvd_stats() -> dict:
    df = pd.read_csv(ANDREWMVD_PATH)
    hfref = df[df["ejection_fraction"] <= 40]
    hfpef = df[df["ejection_fraction"] >= 50]
    return {
        "n_patients": len(df),
        "ejection_fraction_hfref": _describe(hfref["ejection_fraction"]) | {"n": len(hfref)},
        "ejection_fraction_hfpef": _describe(hfpef["ejection_fraction"]) | {"n": len(hfpef)},
        "serum_creatinine_mg_dl": _describe(df["serum_creatinine"]),
        "serum_sodium_meq_l": _describe(df["serum_sodium"]),
        "sex_male_fraction": round(float(df["sex"].mean()), 3),
    }


def extract_fedesoriano_stats() -> dict:
    df = pd.read_csv(FEDESORIANO_PATH)
    return {
        "n_patients": len(df),
        "age": _describe(df["Age"]),
        "resting_bp_mmhg": _describe(df["RestingBP"]),
        "max_hr_bpm": _describe(df["MaxHR"]),
        "sex_male_fraction": round(float((df["Sex"] == "M").mean()), 3),
    }


def extract_nhanes_stats() -> dict:
    demo = pd.read_csv(NHANES_DEMO_PATH, usecols=["SEQN", "RIAGENDR", "RIDAGEYR"])
    exam = pd.read_csv(NHANES_EXAM_PATH, usecols=["SEQN", "BMXWT", "BMXHT", "BMXBMI"])
    df = demo.merge(exam, on="SEQN", how="inner")
    adults = df[(df["RIDAGEYR"] >= 18) & df["BMXWT"].notna() & df["BMXHT"].notna()]

    out = {"n_adults": len(adults)}
    for sex_code, label in [(1, "male"), (2, "female")]:
        g = adults[adults["RIAGENDR"] == sex_code]
        out[label] = {
            "n": len(g),
            "height_cm": _describe(g["BMXHT"]),
            "weight_kg": _describe(g["BMXWT"]),
            "bmi": _describe(g["BMXBMI"]),
        }
    return out


if __name__ == "__main__":
    import json

    report = {}
    if MIMIC_PATH.exists():
        report["mimic"] = extract_mimic_stats()
    else:
        print(f"skip: {MIMIC_PATH} not found (credentialed source, not redownloadable here)")
    if ANDREWMVD_PATH.exists():
        report["andrewmvd_kaggle"] = extract_andrewmvd_stats()
    if FEDESORIANO_PATH.exists():
        report["fedesoriano_kaggle"] = extract_fedesoriano_stats()
    if NHANES_DEMO_PATH.exists() and NHANES_EXAM_PATH.exists():
        report["nhanes_kaggle"] = extract_nhanes_stats()

    print(json.dumps(report, indent=2))
