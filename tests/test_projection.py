"""Validation tests for the Phase 5 forward projection module (src/analytics/projection.py).

Only project_severity() is tested here -- pure math, no Docker/Pulse required.
project_physiology() actually invokes Pulse and can only be exercised inside the Docker container
(same convention as scripts/validate_phase2.py and Phase 4's batch runner).

Run from repo root: pytest tests/test_projection.py -v
"""
import pytest

from src.analytics.deterioration_rate import SD_RATE_TO_SEVERITY_PER_DAY
from src.analytics.projection import project_severity


class TestProjectSeverity:
    """project_severity()'s second parameter is `composite_rate`: the raw, scale-agnostic
    population-SD-equivalents/day rate from compute_deterioration_rate() -- NOT a pre-converted
    risk_score-scale rate (that conflation was the bug fixed 2026-09-10, docs/methodology.md
    Sec 8). The function converts internally via SD_RATE_TO_SEVERITY_PER_DAY."""

    def test_zero_rate_holds_steady(self):
        assert project_severity(0.3, 0.0, 30) == pytest.approx(0.3)

    def test_positive_rate_increases_severity(self):
        result = project_severity(0.3, 0.01, 30)
        assert result > 0.3

    def test_negative_rate_decreases_severity(self):
        result = project_severity(0.3, -0.01, 30)
        assert result < 0.3

    def test_longer_horizon_moves_further_in_same_direction(self):
        near = project_severity(0.3, 0.01, 7)
        far = project_severity(0.3, 0.01, 30)
        assert far > near

    def test_clamped_at_upper_bound(self):
        assert project_severity(0.9, 5.0, 30) == 1.0

    def test_clamped_at_lower_bound(self):
        assert project_severity(0.1, -5.0, 30) == 0.0

    def test_exact_linear_extrapolation(self):
        # composite_rate=0.02 -> severity_rate_per_day = 0.02 * SD_RATE_TO_SEVERITY_PER_DAY (0.05)
        # = 0.001/day -> over 10 days: 0.2 + 0.01 = 0.21. (Previously this test asserted 0.4,
        # which only held under the pre-fix behavior of applying `composite_rate` directly with
        # no conversion -- that was the bug, not a spec this test should keep enforcing.)
        expected = 0.2 + (0.02 * SD_RATE_TO_SEVERITY_PER_DAY) * 10
        assert project_severity(0.2, 0.02, 10) == pytest.approx(expected)
        assert project_severity(0.2, 0.02, 10) == pytest.approx(0.21)


class TestSeverityRiskScoreScaleIndependence:
    """Regression coverage for the scale-mismatch bug fixed 2026-09-10 (docs/methodology.md
    Sec 8): project_severity() must be wired to SD_RATE_TO_SEVERITY_PER_DAY only, and moving
    SD_RATE_TO_RISK_SCORE_PER_DAY in isolation must have zero effect on it -- proven by actually
    changing each constant independently and observing the real behavioral consequence, not by
    comparing today's coincidentally-equal numeric values."""

    def test_project_severity_tracks_its_own_constant(self, monkeypatch):
        import src.analytics.projection as projection_module

        monkeypatch.setattr(projection_module, "SD_RATE_TO_SEVERITY_PER_DAY", 0.20)
        result = project_severity(0.3, 0.10, horizon_days=10)
        # 0.3 + (0.10 * 0.20) * 10 = 0.3 + 0.2 = 0.5
        assert result == pytest.approx(0.5)

    def test_project_severity_is_unaffected_by_the_risk_score_constant(self, monkeypatch):
        import src.analytics.projection as projection_module

        baseline = project_severity(0.3, 0.10, horizon_days=10)
        # project_severity() has no reference to SD_RATE_TO_RISK_SCORE_PER_DAY at all -- patching
        # it on the *deterioration_rate* module (where it actually lives) must change nothing
        # about project_severity()'s output.
        monkeypatch.setattr(
            "src.analytics.deterioration_rate.SD_RATE_TO_RISK_SCORE_PER_DAY", 999.0
        )
        after = project_severity(0.3, 0.10, horizon_days=10)
        assert after == pytest.approx(baseline)

    def test_project_severity_signature_takes_raw_composite_rate(self):
        # The old signature's second parameter was a pre-converted "deterioration_rate_per_day".
        # The fixed signature takes the raw composite_rate and converts internally -- this test
        # locks in that project_severity's own conversion is what determines the outcome, not
        # whatever the caller happened to pre-multiply by.
        import inspect

        params = list(inspect.signature(project_severity).parameters)
        assert params[1] == "composite_rate", (
            "project_severity()'s 2nd parameter must be named composite_rate (raw, scale-agnostic) "
            "-- renaming it back to a pre-converted 'deterioration_rate_per_day' would reintroduce "
            "the risk of a caller pre-converting with the wrong (risk_score) constant."
        )
