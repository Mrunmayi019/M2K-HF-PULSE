"""Daily wearable trend simulator.

For each synthetic patient (from generate_patients.generate_patients), produces a daily time
series of resting HR, SpO2, weight, steps, sleep, and HRV over a rolling window.

Three trend modes, per the project's own roadmap correction: `stable`, `deteriorating`, and
`recovering`. `recovering` exists so that a risk score trained on this data can go down as well as
up -- without it, a model can never learn that a patient's risk can improve after intervention,
which was flagged as a real bug risk in the planning doc (see docs/architecture.md history).
"""
from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd

try:
    from .generate_patients import REPO_ROOT, generate_patients, load_reference_stats
except ImportError:  # allows running this file directly as a script
    from generate_patients import REPO_ROOT, generate_patients, load_reference_stats

DEFAULT_OUTPUT_PATH = REPO_ROOT / "data" / "synthetic" / "wearable_trends.csv"

VITALS = ["resting_hr_bpm", "spo2_pct", "weight_kg", "steps_per_day", "sleep_hours", "hrv_rmssd_ms"]

# Max deviation from baseline at full severity (1.0) and full trend progression, per scenario
# type. Signs match clinical direction: fluid overload gains weight, cardiac stress spikes HR
# and tanks HRV, deconditioning mainly drops activity, acute deterioration moves everything and
# fastest. "stable" is intentionally absent -- it never drifts.
SCENARIO_SIGNAL_DELTAS = {
    "fluid_overload": {
        "weight_kg": 4.5, "resting_hr_bpm": 12, "spo2_pct": -2.5,
        "steps_per_day": -1200, "sleep_hours": -0.8, "hrv_rmssd_ms": -6,
    },
    "cardiac_stress": {
        "weight_kg": 0.5, "resting_hr_bpm": 20, "spo2_pct": -1.5,
        "steps_per_day": -1000, "sleep_hours": -0.5, "hrv_rmssd_ms": -12,
    },
    "deconditioning": {
        "weight_kg": 1.0, "resting_hr_bpm": 8, "spo2_pct": -0.5,
        "steps_per_day": -2500, "sleep_hours": -0.3, "hrv_rmssd_ms": -5,
    },
    "acute_deterioration": {
        "weight_kg": 3.0, "resting_hr_bpm": 25, "spo2_pct": -5.0,
        "steps_per_day": -2000, "sleep_hours": -1.2, "hrv_rmssd_ms": -15,
    },
}

NOISE_SD_FRACTION = 0.15  # daily noise as a fraction of each vital's population SD
WEIGHT_NOISE_SD_KG = 0.4  # plausible day-to-day scale fluctuation


def _trend_curve(frac: np.ndarray, mode: str, scenario_type: str) -> np.ndarray:
    """Returns a 0-1ish progression multiplier over the window, shape depends on mode."""
    if mode == "stable":
        return np.zeros_like(frac)
    if mode == "deteriorating":
        # acute_deterioration accelerates near the end rather than drifting linearly
        return frac**2 if scenario_type == "acute_deterioration" else frac
    if mode == "recovering":
        # starts near peak severity (as if already deteriorated), decays toward/past baseline
        return np.clip(1 - 1.15 * frac, 0, None)
    raise ValueError(f"unknown trend mode: {mode}")


def _assign_trend_mode(rng: np.random.Generator, scenario_type: str, severity: float) -> str:
    if scenario_type == "stable":
        return "stable"
    p_deteriorating = float(np.clip(0.4 + 0.5 * severity, 0, 0.95))
    return rng.choice(["deteriorating", "recovering"], p=[p_deteriorating, 1 - p_deteriorating])


def generate_wearable_trends(patients_df: pd.DataFrame, days: int = 21, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    stats = load_reference_stats()
    baseline_cfg = stats["wearable_baseline"]

    frac = np.arange(days) / max(days - 1, 1)
    records = []

    for _, patient in patients_df.iterrows():
        scenario_type = patient["scenario_type"]
        severity = float(patient["severity"])
        mode = _assign_trend_mode(rng, scenario_type, severity)
        deltas = SCENARIO_SIGNAL_DELTAS.get(scenario_type, {v: 0.0 for v in VITALS})
        curve = _trend_curve(frac, mode, scenario_type)

        # Weight baseline anchors to the patient's own recorded weight (from generate_patients)
        # rather than a fresh population sample -- a wearable scale reports *this* patient's
        # weight, not a population mean.
        baseline = {
            v: rng.normal(baseline_cfg[v]["mean"], baseline_cfg[v]["sd"])
            for v in VITALS if v != "weight_kg"
        }
        baseline["weight_kg"] = float(patient["weight_kg"])
        noise = {
            v: rng.normal(0, baseline_cfg[v]["sd"] * NOISE_SD_FRACTION, days)
            for v in VITALS if v != "weight_kg"
        }
        noise["weight_kg"] = rng.normal(0, WEIGHT_NOISE_SD_KG, days)

        for day_idx in range(days):
            row = {
                "patient_id": patient["patient_id"],
                "day": day_idx,
                "scenario_type": scenario_type,
                "trend_mode": mode,
            }
            for v in VITALS:
                delta_max = deltas.get(v, 0.0)
                row[v] = round(
                    baseline[v] + delta_max * severity * curve[day_idx] + noise[v][day_idx], 2
                )
            records.append(row)

    df = pd.DataFrame.from_records(records)
    df["spo2_pct"] = df["spo2_pct"].clip(upper=100)
    df["steps_per_day"] = df["steps_per_day"].clip(lower=0)
    df["sleep_hours"] = df["sleep_hours"].clip(lower=0)
    df["hrv_rmssd_ms"] = df["hrv_rmssd_ms"].clip(lower=1)
    return df


if __name__ == "__main__":
    # n=2000 -- see the matching comment in generate_patients.py's __main__ block.
    patients = generate_patients(n=2000)
    trends = generate_wearable_trends(patients)
    DEFAULT_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    trends.to_csv(DEFAULT_OUTPUT_PATH, index=False)
    print(f"Wrote {len(trends)} rows ({trends['patient_id'].nunique()} patients) to {DEFAULT_OUTPUT_PATH}")
    print(trends["trend_mode"].value_counts())
