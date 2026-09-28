"""Synthetic deterioration stress-test: anchors a synthetic 21-day acute_deterioration wearable
trend to each real BCG-validation patient's (subject 14, subject 102) real baseline HR/EF, then
runs it through the existing Tier 1 scenario classifier + severity regressor.

IMPORTANT SCOPE NOTE, same discipline as docs/bcg_validation_note.md: this tests internal
pipeline consistency (does the classifier detect a trend that was synthetically constructed to
look like deterioration) using two subjects' REAL baselines as anchors -- it is NOT evidence this
system detects real deterioration in real patients. No real longitudinal data exists for either
subject; the entire 21-day trajectory past day 0 is synthetic. See
docs/synthetic_deterioration_stress_test.md for the full writeup and this limitation stated
up front.

Reuses existing generation code directly, does not reimplement trend logic:
  - SCENARIO_SIGNAL_DELTAS, _trend_curve() from src.data_synthesis.generate_wearable_trends
    (the same per-vital max-deltas and trend-shape function used for all 5 scenario types)
  - build_inference_features(), feature_columns() from src.scenario_classifier.features
    (the same live-inference feature builder src/api/services.py's production path uses)
  - The same trained models/scenario_classifier.joblib + severity_regressor.joblib

What's NOT reused as-is: generate_wearable_trends() itself samples each vital's baseline from a
population distribution (rng.normal(reference_mean, reference_sd)) -- it has no parameter to
anchor a real patient's own measured HR. So this script builds the per-day trend using the same
delta/noise formula generate_wearable_trends() uses internally, but with a manually-constructed
baseline dict where resting_hr_bpm is the real value instead of a population draw (weight_kg is
already anchored to a "real" value in the original function too, following that same existing
precedent -- see its own module docstring). Everything else (SpO2, steps, sleep, HRV) uses the
same population reference means the original function already uses for those vitals, since
neither subject has a real measurement for them.

Trend mode is forced to "deteriorating" (not drawn via the original function's probabilistic
_assign_trend_mode) -- this is a deliberate stress test of a worsening trajectory, not a random
draw that could produce "recovering".
"""
from __future__ import annotations

import pathlib

import joblib
import numpy as np
import pandas as pd

from src.data_synthesis.generate_patients import load_reference_stats
from src.data_synthesis.generate_wearable_trends import (
    NOISE_SD_FRACTION,
    SCENARIO_SIGNAL_DELTAS,
    VITALS,
    WEIGHT_NOISE_SD_KG,
    _trend_curve,
)
from src.scenario_classifier.features import build_inference_features, feature_columns

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MODELS_DIR = REPO_ROOT / "models"
OUT_DIR = REPO_ROOT / "data" / "synthetic_deterioration_stress_test"

DAYS = 21
SCENARIO_TYPE = "acute_deterioration"
ASSUMED_TRUE_SEVERITY = 0.85  # this test's synthetic ground truth -- NOT a measured real value
NT_PROBNP_FALLBACK_PG_ML = 100.0  # same Tier-1 fallback src/api/services.py uses (no real BNP measured for either subject)

# No severity-specific alert threshold exists anywhere in this codebase (checked: training config,
# model_card.md, every eval script, staging.py -- which imports risk_score.py's boundaries and
# applies them to risk_score, never defining its own on severity). risk_score.py's
# MODERATE_HIGH_BOUNDARY=0.65 was considered and REJECTED: computed on the real 117-row Phase 4
# dataset, risk_score and severity are not on comparable scales for acute_deterioration
# specifically (risk_score's own floor there, 0.491, sits above severity's mean, 0.385 -- risk_score
# saturates high almost as soon as any Exercise-driven stress occurs, a structural property already
# documented in docs/methodology.md Sec 6.1). Borrowing 0.65 for severity would imply a validated
# cutoff that doesn't exist. Used instead: STABLE_SEVERITY_CEILING, a real, non-arbitrary property
# of this training data (not invented, not borrowed from a different quantity) -- generate_patients.py's
# own _assign_scenario() hard-codes `severity = severity * 0.15` for "stable" patients, confirmed at
# n=2000 (actual observed max 0.149). Reported as "the day this trajectory first clearly exceeds
# what 'stable' looks like in this training data" -- a descriptive marker, not a clinical alert cutoff.
STABLE_SEVERITY_CEILING = 0.15

SUBJECTS = {
    "subject14": {
        "patient_id": "bcg_subject14_trend",
        "age": 53, "sex": "Male", "height_cm": 160, "weight_kg": 70,
        "ejection_fraction_pct": 34.7,
        "real_hr_bpm": 77,
        "seed": 1400,  # fixed, arbitrary but constant -- NOT hash(label), which is randomized per process
    },
    "subject102": {
        "patient_id": "bcg_subject102_trend",
        "age": 45, "sex": "Male", "height_cm": 182, "weight_kg": 94,
        "ejection_fraction_pct": 35.1,
        "real_hr_bpm": 115,
        "seed": 1020,
    },
}


def build_trend(subject_cfg: dict, seed: int) -> pd.DataFrame:
    """Same per-day formula as generate_wearable_trends(), with a real-HR-anchored baseline."""
    rng = np.random.default_rng(seed)
    stats = load_reference_stats()
    baseline_cfg = stats["wearable_baseline"]

    frac = np.arange(DAYS) / max(DAYS - 1, 1)
    curve = _trend_curve(frac, "deteriorating", SCENARIO_TYPE)  # frac**2 for acute_deterioration
    deltas = SCENARIO_SIGNAL_DELTAS[SCENARIO_TYPE]

    baseline = {v: baseline_cfg[v]["mean"] for v in VITALS if v not in ("resting_hr_bpm", "weight_kg")}
    baseline["resting_hr_bpm"] = float(subject_cfg["real_hr_bpm"])  # real anchor, not population draw
    baseline["weight_kg"] = float(subject_cfg["weight_kg"])  # real anchor, same precedent as the original function

    noise = {
        v: rng.normal(0, baseline_cfg[v]["sd"] * NOISE_SD_FRACTION, DAYS)
        for v in VITALS if v not in ("resting_hr_bpm", "weight_kg")
    }
    # resting_hr_bpm noise still uses the population SD for day-to-day wearable measurement
    # noise (the real value only anchors the MEAN, not the assumed measurement variability).
    noise["resting_hr_bpm"] = rng.normal(0, baseline_cfg["resting_hr_bpm"]["sd"] * NOISE_SD_FRACTION, DAYS)
    noise["weight_kg"] = rng.normal(0, WEIGHT_NOISE_SD_KG, DAYS)

    rows = []
    for day_idx in range(DAYS):
        row = {"patient_id": subject_cfg["patient_id"], "day": day_idx}
        for v in VITALS:
            delta_max = deltas.get(v, 0.0)
            row[v] = round(
                baseline[v] + delta_max * ASSUMED_TRUE_SEVERITY * curve[day_idx] + noise[v][day_idx], 2
            )
        rows.append(row)

    df = pd.DataFrame(rows)
    df["spo2_pct"] = df["spo2_pct"].clip(upper=100)
    df["steps_per_day"] = df["steps_per_day"].clip(lower=0)
    df["sleep_hours"] = df["sleep_hours"].clip(lower=0)
    df["hrv_rmssd_ms"] = df["hrv_rmssd_ms"].clip(lower=1)
    return df


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    clf = joblib.load(MODELS_DIR / "scenario_classifier.joblib")
    reg = joblib.load(MODELS_DIR / "severity_regressor.joblib")

    for label, cfg in SUBJECTS.items():
        trend = build_trend(cfg, seed=cfg["seed"])
        trend_path = OUT_DIR / f"{label}_trend.csv"
        trend.to_csv(trend_path, index=False)

        bmi = cfg["weight_kg"] / (cfg["height_cm"] / 100.0) ** 2
        ml_row = {
            "patient_id": cfg["patient_id"],
            "age": cfg["age"],
            "sex": cfg["sex"],
            "bmi": bmi,
            "ejection_fraction_pct": cfg["ejection_fraction_pct"],
            "nt_probnp_pg_ml": NT_PROBNP_FALLBACK_PG_ML,
        }

        print(f"\n=== {label} (real HR={cfg['real_hr_bpm']}, real EF={cfg['ejection_fraction_pct']}%) ===")
        print(trend.to_string(index=False))

        print(f"\n--- Expanding-window classifier/severity predictions, day 7-21 ---")
        print(f"(production system only ever predicts once, at the full day-21 window -- this "
              f"expanding-window sweep is this stress test's own analysis, built on the existing "
              f"build_inference_features(), to find the earliest day severity clearly exceeds "
              f"what 'stable' looks like in training data, {STABLE_SEVERITY_CEILING} -- see script "
              f"docstring/comment for why a borrowed risk_score threshold was rejected instead)")
        first_divergence_day = None
        prev_severity = None
        severities = []
        for n in range(7, DAYS + 1):
            window = trend[trend["day"] < n]
            features_df = build_inference_features(ml_row, window)
            cols = feature_columns(features_df)
            scenario_pred = clf.predict(features_df[cols])[0]
            severity_pred = float(reg.predict(features_df[cols])[0])
            severities.append(severity_pred)
            direction = "" if prev_severity is None else (
                "up" if severity_pred > prev_severity else ("down" if severity_pred < prev_severity else "flat")
            )
            flag = ""
            if severity_pred >= STABLE_SEVERITY_CEILING and first_divergence_day is None:
                first_divergence_day = n - 1  # 0-indexed day, last day included in this window
                flag = "  <-- first exceeds stable-scenario ceiling"
            print(f"  day {n-1:2d} (window=day0..{n-1}): scenario={scenario_pred:20s} "
                  f"severity={severity_pred:.4f} ({direction}){flag}")
            prev_severity = severity_pred

        monotonic = all(b >= a - 1e-9 for a, b in zip(severities, severities[1:]))
        print(f"\nFinal-window scenario classification: {scenario_pred}")
        print(f"Severity monotonically non-decreasing across the full window sweep: {monotonic}")
        print(f"First day severity exceeds the stable-scenario ceiling ({STABLE_SEVERITY_CEILING}): "
              f"{'day ' + str(first_divergence_day) if first_divergence_day is not None else 'never'}")
        print(f"Wrote trend to {trend_path}")


if __name__ == "__main__":
    main()
