"""ENABLE_ALERT_HYSTERESIS / ENABLE_SCENARIO_PERSISTENCE (feature/wire-research-features, section
C). Pins the order of operations documented in src/analytics/score_reporting.py:

  classifier -> scenario persistence -> [Pulse] -> risk_score -> C3 streak (raw) -> decide_alert()
  -> hysteresis, applied only to severity-rule levels (failed_fallback / unstable_completed) and to
  the separately-reported ML signal.

Parameter values are the functions' existing defaults throughout; nothing is tuned here."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from conftest import classifier, create_patient, fake_pulse_df, fill_window, sync
from src.analytics.score_reporting import (
    ENTER_N, ENTER_THRESHOLD, EXIT_N, EXIT_THRESHOLD, SCENARIO_TYPE_PERSISTENCE_N, AlertAssessmentView,
    AlertReport, apply_hysteresis_to_ml_alert, apply_severity_hysteresis, compute_baseline_high_streak,
    decide_alert, effective_scenario_type, ml_severity_alert,
)
from src.api import models
from src.pulse_runner.runner import PulseExecutionError

CONGESTED = fake_pulse_df(hr_start=70, hr_end=70, map_start=70, map_end=70)


def test_existing_parameter_values_unchanged():
    assert (ENTER_THRESHOLD, EXIT_THRESHOLD, ENTER_N, EXIT_N) == (0.15, pytest.approx(0.12), 2, 2)
    assert SCENARIO_TYPE_PERSISTENCE_N == 6


# ---- order of operations, pure functions ----

class TestOrder:
    @pytest.mark.parametrize("report", [
        AlertReport("ALERT", "risk_scorer"), AlertReport("WATCH", "moderate"),
        AlertReport("WATCH", "c3_downgraded"), AlertReport("NONE", "risk_scorer"),
    ])
    @pytest.mark.parametrize("state", ["alert", "no_alert"])
    def test_valid_twin_levels_are_never_touched(self, report, state):
        assert apply_severity_hysteresis(report, state) == report

    @pytest.mark.parametrize("source", ["failed_fallback", "unstable_completed"])
    def test_severity_rule_levels_follow_the_hysteresis_state(self, source):
        assert apply_severity_hysteresis(AlertReport("ALERT", source), "no_alert") == AlertReport("NONE", source)
        assert apply_severity_hysteresis(AlertReport("NONE", source), "alert") == AlertReport("ALERT", source)

    def test_flag_off_state_none_is_identity(self):
        r = AlertReport("ALERT", "failed_fallback")
        assert apply_severity_hysteresis(r, None) is r
        ml = ml_severity_alert(0.7)
        assert apply_hysteresis_to_ml_alert(ml, None) is ml
        assert apply_hysteresis_to_ml_alert(None, "alert") is None

    def test_c3_streak_is_computed_from_raw_daily_values_and_ignores_hysteresis(self):
        """The C3 bookkeeping takes no hysteresis input at all, so its downgrade happens on exactly
        the same day either way; hysteresis cannot cancel or delay it."""
        streak, seen = None, None
        levels = []
        for _ in range(5):
            streak, seen = compute_baseline_high_streak(streak, seen, "HIGH", "baseline", 0)
            view = AlertAssessmentView(severity=0.3, risk_bucket="HIGH", dominant_mechanism="baseline",
                                       baseline_high_streak_days=streak, instability_seen_in_streak=seen)
            levels.append([apply_severity_hysteresis(decide_alert(view, "valid"), s).level
                           for s in (None, "alert", "no_alert")])
        assert levels == [["ALERT"] * 3] * 3 + [["WATCH"] * 3] * 2

    def test_persistence_uses_raw_label_until_one_is_confirmed(self):
        hist = ["stable"] * 5
        assert effective_scenario_type(hist, "fluid_overload") == ("fluid_overload", None)
        assert effective_scenario_type(hist, "stable") == ("stable", "stable")  # 6th stable confirms
        hist6 = ["stable"] * 6
        assert effective_scenario_type(hist6 + ["fluid_overload"] * 4, "fluid_overload") == ("stable", "stable")
        assert effective_scenario_type(hist6 + ["fluid_overload"] * 5, "fluid_overload") == ("fluid_overload", "fluid_overload")


# ---- end to end through the API (fresh pipeline) ----

def _day(client, pid, day, scenario, severity, pulse):
    kwargs = {"side_effect": PulseExecutionError("simulated crash")} if isinstance(pulse, str) else {"return_value": pulse}
    with patch("src.api.services._load_scenario_classifier_models", return_value=classifier(scenario, severity)), \
         patch("src.pulse_runner.runner.run_pulse", **kwargs):
        sync(client, pid, day)
    return client.get(f"/patients/{pid}/status").json()


def _seed(client, ef=30):
    pid = create_patient(client)
    client.post(f"/patients/{pid}/clinical-report", json={"ejection_fraction_pct": ef, "nt_probnp_pg_ml": 1500})
    with patch("src.api.services._load_scenario_classifier_models", return_value=classifier("stable", 0.05)), \
         patch("src.pulse_runner.runner.run_pulse", return_value=fake_pulse_df()):
        fill_window(client, pid)  # day 20: first run, stable / 0.05
    return pid


class TestHysteresisEndToEnd:
    def test_single_high_severity_failed_day_no_longer_alerts(self, research_api, flags_off):
        client, _ = research_api
        off = _seed(client)
        s_off = _day(client, off, 21, "acute_deterioration", 0.7, "crash")
        assert s_off["alert"] == {"level": "ALERT", "source": "failed_fallback"}

        flags_off.setenv("ENABLE_ALERT_HYSTERESIS", "1")
        on = _seed(client)
        s1 = _day(client, on, 21, "acute_deterioration", 0.7, "crash")
        assert s1["alert"] == {"level": "NONE", "source": "failed_fallback"}  # 1 day >= 0.15 < ENTER_N
        assert s1["ml_severity_alert"]["level"] == "NONE" and s1["ml_severity_alert"]["hysteresis_applied"] is True
        assert s1["signals_disagree"] is False
        s2 = _day(client, on, 22, "acute_deterioration", 0.7, "crash")
        assert s2["alert"] == {"level": "ALERT", "source": "failed_fallback"}  # 2nd consecutive day

    def test_crash_zone_completion_follows_hysteresis(self, research_api, flags_off):
        flags_off.setenv("ENABLE_ALERT_HYSTERESIS", "1")
        client, _ = research_api
        pid = _seed(client)
        s = _day(client, pid, 21, "acute_deterioration", 0.7, fake_pulse_df())
        assert s["alert"] == {"level": "NONE", "source": "unstable_completed"}
        assert s["latest_assessment"]["alert"] == s["alert"]

    def test_c3_and_risk_scorer_levels_identical_with_and_without_hysteresis(self, research_api, flags_off):
        client, _ = research_api
        sequence = [("fluid_overload", 0.3, CONGESTED)] * 5 + [("stable", 0.05, fake_pulse_df())] * 2
        results = {}
        for flag in ("0", "1"):
            flags_off.setenv("ENABLE_ALERT_HYSTERESIS", flag)
            pid = _seed(client)
            results[flag] = [_day(client, pid, 21 + i, *d)["alert"] for i, d in enumerate(sequence)]
        assert results["0"] == results["1"]
        assert [a["level"] for a in results["1"]] == ["ALERT"] * 3 + ["WATCH"] * 2 + ["NONE"] * 2

    def test_ml_signal_needs_two_days_below_exit_to_clear(self, research_api, flags_off):
        flags_off.setenv("ENABLE_ALERT_HYSTERESIS", "1")
        client, _ = research_api
        pid = _seed(client)
        levels = [
            _day(client, pid, 21 + i, "stable", sev, fake_pulse_df())["ml_severity_alert"]["level"]
            for i, sev in enumerate([0.3, 0.3, 0.1, 0.13, 0.1, 0.1])
        ]
        # enter after 2 days >= 0.15; 0.13 is in the deadband (>= 0.12) and breaks the exit streak
        assert levels == ["NONE", "ALERT", "ALERT", "ALERT", "ALERT", "NONE"]

    def test_state_stored_only_when_flag_on(self, research_api, flags_off):
        client, Session = research_api
        pid = _seed(client)
        flags_off.setenv("ENABLE_ALERT_HYSTERESIS", "1")
        _day(client, pid, 21, "stable", 0.3, fake_pulse_df())
        with Session() as db:
            states = [r.severity_hysteresis_state for r in
                      db.query(models.SimulationRun).filter_by(patient_id=pid).order_by(models.SimulationRun.id)]
        assert states == [None, "no_alert"]


class TestScenarioPersistenceEndToEnd:
    def _run_labels(self, client, pid, labels, start_day=21):
        types = []
        for i, label in enumerate(labels):
            with patch("src.api.services._load_scenario_classifier_models", return_value=classifier(label, 0.3)), \
                 patch("src.pulse_runner.runner.run_pulse", return_value=fake_pulse_df()), \
                 patch("src.api.services.build_scenario_file", wraps=__import__(
                     "src.patient_builder.scenario_file", fromlist=["x"]).build_scenario_file) as bsf:
                sync(client, pid, start_day + i)
            types.append(bsf.call_args.kwargs["scenario_type"])
        return types

    def test_pulse_gets_the_confirmed_label_and_raw_is_kept(self, research_api, flags_off):
        flags_off.setenv("ENABLE_SCENARIO_PERSISTENCE", "1")
        client, Session = research_api
        pid = _seed(client)  # day 20: raw "stable", nothing confirmed yet -> raw used
        labels = ["stable"] * 5 + ["fluid_overload"] * 6
        simulated = self._run_labels(client, pid, labels)
        # stable confirmed on its 6th day; then fluid_overload is held back until its own 6th day
        assert simulated == ["stable"] * 5 + ["stable"] * 5 + ["fluid_overload"]
        with Session() as db:
            runs = db.query(models.SimulationRun).filter_by(patient_id=pid).order_by(models.SimulationRun.id).all()
        assert [r.raw_scenario_type for r in runs[1:]] == labels
        assert [r.scenario_type for r in runs[1:]] == simulated
        assert client.get(f"/patients/{pid}/status").json()["latest_assessment"]["scenario_type"] == "fluid_overload"

    def test_flag_off_simulates_raw_label(self, research_api):
        client, _ = research_api
        pid = _seed(client)
        labels = ["stable"] * 6 + ["fluid_overload", "cardiac_stress"]
        assert self._run_labels(client, pid, labels) == labels
