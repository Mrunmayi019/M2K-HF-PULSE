"""Validation tests for the Phase 5 rule-based NYHA classifier (src/analytics/staging.py).

Pure-Python, no Docker/Pulse required.

Run from repo root: pytest tests/test_staging.py -v
"""
from src.analytics.staging import classify_nyha


class TestNoStructuralRisk:
    def test_normal_ef_and_bnp_is_class_i_even_with_high_risk_score(self):
        # No structural HF evidence -> Class I regardless of a (hypothetically) elevated score;
        # NYHA I is the "no structural basis for symptoms" floor in this design.
        result = classify_nyha(
            ejection_fraction_pct=60, nt_probnp_pg_ml=100, age=55, risk_score=0.9, instability_flag=0
        )
        assert result == "I"


class TestStructuralRiskPresent:
    def test_low_risk_score_with_reduced_ef_is_class_ii(self):
        result = classify_nyha(
            ejection_fraction_pct=35, nt_probnp_pg_ml=100, age=55, risk_score=0.1, instability_flag=0
        )
        assert result == "II"

    def test_moderate_risk_score_is_class_iii(self):
        result = classify_nyha(
            ejection_fraction_pct=35, nt_probnp_pg_ml=100, age=55, risk_score=0.5, instability_flag=0
        )
        assert result == "III"

    def test_high_risk_score_is_class_iv(self):
        result = classify_nyha(
            ejection_fraction_pct=35, nt_probnp_pg_ml=100, age=55, risk_score=0.9, instability_flag=0
        )
        assert result == "IV"

    def test_elevated_bnp_alone_triggers_structural_gate(self):
        # EF normal but NT-proBNP above the age-adjusted cutoff -> still gated in, not Class I
        result = classify_nyha(
            ejection_fraction_pct=60, nt_probnp_pg_ml=5000, age=55, risk_score=0.1, instability_flag=0
        )
        assert result != "I"

    def test_instability_flag_forces_class_iv_regardless_of_score(self):
        result = classify_nyha(
            ejection_fraction_pct=35, nt_probnp_pg_ml=100, age=55, risk_score=0.05, instability_flag=1
        )
        assert result == "IV"


class TestAgeAdjustedCutoff:
    def test_same_bnp_value_can_gate_differently_by_age(self):
        # 600 pg/mL is above the under-50 cutoff (450) but below the 50-75 cutoff (900)
        young = classify_nyha(
            ejection_fraction_pct=60, nt_probnp_pg_ml=600, age=35, risk_score=0.1, instability_flag=0
        )
        middle_aged = classify_nyha(
            ejection_fraction_pct=60, nt_probnp_pg_ml=600, age=60, risk_score=0.1, instability_flag=0
        )
        assert young != "I"
        assert middle_aged == "I"
