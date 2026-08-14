"""Validation tests for the Phase 5 primary hand-tuned risk score (src/analytics/risk_score.py).

Pure-Python, no Docker/Pulse required.

Run from repo root: pytest tests/test_risk_score.py -v
"""
import pytest

from src.analytics.risk_score import (
    ASSUMED_HEALTHY_MAP_MMHG,
    LOW_HIGH_BOUNDARY,
    MODERATE_HIGH_BOUNDARY,
    compute_risk_score,
)

# A healthy map_start that contributes ~0 to baseline_deficit_score, so these tests exercise only
# the acute-change path (the pre-existing 5-feature behavior) unless a test explicitly varies it.
HEALTHY_MAP_START = ASSUMED_HEALTHY_MAP_MMHG


class TestBoundaryCases:
    def test_all_benign_inputs_score_low(self):
        result = compute_risk_score(
            hr_rise=0, map_drop=0, co_drop_pct=-5, compensation_flag=1, instability_flag=0,
            map_start=HEALTHY_MAP_START,
        )
        assert result["risk_bucket"] == "LOW"
        assert result["risk_score"] < LOW_HIGH_BOUNDARY

    def test_all_severe_inputs_score_high(self):
        result = compute_risk_score(
            hr_rise=90, map_drop=30, co_drop_pct=40, compensation_flag=0, instability_flag=1,
            map_start=HEALTHY_MAP_START,
        )
        assert result["risk_bucket"] == "HIGH"
        assert result["risk_score"] >= MODERATE_HIGH_BOUNDARY

    def test_weights_sum_to_one(self):
        from src.analytics.risk_score import WEIGHTS
        assert sum(WEIGHTS.values()) == pytest.approx(1.0)

    def test_risk_score_bounded_zero_to_one(self):
        result = compute_risk_score(
            hr_rise=1000, map_drop=1000, co_drop_pct=1000, compensation_flag=0, instability_flag=1,
            map_start=HEALTHY_MAP_START,
        )
        assert 0.0 <= result["risk_score"] <= 1.0

    def test_congested_baseline_with_no_acute_change_scores_high(self):
        # The fluid_overload blind-spot fix: map_start already near the instability threshold,
        # nothing else moves during the encounter -- must not score near-zero anymore.
        result = compute_risk_score(
            hr_rise=0, map_drop=0, co_drop_pct=-10, compensation_flag=1, instability_flag=0,
            map_start=67.0,  # just above the 65mmHg instability threshold
        )
        assert result["dominant_mechanism"] == "baseline"
        assert result["risk_score"] >= MODERATE_HIGH_BOUNDARY

    def test_baseline_deficit_bounded_zero_to_one(self):
        result = compute_risk_score(
            hr_rise=0, map_drop=0, co_drop_pct=0, compensation_flag=1, instability_flag=0,
            map_start=-500,
        )
        assert 0.0 <= result["baseline_deficit_score"] <= 1.0
        assert 0.0 <= result["risk_score"] <= 1.0


class TestMonotonicity:
    def test_higher_hr_rise_never_decreases_score(self):
        low = compute_risk_score(10, 0, 0, 1, 0, HEALTHY_MAP_START)["risk_score"]
        high = compute_risk_score(60, 0, 0, 1, 0, HEALTHY_MAP_START)["risk_score"]
        assert high >= low

    def test_higher_map_drop_never_decreases_score(self):
        low = compute_risk_score(0, 2, 0, 1, 0, HEALTHY_MAP_START)["risk_score"]
        high = compute_risk_score(0, 25, 0, 1, 0, HEALTHY_MAP_START)["risk_score"]
        assert high >= low

    def test_higher_co_drop_pct_never_decreases_score(self):
        low = compute_risk_score(0, 0, 5, 1, 0, HEALTHY_MAP_START)["risk_score"]
        high = compute_risk_score(0, 0, 25, 1, 0, HEALTHY_MAP_START)["risk_score"]
        assert high >= low

    def test_co_rising_contributes_no_risk(self):
        # co_drop_pct negative means cardiac output rose (e.g. healthy compensation) -- should not
        # be penalized, i.e. clamped at the same floor as co_drop_pct=0.
        rising = compute_risk_score(0, 0, -50, 1, 0, HEALTHY_MAP_START)
        flat = compute_risk_score(0, 0, 0, 1, 0, HEALTHY_MAP_START)
        assert rising["risk_score"] == flat["risk_score"]

    def test_failed_compensation_increases_score(self):
        compensated = compute_risk_score(20, 5, 5, 1, 0, HEALTHY_MAP_START)["risk_score"]
        uncompensated = compute_risk_score(20, 5, 5, 0, 0, HEALTHY_MAP_START)["risk_score"]
        assert uncompensated > compensated

    def test_instability_flag_increases_score(self):
        stable = compute_risk_score(20, 5, 5, 1, 0, HEALTHY_MAP_START)["risk_score"]
        unstable = compute_risk_score(20, 5, 5, 1, 1, HEALTHY_MAP_START)["risk_score"]
        assert unstable > stable

    def test_lower_map_start_never_decreases_score(self):
        higher_baseline = compute_risk_score(0, 0, 0, 1, 0, map_start=90.0)["risk_score"]
        lower_baseline = compute_risk_score(0, 0, 0, 1, 0, map_start=60.0)["risk_score"]
        assert lower_baseline >= higher_baseline


class TestComponentScores:
    def test_component_scores_sum_to_acute_score(self):
        # component_scores is the acute (within-encounter) sub-score only; risk_score itself is
        # max(acute_score, baseline_deficit_score), see TestBaselineDeficit below.
        result = compute_risk_score(30, 10, 15, 0, 1, HEALTHY_MAP_START)
        assert sum(result["component_scores"].values()) == pytest.approx(result["acute_score"])

    def test_component_scores_have_all_five_keys(self):
        result = compute_risk_score(0, 0, 0, 1, 0, HEALTHY_MAP_START)
        assert set(result["component_scores"].keys()) == {
            "hr_rise", "map_drop", "co_drop_pct", "compensation_flag", "instability_flag",
        }


class TestBaselineDeficit:
    def test_risk_score_is_max_of_acute_and_baseline(self):
        result = compute_risk_score(30, 10, 15, 0, 1, map_start=67.0)
        assert result["risk_score"] == pytest.approx(
            max(result["acute_score"], result["baseline_deficit_score"])
        )

    def test_healthy_baseline_contributes_zero(self):
        result = compute_risk_score(0, 0, 0, 1, 0, map_start=ASSUMED_HEALTHY_MAP_MMHG)
        assert result["baseline_deficit_score"] == 0.0

    def test_dominant_mechanism_matches_the_larger_sub_score(self):
        acute_dominant = compute_risk_score(90, 30, 40, 0, 1, map_start=HEALTHY_MAP_START)
        assert acute_dominant["dominant_mechanism"] == "acute"

        baseline_dominant = compute_risk_score(0, 0, -10, 1, 0, map_start=60.0)
        assert baseline_dominant["dominant_mechanism"] == "baseline"
