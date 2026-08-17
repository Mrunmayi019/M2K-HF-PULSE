"""Post-handoff: secondary benchmark comparator against a published clinical risk score
(MAGGIC), for HANDOFF.md P2 "benchmark against an established clinical risk score."

This is NOT a replacement for src/analytics/risk_score.py (still primary -- see its own module
docstring). It exists purely to show how this project's risk_score.py output compares to an
externally validated score computed on the same patients, per HANDOFF.md's explicit ask.

MAGGIC (Pocock SJ, et al. "Predicting survival in heart failure: a risk score based on 39,372
patients from 30 studies worldwide." Eur Heart J. 2013;34(19):1404-1413) is an integer point
score built from 13 routinely available clinical variables, developed on >39,000 real HF
patients. Provenance of the point table used below:
  - The age x ejection-fraction interaction bands were independently confirmed against the
    original paper by the repo owner (Kaveri Sharma) directly -- covers <55 through >=80, filling
    a gap this project's web-sourced secondary reference was missing at the >=80 end, which
    matters here given this project's real PerHeart validation cohort skews to ages 67-94
    (docs/real_world_data_integration.md).
  - Every other band (EF points, BMI, creatinine, SBP-by-EF, NYHA, and the binary risk factors)
    is reproduced from a secondary source (an MDApp.co MAGGIC-calculator writeup) that was NOT
    independently re-verified against the original paper's own supplementary table -- flagged
    here, not hidden, consistent with this project's citation discipline
    (docs/data_provenance.md). **Re-verify these against Pocock et al. 2013's supplementary table
    before citing this comparison in the paper.**

Inputs this project doesn't measure (systolic BP, serum creatinine, diabetes, COPD, smoking
status, HF-diagnosis duration, beta-blocker/ACEI-ARB use) are filled with fixed, documented
defaults -- see the ASSUMED_* constants below -- the same assumed_default pattern already used
throughout src/data_synthesis/reference_stats.yaml. Serum creatinine reuses this project's own
already-cited MIMIC-derived mean (reference_stats.yaml labs.serum_creatinine_mg_dl -- real data,
not invented); the rest have no real source in this project and are held at clinically
plausible, guideline-informed constants (see each constant's own comment).

Because every one of these fill-ins is a FIXED constant, not sampled per patient, they add the
same constant offset to every patient's MAGGIC score. That shifts the absolute point total (and,
since MAGGIC's risk tiers are absolute thresholds rather than percentiles, could shift which tier
a borderline patient falls in) -- but it does NOT affect rank-based agreement between MAGGIC and
risk_score.py across a cohort (Spearman correlation is invariant to a constant offset).
scripts/benchmark_comparison.py reports both a bucket-agreement view and a rank-correlation view
for exactly this reason.
"""
from __future__ import annotations

# ---- Fixed defaults for MAGGIC inputs this project doesn't measure ----

# Real, already-cited data (src/data_synthesis/reference_stats.yaml labs.serum_creatinine_mg_dl,
# status derived_from_dataset, source mimic_bigquery_extract): mean 1.82 mg/dL. Converted to
# umol/L (x88.4, standard clinical conversion factor) for MAGGIC's own units.
ASSUMED_SERUM_CREATININE_UMOL_L = 1.82 * 88.4  # ~160.9 umol/L

# fedesoriano_kaggle's RestingBP mean (132.4 mmHg -- see reference_stats.yaml's own comment on
# it), explicitly NOT reused elsewhere in this project for wearable-baseline generation (that
# comment's reasoning: it's a coronary-clinic cohort, not an at-home wearable user's resting
# baseline) -- but reused *here* because MAGGIC's own development population IS a diagnosed,
# in-clinic HF cohort, which is what this figure actually measures.
ASSUMED_SYSTOLIC_BP_MMHG = 132.4

# No source in this project for these six -- held at clinically plausible constants for an
# already-diagnosed, guideline-treated HF cohort (this project's synthetic patients all have an
# established EF/NT-proBNP workup, i.e. not new-onset): most such patients are on
# guideline-directed beta-blocker + ACEI/ARB therapy and were diagnosed >=18 months ago. To avoid
# stacking further unfounded comorbidity assumptions on top of an already-approximate score, no
# diabetes/COPD/current-smoking is assumed.
ASSUMED_DIABETES = False
ASSUMED_COPD = False
ASSUMED_CURRENT_SMOKER = False
ASSUMED_HF_DURATION_18MO_PLUS = True
ASSUMED_ON_BETA_BLOCKER = True
ASSUMED_ON_ACEI_ARB = True

_NYHA_POINTS = {"I": 0, "II": 2, "III": 6, "IV": 8}

# (upper bound exclusive, points) bands; age/value >= the last finite bound uses the last points.
_AGE_POINTS_BY_EF_CATEGORY = {
    "under_30": [(55, 0), (60, 1), (65, 2), (70, 4), (75, 6), (80, 8), (float("inf"), 10)],
    "30_to_39": [(55, 0), (60, 2), (65, 4), (70, 6), (75, 8), (80, 10), (float("inf"), 13)],
    "40_plus": [(55, 0), (60, 3), (65, 5), (70, 7), (75, 9), (80, 12), (float("inf"), 15)],
}

_SBP_POINTS_BY_EF_CATEGORY = {
    "under_30": [(110, 5), (120, 4), (130, 3), (140, 2), (150, 1), (float("inf"), 0)],
    "30_to_39": [(110, 3), (120, 2), (130, 1), (140, 1), (150, 0), (float("inf"), 0)],
    "40_plus": [(110, 2), (120, 1), (130, 1), (140, 0), (150, 0), (float("inf"), 0)],
}

_CREATININE_POINTS = [
    (90, 0), (110, 1), (130, 2), (150, 3), (170, 4), (210, 5), (250, 6), (float("inf"), 8),
]


def _band_lookup(value: float, bands: list[tuple[float, int]]) -> int:
    for upper_bound, points in bands:
        if value < upper_bound:
            return points
    return bands[-1][1]


def _ef_category(ef_pct: float) -> str:
    """The 3-way EF category the age/SBP interaction tables are banded on -- boundaries (30, 40)
    intentionally match the raw EF-points band edges below, so a patient's EF category is
    consistent between the two tables."""
    if ef_pct < 30:
        return "under_30"
    if ef_pct < 40:
        return "30_to_39"
    return "40_plus"


def _ef_points(ef_pct: float) -> int:
    if ef_pct < 20:
        return 7
    if ef_pct < 25:
        return 6
    if ef_pct < 30:
        return 5
    if ef_pct < 35:
        return 3
    if ef_pct < 40:
        return 2
    return 0


def _bmi_points(bmi: float) -> int:
    if bmi < 15:
        return 6
    if bmi < 20:
        return 5
    if bmi < 25:
        return 3
    if bmi < 30:
        return 2
    return 0


def compute_maggic_score(
    age: float,
    sex: str,
    ejection_fraction_pct: float,
    nyha_class: str,
    bmi: float,
    systolic_bp_mmhg: float = ASSUMED_SYSTOLIC_BP_MMHG,
    serum_creatinine_umol_l: float = ASSUMED_SERUM_CREATININE_UMOL_L,
    diabetes: bool = ASSUMED_DIABETES,
    copd: bool = ASSUMED_COPD,
    current_smoker: bool = ASSUMED_CURRENT_SMOKER,
    hf_duration_18mo_plus: bool = ASSUMED_HF_DURATION_18MO_PLUS,
    on_beta_blocker: bool = ASSUMED_ON_BETA_BLOCKER,
    on_acei_arb: bool = ASSUMED_ON_ACEI_ARB,
) -> dict:
    """Returns {"maggic_score": int, "component_points": {...}}.

    age/sex/ejection_fraction_pct/nyha_class/bmi are real per-patient fields already in this
    project's records; every other parameter defaults to the fixed ASSUMED_* constants above --
    see the module docstring for why, and what that does (and doesn't) affect in a comparison.
    """
    if nyha_class not in _NYHA_POINTS:
        raise ValueError(f"nyha_class must be one of {sorted(_NYHA_POINTS)}, got {nyha_class!r}")

    ef_category = _ef_category(ejection_fraction_pct)
    components = {
        "age": _band_lookup(age, _AGE_POINTS_BY_EF_CATEGORY[ef_category]),
        "ejection_fraction": _ef_points(ejection_fraction_pct),
        "nyha_class": _NYHA_POINTS[nyha_class],
        "bmi": _bmi_points(bmi),
        "systolic_bp": _band_lookup(systolic_bp_mmhg, _SBP_POINTS_BY_EF_CATEGORY[ef_category]),
        "creatinine": _band_lookup(serum_creatinine_umol_l, _CREATININE_POINTS),
        "male_sex": 1 if sex == "Male" else 0,
        "current_smoker": 1 if current_smoker else 0,
        "diabetes": 3 if diabetes else 0,
        "copd": 2 if copd else 0,
        "hf_duration_18mo_plus": 2 if hf_duration_18mo_plus else 0,
        "not_on_beta_blocker": 0 if on_beta_blocker else 3,
        "not_on_acei_arb": 0 if on_acei_arb else 1,
    }
    return {"maggic_score": sum(components.values()), "component_points": components}
