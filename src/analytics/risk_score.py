"""Phase 5, primary risk scorer: a hand-tuned, interpretable weighted score.

Per the locked decision in CLAUDE.md ("Risk scorer"), this -- not the secondary/experimental
XGBoost model in src/ml_models/train_risk_scorer.py -- is the system's primary risk output. Every
component's normalization anchor and every weight is documented here and in
docs/data_provenance.md; weights themselves are clinically *motivated*, not statistically fit to
data (there isn't enough data to fit them defensibly -- see model_card.md for why that reasoning
applies even harder to the secondary model).

Inputs are exactly the 5 features src/analytics/simulation_features.py extracts from one Pulse
run: hr_rise, map_drop, co_drop_pct, compensation_flag, instability_flag.
"""
from __future__ import annotations

# Assumed resting HR baseline this project already uses everywhere (reference_stats.yaml
# wearable_baseline.resting_hr_bpm) -- needed here because hr_rise is a delta, but the clinical
# banding below (NEWS2) is defined on absolute HR.
ASSUMED_RESTING_HR_BPM = 70.0

# NEWS2 (Royal College of Physicians, "National Early Warning Score (NEWS) 2", 2017) heart-rate
# scoring bands -- a validated, widely-used UK NHS early-warning score. Both very low and very
# high HR score points; NEWS2's own point values (0-3) are reused directly as the sub-score before
# normalizing to 0-1.
_NEWS2_HR_BANDS = [
    (40, 3), (50, 1), (90, 0), (110, 1), (130, 2),
]  # (upper bound inclusive, points); anything above the last bound scores 3
_NEWS2_MAX_POINTS = 3.0

# Approximate healthy resting MAP from this project's own validated Pulse `stable`-scenario output
# (docs/methodology.md §7 Phase 2 table: MAP 95->95, 90-95mmHg range across runs).
ASSUMED_HEALTHY_MAP_MMHG = 92.5
# Reused from simulation_features.py / data_provenance.md: Surviving Sepsis Campaign resuscitation
# target (MAP >=65mmHg); Vincent & De Backer, "Circulatory Shock", NEJM 2013.
INSTABILITY_MAP_THRESHOLD_MMHG = 65.0
_MAP_DROP_FULL_SCALE = ASSUMED_HEALTHY_MAP_MMHG - INSTABILITY_MAP_THRESHOLD_MMHG

# Cardiac output decline clinically associated with a severe low-output state -- Nohria et al.,
# "Medical management of advanced heart failure", JAMA 2002 (hemodynamic "cold" profiling), and
# the SCAI 2019 Cardiogenic Shock Stage consensus statement (classic/severe shock stages
# characterized by a markedly reduced cardiac index). 30% is used as the full-scale anchor.
CO_DROP_FULL_SCALE_PCT = 30.0

# Weights, clinically motivated (see module docstring), sum to 1.0. instability_flag is weighted
# highest as the single most acute, directly-actionable danger sign (shock-range MAP); map_drop
# and co_drop_pct next as continuous hemodynamic-decline measures; hr_rise and compensation_flag
# lowest since each alone is a weaker/less specific signal (HR rise alone can reflect benign
# exertion; failed compensation alone, without an accompanying pressure/output drop, is less
# immediately dangerous).
WEIGHTS = {
    "instability_flag": 0.30,
    "map_drop": 0.20,
    "co_drop_pct": 0.20,
    "hr_rise": 0.15,
    "compensation_flag": 0.15,
}

# Engineering choice (roughly a tertile split of the 0-1 score), not a clinical citation.
LOW_HIGH_BOUNDARY = 0.35
MODERATE_HIGH_BOUNDARY = 0.65


def _hr_rise_component(hr_rise: float) -> float:
    hr_end = ASSUMED_RESTING_HR_BPM + hr_rise
    for upper_bound, points in _NEWS2_HR_BANDS:
        if hr_end <= upper_bound:
            return points / _NEWS2_MAX_POINTS
    return 1.0  # above the last band (>130 bpm) -> max NEWS2 points


def _map_drop_component(map_drop: float) -> float:
    return max(0.0, min(map_drop / _MAP_DROP_FULL_SCALE, 1.0))


def _co_drop_pct_component(co_drop_pct: float) -> float:
    # Negative co_drop_pct means CO rose (e.g. a compensating heart under stress) -- not a risk.
    return max(0.0, min(co_drop_pct / CO_DROP_FULL_SCALE_PCT, 1.0))


def compute_risk_score(
    hr_rise: float,
    map_drop: float,
    co_drop_pct: float,
    compensation_flag: int,
    instability_flag: int,
) -> dict:
    """Returns {"risk_score": 0-1, "risk_bucket": LOW|MODERATE|HIGH, "component_scores": {...}}.

    component_scores exposes each weighted contribution so a clinician (or a caller building an
    explanation) can see exactly which signal(s) drove the score -- the interpretability that is
    the entire point of this being the primary model instead of the XGBoost one.
    """
    components = {
        "hr_rise": _hr_rise_component(hr_rise),
        "map_drop": _map_drop_component(map_drop),
        "co_drop_pct": _co_drop_pct_component(co_drop_pct),
        "compensation_flag": 1.0 if not compensation_flag else 0.0,
        "instability_flag": 1.0 if instability_flag else 0.0,
    }
    weighted_contributions = {k: components[k] * WEIGHTS[k] for k in WEIGHTS}
    risk_score = sum(weighted_contributions.values())

    if risk_score < LOW_HIGH_BOUNDARY:
        risk_bucket = "LOW"
    elif risk_score < MODERATE_HIGH_BOUNDARY:
        risk_bucket = "MODERATE"
    else:
        risk_bucket = "HIGH"

    return {
        "risk_score": round(risk_score, 4),
        "risk_bucket": risk_bucket,
        "component_scores": {k: round(v, 4) for k, v in weighted_contributions.items()},
    }
