"""Unit tests for the MAGGIC risk score (src/analytics/benchmark_scores.py::compute_maggic_score),
hand-verified against the published point system (Pocock SJ, et al. "Predicting survival in heart
failure: a risk score based on 39 372 patients from 30 studies worldwide." Eur Heart J.
2013;34(19):1404-1413).

Every band value asserted below was independently cross-checked (2026-09-24, this session) against
external sources synthesizing the original paper's Table 3 (MDApp.co, AppCardio, Johnson Francis's
clinical review), not just the single secondary source src/analytics/benchmark_scores.py's own
docstring originally flagged as unverified:
  - SBP<110 (reduced-EF band) = 5 pts; SBP>=150 = 0 pts -- confirmed
  - Creatinine band edges 90/110/130/150/170/210/250 umol/L, >250 = 8 pts -- confirmed
  - Age max points = 15 (EF>=40 category, oldest band) -- confirmed
  - NYHA I/II/III/IV = 0/2/6/8 -- confirmed
  - EF<20% = 7 pts -- confirmed
  - BMI<15 = 6 pts, BMI>=30 = 0 pts -- confirmed
  - male sex=1, current smoker=1, diabetes=3, COPD=2, HF>=18mo=2, not on beta-blocker=3,
    not on ACEI/ARB=1 -- all confirmed

Each test hand-calculates the expected point total (and every component) from the published bands
BEFORE calling the production function, then asserts the production function matches -- this is an
independently-calculated-expected-result test, the same pattern as
tests/test_simulation_features.py's PV-loop/ECG tests, not a property/invariant check.

Run from repo root: pytest tests/test_maggic_score.py -v
"""
from src.analytics.benchmark_scores import compute_maggic_score


class TestLowRiskProfile:
    """Age=45 (<55, EF>=40 category) -> 0. EF=55% (>=40) -> 0. NYHA I -> 0. BMI=24 (<25) -> 3.
    SBP=140 (EF>=40 category, 140<150) -> 0. Creatinine=80 (<90) -> 0. Female -> 0. Non-smoker -> 0.
    Non-diabetic -> 0. No COPD -> 0. HF diagnosed <18mo -> 0. On beta-blocker -> 0. On ACEI/ARB -> 0.
    Hand-calculated total: 3.
    """

    def test_low_risk_patient_matches_hand_calculation(self):
        result = compute_maggic_score(
            age=45, sex="Female", ejection_fraction_pct=55, nyha_class="I", bmi=24,
            systolic_bp_mmhg=140, serum_creatinine_umol_l=80,
            diabetes=False, copd=False, current_smoker=False,
            hf_duration_18mo_plus=False, on_beta_blocker=True, on_acei_arb=True,
        )
        expected_components = {
            "age": 0, "ejection_fraction": 0, "nyha_class": 0, "bmi": 3, "systolic_bp": 0,
            "creatinine": 0, "male_sex": 0, "current_smoker": 0, "diabetes": 0, "copd": 0,
            "hf_duration_18mo_plus": 0, "not_on_beta_blocker": 0, "not_on_acei_arb": 0,
        }
        assert result["component_points"] == expected_components
        assert result["maggic_score"] == 3


class TestHighRiskProfile:
    """Age=82 (EF<30 category, oldest band) -> 10. EF=18% (<20) -> 7. NYHA IV -> 8. BMI=19 (<20)
    -> 5. SBP=95 (EF<30 category, <110) -> 5. Creatinine=260 (>250) -> 8. Male -> 1. Current
    smoker -> 1. Diabetic -> 3. COPD -> 2. HF diagnosed >=18mo -> 2. Not on beta-blocker -> 3.
    Not on ACEI/ARB -> 1.
    Hand-calculated total: 10+7+8+5+5+8+1+1+3+2+2+3+1 = 56.

    Note: 56 exceeds the ~50-52 range commonly cited by secondary sources for MAGGIC's published
    points-to-mortality lookup table -- this is expected, not a bug: that lookup table only tabulates
    scores actually observed in the 39,372-patient derivation cohort, it is not a mathematical cap
    on the point-summation formula itself, which this test verifies in isolation from any
    probability conversion (compute_maggic_score returns points only, never a mortality percentage).
    """

    def test_high_risk_patient_matches_hand_calculation(self):
        result = compute_maggic_score(
            age=82, sex="Male", ejection_fraction_pct=18, nyha_class="IV", bmi=19,
            systolic_bp_mmhg=95, serum_creatinine_umol_l=260,
            diabetes=True, copd=True, current_smoker=True,
            hf_duration_18mo_plus=True, on_beta_blocker=False, on_acei_arb=False,
        )
        expected_components = {
            "age": 10, "ejection_fraction": 7, "nyha_class": 8, "bmi": 5, "systolic_bp": 5,
            "creatinine": 8, "male_sex": 1, "current_smoker": 1, "diabetes": 3, "copd": 2,
            "hf_duration_18mo_plus": 2, "not_on_beta_blocker": 3, "not_on_acei_arb": 1,
        }
        assert result["component_points"] == expected_components
        assert result["maggic_score"] == 56


class TestModerateRiskProfile:
    """Age=68 (EF 30-39 category, <70 band) -> 6. EF=32% (<35) -> 3. NYHA III -> 6. BMI=27 (<30)
    -> 2. SBP=125 (EF 30-39 category, <130) -> 1. Creatinine=115 (<130) -> 2. Male -> 1.
    Non-smoker -> 0. Non-diabetic -> 0. No COPD -> 0. HF diagnosed >=18mo -> 2. On beta-blocker
    -> 0. Not on ACEI/ARB -> 1.
    Hand-calculated total: 6+3+6+2+1+2+1+0+0+0+2+0+1 = 24.
    """

    def test_moderate_risk_patient_matches_hand_calculation(self):
        result = compute_maggic_score(
            age=68, sex="Male", ejection_fraction_pct=32, nyha_class="III", bmi=27,
            systolic_bp_mmhg=125, serum_creatinine_umol_l=115,
            diabetes=False, copd=False, current_smoker=False,
            hf_duration_18mo_plus=True, on_beta_blocker=True, on_acei_arb=False,
        )
        expected_components = {
            "age": 6, "ejection_fraction": 3, "nyha_class": 6, "bmi": 2, "systolic_bp": 1,
            "creatinine": 2, "male_sex": 1, "current_smoker": 0, "diabetes": 0, "copd": 0,
            "hf_duration_18mo_plus": 2, "not_on_beta_blocker": 0, "not_on_acei_arb": 1,
        }
        assert result["component_points"] == expected_components
        assert result["maggic_score"] == 24


class TestInvalidInput:
    def test_unknown_nyha_class_raises(self):
        import pytest
        with pytest.raises(ValueError):
            compute_maggic_score(age=60, sex="Male", ejection_fraction_pct=40, nyha_class="V", bmi=25)
