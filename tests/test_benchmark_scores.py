"""Validation tests for the MAGGIC benchmark comparator (src/analytics/benchmark_scores.py).

Pure-Python, no Docker/Pulse required.

Run from repo root: pytest tests/test_benchmark_scores.py -v
"""
import pytest

from src.analytics.benchmark_scores import compute_maggic_score


class TestKnownExample:
    def test_hand_computed_example_matches(self):
        """age=68/EF=35/NYHA III/BMI=28/Male, all other inputs at their documented assumed
        defaults -- hand-computed against the module's own band tables (see PR/commit for the
        by-hand arithmetic): age=6, ef=2, nyha=6, bmi=2, sbp=1, creatinine=4, male=1,
        hf_duration=2, everything else 0 -> total 24."""
        result = compute_maggic_score(
            age=68, sex="Male", ejection_fraction_pct=35, nyha_class="III", bmi=28,
        )
        assert result["maggic_score"] == 24
        assert result["component_points"] == {
            "age": 6,
            "ejection_fraction": 2,
            "nyha_class": 6,
            "bmi": 2,
            "systolic_bp": 1,
            "creatinine": 4,
            "male_sex": 1,
            "current_smoker": 0,
            "diabetes": 0,
            "copd": 0,
            "hf_duration_18mo_plus": 2,
            "not_on_beta_blocker": 0,
            "not_on_acei_arb": 0,
        }


class TestComponentSum:
    def test_component_points_sum_to_total(self):
        result = compute_maggic_score(
            age=74, sex="Female", ejection_fraction_pct=22, nyha_class="IV", bmi=19,
        )
        assert sum(result["component_points"].values()) == result["maggic_score"]


class TestBoundaryCases:
    def test_ef_below_20_scores_max_ef_points(self):
        result = compute_maggic_score(age=50, sex="Female", ejection_fraction_pct=15, nyha_class="I", bmi=25)
        assert result["component_points"]["ejection_fraction"] == 7

    def test_ef_40_or_above_scores_zero_ef_points(self):
        result = compute_maggic_score(age=50, sex="Female", ejection_fraction_pct=60, nyha_class="I", bmi=25)
        assert result["component_points"]["ejection_fraction"] == 0

    def test_nyha_class_i_scores_zero(self):
        result = compute_maggic_score(age=50, sex="Female", ejection_fraction_pct=45, nyha_class="I", bmi=25)
        assert result["component_points"]["nyha_class"] == 0

    def test_nyha_class_iv_scores_eight(self):
        result = compute_maggic_score(age=50, sex="Female", ejection_fraction_pct=45, nyha_class="IV", bmi=25)
        assert result["component_points"]["nyha_class"] == 8

    def test_invalid_nyha_class_raises(self):
        with pytest.raises(ValueError):
            compute_maggic_score(age=50, sex="Female", ejection_fraction_pct=45, nyha_class="V", bmi=25)

    def test_under_55_scores_zero_age_points_regardless_of_ef(self):
        for ef in (15, 35, 60):
            result = compute_maggic_score(age=40, sex="Male", ejection_fraction_pct=ef, nyha_class="I", bmi=25)
            assert result["component_points"]["age"] == 0


class TestEfCategoryInteraction:
    def test_age_points_differ_across_the_ef_30_boundary(self):
        """Same age, EF just below vs. at the under_30/30_to_39 boundary -- the age-points table
        used should differ (this is MAGGIC's real age x EF interaction, not a bug)."""
        below = compute_maggic_score(age=62, sex="Male", ejection_fraction_pct=29, nyha_class="I", bmi=25)
        at_or_above = compute_maggic_score(age=62, sex="Male", ejection_fraction_pct=30, nyha_class="I", bmi=25)
        assert below["component_points"]["age"] != at_or_above["component_points"]["age"]


class TestMonotonicity:
    def test_older_age_never_scores_fewer_points_within_same_ef_category(self):
        younger = compute_maggic_score(age=56, sex="Male", ejection_fraction_pct=45, nyha_class="I", bmi=25)
        older = compute_maggic_score(age=82, sex="Male", ejection_fraction_pct=45, nyha_class="I", bmi=25)
        assert older["component_points"]["age"] >= younger["component_points"]["age"]

    def test_male_scores_at_least_as_high_as_otherwise_identical_female(self):
        female = compute_maggic_score(age=60, sex="Female", ejection_fraction_pct=45, nyha_class="II", bmi=25)
        male = compute_maggic_score(age=60, sex="Male", ejection_fraction_pct=45, nyha_class="II", bmi=25)
        assert male["maggic_score"] == female["maggic_score"] + 1


class TestAssumedDefaultOverrides:
    def test_not_on_beta_blocker_adds_three_points(self):
        on = compute_maggic_score(age=60, sex="Male", ejection_fraction_pct=35, nyha_class="II", bmi=25, on_beta_blocker=True)
        off = compute_maggic_score(age=60, sex="Male", ejection_fraction_pct=35, nyha_class="II", bmi=25, on_beta_blocker=False)
        assert off["maggic_score"] == on["maggic_score"] + 3

    def test_diabetes_adds_three_points(self):
        without = compute_maggic_score(age=60, sex="Male", ejection_fraction_pct=35, nyha_class="II", bmi=25, diabetes=False)
        with_ = compute_maggic_score(age=60, sex="Male", ejection_fraction_pct=35, nyha_class="II", bmi=25, diabetes=True)
        assert with_["maggic_score"] == without["maggic_score"] + 3
