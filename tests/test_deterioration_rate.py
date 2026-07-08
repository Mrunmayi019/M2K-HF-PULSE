"""Validation tests for the Phase 5 deterioration rate calculator
(src/analytics/deterioration_rate.py).

Pure-Python, no Docker/Pulse required.

Run from repo root: pytest tests/test_deterioration_rate.py -v
"""
import numpy as np
import pandas as pd
import pytest

from src.analytics.deterioration_rate import compute_deterioration_rate, days_to_next_stage


def _make_trend(days=21, hr_start=70, hr_end=70, weight_start=75, weight_end=75):
    day = np.arange(days)
    hr = np.linspace(hr_start, hr_end, days)
    weight = np.linspace(weight_start, weight_end, days)
    return pd.DataFrame(
        {
            "day": day,
            "resting_hr_bpm": hr,
            "spo2_pct": np.full(days, 97.0),
            "weight_kg": weight,
            "steps_per_day": np.full(days, 6000.0),
            "sleep_hours": np.full(days, 7.0),
            "hrv_rmssd_ms": np.full(days, 35.0),
        }
    )


class TestComputeDeteriorationRate:
    def test_returns_expected_keys(self):
        result = compute_deterioration_rate(_make_trend())
        assert set(result.keys()) == {"vital_slopes", "normalized_rates", "composite_rate", "direction"}
        assert set(result["vital_slopes"].keys()) == {
            "resting_hr_bpm", "spo2_pct", "weight_kg", "steps_per_day", "sleep_hours", "hrv_rmssd_ms",
        }

    def test_flat_trend_is_stable(self):
        result = compute_deterioration_rate(_make_trend())
        assert result["direction"] == "stable"
        assert result["composite_rate"] == pytest.approx(0, abs=1e-9)

    def test_rising_hr_and_weight_is_worsening(self):
        result = compute_deterioration_rate(_make_trend(hr_start=70, hr_end=110, weight_start=75, weight_end=80))
        assert result["direction"] == "worsening"
        assert result["composite_rate"] > 0

    def test_falling_hr_is_improving(self):
        # A falling HR alone (nothing else moving) should read as improving, not worsening --
        # confirms the sign convention is applied correctly, not just magnitude.
        result = compute_deterioration_rate(_make_trend(hr_start=90, hr_end=70))
        assert result["normalized_rates"]["resting_hr_bpm"] < 0

    def test_normalized_rate_sign_matches_worsening_direction_for_spo2(self):
        days = 21
        trend = _make_trend()
        trend["spo2_pct"] = np.linspace(97, 90, days)  # falling SpO2 = worsening
        result = compute_deterioration_rate(trend)
        assert result["normalized_rates"]["spo2_pct"] > 0


class TestDaysToNextStage:
    def test_improving_trend_returns_none(self):
        assert days_to_next_stage(current_risk_score=0.5, composite_rate=-0.5) is None

    def test_flat_trend_returns_none(self):
        assert days_to_next_stage(current_risk_score=0.5, composite_rate=0.0) is None

    def test_already_high_returns_none(self):
        assert days_to_next_stage(current_risk_score=0.9, composite_rate=0.5) is None

    def test_worsening_trend_from_low_returns_positive_days(self):
        result = days_to_next_stage(current_risk_score=0.1, composite_rate=0.5)
        assert result is not None
        assert result > 0

    def test_faster_worsening_gives_fewer_days(self):
        slow = days_to_next_stage(current_risk_score=0.1, composite_rate=0.2)
        fast = days_to_next_stage(current_risk_score=0.1, composite_rate=1.0)
        assert fast < slow
