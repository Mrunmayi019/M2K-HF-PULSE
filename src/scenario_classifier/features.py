"""Per-patient feature engineering for the Phase 3 scenario classifier (Model 1).

Turns a patient's clinical snapshot (from generate_patients) plus their 21-day wearable trend
(from generate_wearable_trends) into a single feature row. This is the same shape of input the
model will see in deployment: a clinical report + a rolling wearable window, not raw simulation
internals.

Leakage guard: `trend_mode` and `scenario_type` in wearable_trends.csv are derived directly from
the label and must never appear as features. `severity` is a training target (predicted alongside
scenario_type), not an input -- it legitimately drives the wearable deltas and clinical values, so
the model infers it from those measurable effects rather than being handed it directly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

VITALS = ["resting_hr_bpm", "spo2_pct", "weight_kg", "steps_per_day", "sleep_hours", "hrv_rmssd_ms"]

NYHA_ORDINAL = {"I": 0, "II": 1, "III": 2, "IV": 3}

CLINICAL_FEATURE_COLUMNS = [
    "age", "sex_male", "bmi", "ejection_fraction_pct", "nt_probnp_pg_ml", "nyha_ordinal",
]

TARGET_COLUMNS = ["scenario_type", "severity"]


def _wearable_features(trends_df: pd.DataFrame) -> pd.DataFrame:
    """One row per patient_id: first/last-7-day means, delta, and 21-day slope per vital."""
    rows = []
    for patient_id, g in trends_df.sort_values("day").groupby("patient_id", sort=False):
        day = g["day"].to_numpy()
        row = {"patient_id": patient_id}
        for v in VITALS:
            values = g[v].to_numpy()
            first_week = values[day < 7].mean()
            last_week = values[day >= max(day.max() - 6, 0)].mean()
            slope = np.polyfit(day, values, 1)[0]
            row[f"{v}_first7_mean"] = first_week
            row[f"{v}_last7_mean"] = last_week
            row[f"{v}_delta"] = last_week - first_week
            row[f"{v}_slope"] = slope
        rows.append(row)
    return pd.DataFrame(rows)


def build_features(patients_df: pd.DataFrame, trends_df: pd.DataFrame) -> pd.DataFrame:
    """Returns one row per patient: engineered features + TARGET_COLUMNS, joined on patient_id.

    Feature columns are CLINICAL_FEATURE_COLUMNS + the wearable columns produced by
    `_wearable_features` (never `trend_mode` or raw `scenario_type`).
    """
    clinical = patients_df.copy()
    clinical["sex_male"] = (clinical["sex"] == "Male").astype(int)
    clinical["nyha_ordinal"] = clinical["nyha_class"].map(NYHA_ORDINAL)

    wearable = _wearable_features(trends_df)

    merged = clinical.merge(wearable, on="patient_id", how="inner")

    feature_columns = CLINICAL_FEATURE_COLUMNS + [c for c in wearable.columns if c != "patient_id"]
    return merged[["patient_id"] + feature_columns + TARGET_COLUMNS]


def feature_columns(features_df: pd.DataFrame) -> list[str]:
    """Feature column names present in a `build_features` output (excludes id + targets)."""
    return [c for c in features_df.columns if c not in {"patient_id", *TARGET_COLUMNS}]


def build_inference_features(patient_row: dict, trends_df: pd.DataFrame) -> pd.DataFrame:
    """Phase 6: same feature construction as `build_features`, for live API inference where
    `scenario_type`/`severity` aren't known yet -- they're exactly what the classifier predicts.

    `build_features` can't be reused directly for this: its final column selection hard-requires
    TARGET_COLUMNS to already be present (correct for training, where they're the labels; a
    KeyError otherwise). This returns feature columns only, no targets.

    `patient_row` needs `patient_id`, `age`, `sex`, `bmi`, `ejection_fraction_pct`,
    `nt_probnp_pg_ml`. `nyha_class` is optional -- a brand-new patient won't have one yet (it's
    what `src/analytics/staging.py` computes *from* the simulation this feature vector feeds into),
    so it defaults to "I" if absent, the same kind of explicit Tier-1-style fallback used elsewhere
    in the API (see docs/data_provenance.md).
    """
    clinical = pd.DataFrame([patient_row])
    clinical["sex_male"] = (clinical["sex"] == "Male").astype(int)
    clinical["nyha_ordinal"] = clinical.get("nyha_class", pd.Series(["I"])).fillna("I").map(NYHA_ORDINAL)

    wearable = _wearable_features(trends_df)
    merged = clinical.merge(wearable, on="patient_id", how="inner")

    feature_cols = CLINICAL_FEATURE_COLUMNS + [c for c in wearable.columns if c != "patient_id"]
    return merged[["patient_id"] + feature_cols]
