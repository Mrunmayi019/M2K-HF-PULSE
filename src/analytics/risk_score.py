"""Phase 5, primary risk scorer: a hand-tuned, interpretable weighted score.

Per the locked decision in CLAUDE.md ("Risk scorer"), this -- not the secondary/experimental
XGBoost model in src/ml_models/train_risk_scorer.py -- is the system's primary risk output. Every
component's normalization anchor and every weight is documented here and in
docs/data_provenance.md; weights themselves are clinically *motivated*, not statistically fit to
data (there isn't enough data to fit them defensibly -- see model_card.md for why that reasoning
applies even harder to the secondary model).

Inputs are the 5 features src/analytics/simulation_features.py extracts from one Pulse run
(hr_rise, map_drop, co_drop_pct, compensation_flag, instability_flag) plus map_start, added to fix
a documented blind spot -- see "Baseline-deviation term" below.

Baseline-deviation term (fluid_overload blind-spot fix, PUBLICATION_TODO.md P2): the original 5
acute-change features only capture hemodynamic *change during* one simulated encounter, so a
patient whose danger is an already-abnormal resting baseline that stays roughly flat during the
encounter -- exactly fluid_overload's presentation (map_start ~77-79mmHg vs. a healthy ~90-95mmHg,
per docs/methodology.md Sec 6.1/Sec 4's Phase 2 table) -- scored a constant near-zero risk
regardless of true severity, confirmed empirically on 30/30 real fluid_overload runs
(models/model_card.md). `analyze_simulation()` already computed `map_start` for every run; it was
simply never passed to this function. Fix: a second sub-score, `baseline_deficit_score`, evaluates
how congested `map_start` already is (same NEWS2-style anchors as `map_drop`: healthy ~92.5mmHg
down to the MAP<65 instability threshold), and the final `risk_score` is
`max(acute_score, baseline_deficit_score)` -- not a reweighted blend. This is a deliberate design
choice: risk is driven by whichever mechanism (acute decompensation *or* chronic-baseline
congestion) is worse, and max() leaves the existing 5 acute weights and their citations completely
unchanged rather than diluting them to make room for a 6th term.
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


def _baseline_deficit_component(map_start: float) -> float:
    """How congested map_start already is, independent of anything that happens *during* the
    encounter -- the fluid_overload blind-spot fix (see module docstring). Same anchors as
    map_drop: 0 at the healthy baseline (~92.5mmHg), 1 at or below the MAP<65 instability
    threshold. A patient whose resting MAP is already near-shock-range scores high here even if it
    barely moves during the simulated window.
    """
    return max(0.0, min((ASSUMED_HEALTHY_MAP_MMHG - map_start) / _MAP_DROP_FULL_SCALE, 1.0))


def compute_risk_score(
    hr_rise: float,
    map_drop: float,
    co_drop_pct: float,
    compensation_flag: int,
    instability_flag: int,
    map_start: float,
) -> dict:
    """Returns {"risk_score": 0-1, "risk_bucket": LOW|MODERATE|HIGH, "component_scores": {...},
    "acute_score": 0-1, "baseline_deficit_score": 0-1, "dominant_mechanism": "acute"|"baseline"}.

    component_scores exposes each weighted contribution to the *acute* sub-score so a clinician
    (or a caller building an explanation) can see exactly which signal(s) drove it -- the
    interpretability that is the entire point of this being the primary model instead of the
    XGBoost one. risk_score = max(acute_score, baseline_deficit_score) -- see module docstring for
    why this is max(), not a blend.
    """
    components = {
        "hr_rise": _hr_rise_component(hr_rise),
        "map_drop": _map_drop_component(map_drop),
        "co_drop_pct": _co_drop_pct_component(co_drop_pct),
        "compensation_flag": 1.0 if not compensation_flag else 0.0,
        "instability_flag": 1.0 if instability_flag else 0.0,
    }
    weighted_contributions = {k: components[k] * WEIGHTS[k] for k in WEIGHTS}
    acute_score = sum(weighted_contributions.values())
    baseline_deficit_score = _baseline_deficit_component(map_start)
    risk_score = max(acute_score, baseline_deficit_score)

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
        "acute_score": round(acute_score, 4),
        "baseline_deficit_score": round(baseline_deficit_score, 4),
        "dominant_mechanism": "acute" if acute_score >= baseline_deficit_score else "baseline",
    }
