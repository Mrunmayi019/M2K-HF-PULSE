"""Phase 5: slope-based deterioration rate + days-to-next-stage estimate.

Operates on a single patient's 21-day wearable trend (data/synthetic/wearable_trends.csv slice),
reusing the exact per-vital slope technique already built in
src/scenario_classifier/features.py's `_wearable_features()` (np.polyfit trend slope) rather than
reimplementing it.

Unlike src/analytics/risk_score.py (which scores one Pulse simulation snapshot), this module
reads the wearable time series directly -- a different data source on a different scale, so
combining per-vital slopes into one composite requires normalizing them onto a common scale first.
Each vital's slope is expressed in population-SD-equivalents/day using this project's own
`wearable_baseline` SDs (already in reference_stats.yaml/data_provenance.md), then combined with a
sign convention that matches how generate_wearable_trends.py already defines "worsening" per vital
(SCENARIO_SIGNAL_DELTAS: HR/weight rise, SpO2/steps/sleep/HRV fall, as severity increases).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.analytics.risk_score import LOW_HIGH_BOUNDARY, MODERATE_HIGH_BOUNDARY
from src.data_synthesis.generate_patients import load_reference_stats
from src.data_synthesis.generate_wearable_trends import WEIGHT_NOISE_SD_KG

# +1 if a rising value means worsening, -1 if a falling value means worsening -- matches the sign
# convention already embedded in generate_wearable_trends.py's SCENARIO_SIGNAL_DELTAS.
WORSENING_SIGN = {
    "resting_hr_bpm": 1,
    "spo2_pct": -1,
    "weight_kg": 1,
    "steps_per_day": -1,
    "sleep_hours": -1,
    "hrv_rmssd_ms": -1,
}

# Rough, explicitly hand-tuned engineering calibration -- there is no clinical literature source
# for "how many population-SDs/day of wearable drift equals how much daily risk_score change".
# Treated the same way this project treats other assumed_default constants: named, documented,
# and flagged as not empirically fit. See docs/data_provenance.md.
#
# Used ONLY for risk_score-scale consumers (days_to_next_stage() below). Do NOT reuse this for
# projecting `severity` (ML Model 1's classifier output) -- severity and risk_score are NOT on
# comparable scales (docs/methodology.md Sec 8, "severity and risk_score are not on comparable
# scales", discovered 2026-09-10: risk_score's own floor for acute_deterioration, 0.491, sits
# above severity's mean, 0.385, in the real 117-row Phase 4 dataset). Reusing this constant to
# project severity was exactly the bug fixed in src/analytics/projection.py's project_severity()
# that session -- SD_RATE_TO_SEVERITY_PER_DAY below is the separate, severity-scoped constant for
# that use, deliberately independent so the two calibrations can never be conflated again by
# construction, not just by caller discipline.
SD_RATE_TO_RISK_SCORE_PER_DAY = 0.05

# Severity-scale counterpart to SD_RATE_TO_RISK_SCORE_PER_DAY above, used only by
# src/analytics/projection.py's project_severity(). Same status: an explicitly hand-tuned
# engineering placeholder, not derived from real severity-trajectory calibration data (none
# exists -- see docs/methodology.md Sec 8's "blocked on data" note). Deliberately given the same
# starting magnitude as SD_RATE_TO_RISK_SCORE_PER_DAY only because there is no basis yet to pick a
# different number for either scale independently -- this fixes the *structural* conflation bug
# (severity and risk_score can now be recalibrated independently), not the *numerical* one (this
# specific value is still unvalidated and pending real data either way).
SD_RATE_TO_SEVERITY_PER_DAY = 0.05

# Composite rate below this magnitude (population-SD-equivalents/day) is treated as noise, not a
# real trend -- an engineering choice, not a clinical citation.
STABLE_RATE_EPSILON = 0.05


def _population_sd(vital: str) -> float:
    if vital == "weight_kg":
        return WEIGHT_NOISE_SD_KG
    return load_reference_stats()["wearable_baseline"][vital]["sd"]


def compute_deterioration_rate(trends_df_for_one_patient: pd.DataFrame) -> dict:
    """`trends_df_for_one_patient` is wearable_trends.csv rows for exactly one patient_id.

    Returns per-vital raw slopes (native units/day), per-vital normalized worsening rates
    (population-SD-equivalents/day, positive = worsening), a composite rate (mean of the
    normalized rates), and a direction label.
    """
    day = trends_df_for_one_patient["day"].to_numpy()
    vital_slopes = {}
    normalized_rates = {}

    for vital, sign in WORSENING_SIGN.items():
        values = trends_df_for_one_patient[vital].to_numpy()
        slope = float(np.polyfit(day, values, 1)[0])
        vital_slopes[vital] = slope
        normalized_rates[vital] = sign * slope / _population_sd(vital)

    composite_rate = float(np.mean(list(normalized_rates.values())))

    if composite_rate > STABLE_RATE_EPSILON:
        direction = "worsening"
    elif composite_rate < -STABLE_RATE_EPSILON:
        direction = "improving"
    else:
        direction = "stable"

    return {
        "vital_slopes": vital_slopes,
        "normalized_rates": normalized_rates,
        "composite_rate": composite_rate,
        "direction": direction,
    }


def days_to_next_stage(current_risk_score: float, composite_rate: float) -> int | None:
    """Linear extrapolation to the next LOW/MODERATE/HIGH boundary (src/analytics/risk_score.py).

    Returns None when the trend is flat/improving -- there is no meaningful forward date to
    report in that case.
    """
    risk_score_change_per_day = composite_rate * SD_RATE_TO_RISK_SCORE_PER_DAY
    if risk_score_change_per_day <= 0:
        return None

    if current_risk_score < LOW_HIGH_BOUNDARY:
        target = LOW_HIGH_BOUNDARY
    elif current_risk_score < MODERATE_HIGH_BOUNDARY:
        target = MODERATE_HIGH_BOUNDARY
    else:
        return None  # already at the highest bucket

    days = (target - current_risk_score) / risk_score_change_per_day
    return max(1, round(days))
