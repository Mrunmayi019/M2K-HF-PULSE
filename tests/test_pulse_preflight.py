"""Tests for src/pulse_runner/runner.py's Sprint 2 crash-zone pre-flight guardrail
(is_known_unstable_configuration, run_pulse_with_preflight). Pure Python + mocked run_pulse --
no Docker required.

Run from repo root: pytest tests/test_pulse_preflight.py -v
"""
from unittest.mock import patch

import pandas as pd
import pytest

from src.analytics.score_reporting import determine_simulation_status
from src.pulse_runner.runner import (
    ACUTE_DETERIORATION_CRASH_RANGE,
    PulseExecutionError,
    is_known_unstable_configuration,
    run_pulse_with_preflight,
)


class TestIsKnownUnstableConfiguration:
    def test_below_crash_range_is_stable(self):
        assert is_known_unstable_configuration("acute_deterioration", 0.5) is False

    def test_above_crash_range_is_stable(self):
        assert is_known_unstable_configuration("acute_deterioration", 0.9) is False

    def test_inside_crash_range_is_unstable(self):
        assert is_known_unstable_configuration("acute_deterioration", 0.7) is True

    def test_lower_boundary_is_inclusive(self):
        assert is_known_unstable_configuration("acute_deterioration", ACUTE_DETERIORATION_CRASH_RANGE[0]) is True

    def test_upper_boundary_is_inclusive(self):
        assert is_known_unstable_configuration("acute_deterioration", ACUTE_DETERIORATION_CRASH_RANGE[1]) is True

    def test_other_scenario_types_never_flagged(self):
        # Only acute_deterioration is characterized -- other types return False (not "confirmed
        # stable", just not audited for this guardrail), see the function's own docstring.
        for scenario_type in ("stable", "fluid_overload", "cardiac_stress", "deconditioning"):
            assert is_known_unstable_configuration(scenario_type, 0.7) is False


class TestRunPulseWithPreflight:
    def _fake_df(self):
        return pd.DataFrame({"Time(s)": [0, 600], "HeartRate(1/min)": [70, 70]})

    def test_outside_crash_zone_runs_normally_no_warning(self, recwarn):
        with patch("src.pulse_runner.runner.run_pulse", return_value=self._fake_df()):
            result = run_pulse_with_preflight("scenario.json", "acute_deterioration", 0.3, expected_duration_s=600)

        assert result["pulse_attempted"] is True
        assert result["pulse_succeeded"] is True
        assert result["flagged_unstable"] is False
        assert result["error"] is None
        assert not any(issubclass(w.category, RuntimeWarning) for w in recwarn.list)

    def test_inside_crash_zone_warns_but_still_runs_by_default(self):
        with patch("src.pulse_runner.runner.run_pulse", return_value=self._fake_df()):
            with pytest.warns(RuntimeWarning, match="known-unstable"):
                result = run_pulse_with_preflight("scenario.json", "acute_deterioration", 0.7, expected_duration_s=600)

        # Never silently skips a run the caller expected: still ran, still succeeded.
        assert result["pulse_attempted"] is True
        assert result["pulse_succeeded"] is True
        assert result["flagged_unstable"] is True

    def test_a_lucky_success_in_the_crash_zone_is_still_flagged_unstable(self):
        # The whole point: succeeding doesn't erase the flag. A "lucky" pass at severity 0.65 is
        # still not a reliable data point (docs/synthetic_deterioration_stress_test.md: 4/8
        # failures observed in exactly this zone).
        with patch("src.pulse_runner.runner.run_pulse", return_value=self._fake_df()):
            with pytest.warns(RuntimeWarning):
                result = run_pulse_with_preflight("scenario.json", "acute_deterioration", 0.65, expected_duration_s=600)
        assert result["pulse_succeeded"] is True
        assert result["flagged_unstable"] is True

    def test_skip_if_unstable_explicitly_skips_without_running(self):
        with patch("src.pulse_runner.runner.run_pulse") as mock_run:
            with pytest.warns(RuntimeWarning):
                result = run_pulse_with_preflight(
                    "scenario.json", "acute_deterioration", 0.7, expected_duration_s=600, skip_if_unstable=True
                )
            mock_run.assert_not_called()

        assert result["pulse_attempted"] is False
        assert result["pulse_succeeded"] is False
        assert result["flagged_unstable"] is True
        assert "skipped" in result["error"]

    def test_skip_if_unstable_does_not_affect_stable_configurations(self):
        # skip_if_unstable=True must not skip runs OUTSIDE the crash zone -- only flagged ones.
        with patch("src.pulse_runner.runner.run_pulse", return_value=self._fake_df()) as mock_run:
            result = run_pulse_with_preflight(
                "scenario.json", "acute_deterioration", 0.3, expected_duration_s=600, skip_if_unstable=True
            )
            mock_run.assert_called_once()
        assert result["pulse_attempted"] is True
        assert result["pulse_succeeded"] is True

    def test_pulse_failure_is_reported_not_raised(self):
        with patch("src.pulse_runner.runner.run_pulse", side_effect=PulseExecutionError("boom")):
            result = run_pulse_with_preflight("scenario.json", "acute_deterioration", 0.3, expected_duration_s=600)
        assert result["pulse_attempted"] is True
        assert result["pulse_succeeded"] is False
        assert result["df"] is None
        assert "boom" in result["error"]

    def test_failure_inside_crash_zone_is_flagged_and_failed(self):
        with patch("src.pulse_runner.runner.run_pulse", side_effect=PulseExecutionError("crashed")):
            with pytest.warns(RuntimeWarning):
                result = run_pulse_with_preflight("scenario.json", "acute_deterioration", 0.7, expected_duration_s=600)
        assert result["pulse_succeeded"] is False
        assert result["flagged_unstable"] is True


class TestLuckySuccessInsideCrashZone:
    """Sprint 2 closing check: a run that lands inside the documented 0.6-0.85 crash zone but
    SUCCEEDS anyway (a "lucky" run, not the more commonly-observed failure) must still surface as
    simulation_status="unstable" all the way through -- succeeding once must not be allowed to
    override the pre-flight flag.

    No such successful in-zone run exists yet in the actual BCG-validation/deterioration-stress-
    test data collected this session -- of the 4 representative points that landed in this zone
    across both subjects (day16/day20, both subjects), all 4 failed
    (docs/synthetic_deterioration_stress_test.md), none succeeded. This is therefore a
    CONSTRUCTED case (severity=0.65, the low end of the documented zone, paired with a mocked but
    structurally realistic completed-run DataFrame -- same shape run_pulse() actually returns),
    exercising the real, unmocked run_pulse_with_preflight() -> determine_simulation_status()
    composition end to end, not just isolated unit-level assertions on each function separately.
    """

    def _realistic_completed_df(self):
        # Same column shape run_pulse() actually returns (src/pulse_runner/runner.py's
        # _check_csv_completeness() reads a real Pulse-generated CSV) -- a plausible completed
        # acute_deterioration run's start/end values, not just a placeholder shape.
        return pd.DataFrame(
            {
                "Time(s)": [0, 660],
                "HeartRate(1/min)": [72, 165],
                "MeanArterialPressure(mmHg)": [95, 58],
                "CardiacOutput(mL/min)": [5000, 8200],
                "HeartStrokeVolume(mL)": [70, 52],
            }
        )

    def test_lucky_success_at_severity_065_still_reports_unstable(self):
        severity = 0.65  # low end of ACUTE_DETERIORATION_CRASH_RANGE (0.6, 0.85)
        assert is_known_unstable_configuration("acute_deterioration", severity) is True  # confirms this IS the zone

        with patch("src.pulse_runner.runner.run_pulse", return_value=self._realistic_completed_df()):
            with pytest.warns(RuntimeWarning, match="known-unstable"):
                pulse_result = run_pulse_with_preflight(
                    "scenario.json", "acute_deterioration", severity, expected_duration_s=660
                )

        # The run genuinely "succeeded" -- a real DataFrame came back, no exception.
        assert pulse_result["pulse_succeeded"] is True
        assert pulse_result["df"] is not None
        assert pulse_result["flagged_unstable"] is True

        # Feeding that (real, unmocked) composition into determine_simulation_status() must still
        # report "unstable" -- a successful outcome does not launder a flagged configuration.
        status = determine_simulation_status(
            "acute_deterioration", severity,
            pulse_attempted=pulse_result["pulse_attempted"],
            pulse_succeeded=pulse_result["pulse_succeeded"],
        )
        assert status == "unstable"

    def test_contrasted_with_a_genuinely_stable_success_outside_the_zone(self):
        # Same mocked "successful" DataFrame, same code path -- only severity differs. Confirms
        # the "unstable" result above is specifically about the crash-zone flag, not an artifact
        # of the mock itself always producing "unstable".
        severity = 0.3  # well outside (0.6, 0.85)
        with patch("src.pulse_runner.runner.run_pulse", return_value=self._realistic_completed_df()):
            pulse_result = run_pulse_with_preflight(
                "scenario.json", "acute_deterioration", severity, expected_duration_s=660
            )
        assert pulse_result["flagged_unstable"] is False
        status = determine_simulation_status(
            "acute_deterioration", severity,
            pulse_attempted=pulse_result["pulse_attempted"],
            pulse_succeeded=pulse_result["pulse_succeeded"],
        )
        assert status == "valid"
