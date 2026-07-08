"""Phase 5: rule-based NYHA functional classifier.

Two-step classification, matching how the planning PDF's own summary of the ACC/AHA Stages and
NYHA Functional Classification describes them working together (pages 99-101): the ACC/AHA
Stage B structural/biomarker criteria (LVEF<=40%, or NT-proBNP above the age-adjusted cutoff --
both already established in reference_stats.yaml/data_provenance.md) gate whether a patient has
any heart-failure structural basis for symptoms at all; the Pulse-simulated response to exertion
(this system's proxy for the METs-based symptom-provocation the real NYHA classification uses)
then places a structurally-at-risk patient in NYHA I-IV, reusing risk_score.py's own LOW/MODERATE/
HIGH boundaries so the two live on one consistent scale rather than a second set of magic numbers.

Citations: AHA/ACC 2022 Guideline (LVEF<=40% / NT-proBNP Stage B criteria, already in
data_provenance.md); NYHA Functional Classification, New York Heart Association.
"""
from __future__ import annotations

from src.analytics.risk_score import LOW_HIGH_BOUNDARY, MODERATE_HIGH_BOUNDARY
from src.data_synthesis.generate_patients import load_reference_stats

HFREF_EF_THRESHOLD_PCT = 40.0  # AHA/ACC 2022 Stage B structural criterion


def _nt_probnp_cutoff_for_age(age: float) -> float:
    cutoffs = load_reference_stats()["nt_probnp_cutoff_pg_ml"]
    if age < 50:
        return cutoffs["under_50"]
    if age <= 75:
        return cutoffs["50_to_75"]
    return cutoffs["over_75"]


def classify_nyha(
    ejection_fraction_pct: float,
    nt_probnp_pg_ml: float,
    age: float,
    risk_score: float,
    instability_flag: int,
) -> str:
    """Returns "I", "II", "III", or "IV"."""
    has_structural_risk = (
        ejection_fraction_pct <= HFREF_EF_THRESHOLD_PCT
        or nt_probnp_pg_ml > _nt_probnp_cutoff_for_age(age)
    )

    if not has_structural_risk:
        return "I"

    # Symptoms present even at rest (shock-range MAP under simulated exertion) -> most severe rung,
    # regardless of where the continuous risk_score otherwise lands.
    if instability_flag:
        return "IV"

    if risk_score < LOW_HIGH_BOUNDARY:
        return "II"
    if risk_score < MODERATE_HIGH_BOUNDARY:
        return "III"
    return "IV"
