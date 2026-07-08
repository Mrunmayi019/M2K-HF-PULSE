"""Validation tests for the Phase 5 forward projection module (src/analytics/projection.py).

Only project_severity() is tested here -- pure math, no Docker/Pulse required.
project_physiology() actually invokes Pulse and can only be exercised inside the Docker container
(same convention as scripts/validate_phase2.py and Phase 4's batch runner).

Run from repo root: pytest tests/test_projection.py -v
"""
import pytest

from src.analytics.projection import project_severity


class TestProjectSeverity:
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
        assert project_severity(0.9, 0.5, 30) == 1.0

    def test_clamped_at_lower_bound(self):
        assert project_severity(0.1, -0.5, 30) == 0.0

    def test_exact_linear_extrapolation(self):
        assert project_severity(0.2, 0.02, 10) == pytest.approx(0.4)
