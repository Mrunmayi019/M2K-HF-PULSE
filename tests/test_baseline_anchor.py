"""ENABLE_BASELINE_ANCHOR (feature/baseline-anchor): the anchor (today's end values against the
state's baseline) and the weekly refresh (an initial run from the patient file, drift = resumed end
minus fresh end, the fresh state starts a new chain). Pulse is replaced by a FakeContinuousPulse
whose initial and resumed runs return different vitals, so every number below is checkable by hand.

  initial run: HR 70 -> 75, MAP 95 -> 90, CO 5000 -> 4800   (baseline = the start: 70 / 95 / 5000)
  resumed run: HR 60 -> 55, MAP 85 -> 80, CO 4500 -> 4000
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from conftest import FakeContinuousPulse, classifier, create_patient, fake_pulse_df, fill_window, sync
from src import feature_flags
from src.api import models

INITIAL_DF = fake_pulse_df(hr_start=70, hr_end=75, map_start=95, map_end=90, co_start=5000, co_end=4800)
RESUME_DF = fake_pulse_df(hr_start=60, hr_end=55, map_start=85, map_end=80, co_start=4500, co_end=4000)


class TwoDfPulse(FakeContinuousPulse):
    def run_initial(self, **kwargs):
        state, snap, _ = super().run_initial(**kwargs)
        return state, snap, INITIAL_DF

    def resume_and_advance(self, **kwargs):
        state, snap, _ = super().resume_and_advance(**kwargs)
        return state, snap, RESUME_DF


class _Env:
    def __init__(self, pulse, scenario="stable", severity=0.1):
        self.pulse = pulse
        self.models = classifier(scenario, severity)

    def __enter__(self):
        self._patches = [
            patch("src.api.continuous_state_pipeline._load_scenario_classifier_models", return_value=self.models),
            patch("src.pulse_runner.runner.run_pulse", return_value=fake_pulse_df()),
            *self.pulse.patches(),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()


@pytest.fixture()
def anchored(research_api, flags_off):
    flags_off.setenv("PIPELINE_MODE", "continuous")
    flags_off.setenv("ENABLE_BASELINE_ANCHOR", "1")
    return research_api


def _anchors(client, pid):
    return [a.get("baseline_anchor") for a in client.get(f"/patients/{pid}/history").json()["assessments"]]


def _run_days(client, pid, resumes):
    """Day 1 (initial) plus `resumes` more days."""
    fill_window(client, pid, 21)
    for d in range(resumes):
        sync(client, pid, 21 + d)


class TestFlagValues:
    def test_defaults(self, flags_off):
        assert feature_flags.baseline_anchor_enabled() is False
        assert feature_flags.baseline_refresh_days() == 7

    def test_defaults_keep_the_dashboard_panel_hidden(self, flags_off):
        """frontend/src/utils/twinState.js hides the twin-state panel only when every listed
        value is 'fresh' or False, so the refresh period is listed only with the anchor on."""
        flags = feature_flags.all_flags()
        assert "BASELINE_REFRESH_DAYS" not in flags
        assert all(v is False for k, v in flags.items() if k != "PIPELINE_MODE")
        flags_off.setenv("ENABLE_BASELINE_ANCHOR", "1")
        assert feature_flags.all_flags()["BASELINE_REFRESH_DAYS"] == 7

    @pytest.mark.parametrize("raw", ["-1", "seven", "1.5"])
    def test_bad_refresh_days_fail_loudly(self, flags_off, raw):
        flags_off.setenv("BASELINE_REFRESH_DAYS", raw)
        with pytest.raises(ValueError):
            feature_flags.validate_all()


class TestFlagOff:
    def test_continuous_mode_without_the_flag_records_nothing(self, research_api, flags_off):
        flags_off.setenv("PIPELINE_MODE", "continuous")
        client, Session = research_api
        pid = create_patient(client)
        pulse = TwoDfPulse()
        with _Env(pulse):
            _run_days(client, pid, 8)
        assert [k for k, _ in pulse.calls] == ["initial"] + ["resume"] * 8  # no refresh
        assert _anchors(client, pid) == [None] * 9
        assert all("baseline_anchor" not in a for a in client.get(f"/patients/{pid}/history").json()["assessments"])
        with Session() as db:
            assert {s.baseline_hr_bpm for s in db.query(models.PulseState)} == {None}
        assert client.get(f"/patients/{pid}/twin-state").json()["baseline_refresh_in_days"] is None

    def test_fresh_mode_ignores_the_flag(self, research_api, flags_off):
        flags_off.setenv("ENABLE_BASELINE_ANCHOR", "1")
        client, Session = research_api
        pid = create_patient(client)
        pulse = TwoDfPulse()
        with _Env(pulse), \
             patch("src.api.services._load_scenario_classifier_models", return_value=classifier()), \
             patch("src.pulse_runner.runner.run_pulse", return_value=fake_pulse_df()):
            fill_window(client, pid, 22)
        assert pulse.calls == []
        assert _anchors(client, pid) == [None, None]


class TestAnchor:
    def test_baseline_is_the_initial_runs_first_sample_and_is_carried(self, anchored, flags_off):
        flags_off.setenv("BASELINE_REFRESH_DAYS", "0")
        client, Session = anchored
        pid = create_patient(client)
        with _Env(TwoDfPulse()):
            _run_days(client, pid, 2)
        day1, day2, day3 = _anchors(client, pid)
        baseline = {"hr_bpm": 70.0, "map_mmhg": 95.0, "co_ml_min": 5000.0}
        assert day1["chain_day"] == 1 and day1["baseline"] == baseline
        # day 1 against baseline is the initial run's own fresh-mode deltas
        assert day1["vs_baseline"] == {"hr_rise_bpm": 5.0, "map_drop_mmhg": 5.0, "co_drop_pct": 4.0}
        for n, day in ((2, day2), (3, day3)):
            assert day["chain_day"] == n
            assert day["baseline"] == baseline
            assert day["today_end"] == {"hr_bpm": 55.0, "map_mmhg": 80.0, "co_ml_min": 4000.0}
            assert day["vs_baseline"] == {"hr_rise_bpm": -15.0, "map_drop_mmhg": 15.0, "co_drop_pct": 20.0}
            assert "refresh" not in day
        with Session() as db:
            assert {(s.baseline_hr_bpm, s.baseline_map_mmhg, s.baseline_co_ml_min) for s in db.query(models.PulseState)} == {(70, 95, 5000)}

    def test_anchor_does_not_change_risk_scores(self, research_api, flags_off):
        flags_off.setenv("PIPELINE_MODE", "continuous")
        client, _ = research_api

        def history(anchor):
            flags_off.setenv("ENABLE_BASELINE_ANCHOR", "1" if anchor else "0")
            flags_off.setenv("BASELINE_REFRESH_DAYS", "0")
            pid = create_patient(client)
            with _Env(TwoDfPulse()):
                _run_days(client, pid, 3)
            keep = ("risk_score", "risk_bucket", "component_scores", "baseline_deficit_score", "nyha_class", "alert")
            return [{k: a.get(k) for k in keep} for a in client.get(f"/patients/{pid}/history").json()["assessments"]]

        assert history(anchor=True) == history(anchor=False)

    def test_turned_on_mid_chain_says_there_is_no_baseline(self, research_api, flags_off):
        flags_off.setenv("PIPELINE_MODE", "continuous")
        client, _ = research_api
        pid = create_patient(client)
        with _Env(TwoDfPulse()):
            fill_window(client, pid, 21)   # initial run, flag off
            flags_off.setenv("ENABLE_BASELINE_ANCHOR", "1")
            flags_off.setenv("BASELINE_REFRESH_DAYS", "0")
            sync(client, pid, 21)
        _, day2 = _anchors(client, pid)
        assert day2["baseline"] is None and day2["vs_baseline"] is None
        assert "no baseline" in day2["note"]
        assert day2["today_end"]["hr_bpm"] == 55.0


class TestRefresh:
    def test_weekly_refresh_runs_once_the_chain_holds_seven_states(self, anchored):
        client, Session = anchored
        pid = create_patient(client)
        pulse = TwoDfPulse()
        with _Env(pulse):
            _run_days(client, pid, 6)                               # chain days 1-7
            assert client.get(f"/patients/{pid}/twin-state").json()["baseline_refresh_in_days"] == 0
            sync(client, pid, 27)                                   # day 8: resume + refresh
            twin = client.get(f"/patients/{pid}/twin-state").json()
            sync(client, pid, 28)                                   # resumes from the fresh state

        kinds = [k for k, _ in pulse.calls]
        assert kinds == ["initial"] + ["resume"] * 7 + ["initial", "resume"]
        fresh_serial = 9
        assert json.loads(pulse.calls[-1][1]["state_json"])["serial"] == fresh_serial
        # the refresh uses the day's own EF/severity and the same encounter length
        refresh_kw = pulse.calls[8][1]
        assert refresh_kw["severity"] == pulse.calls[7][1]["severity"]
        assert refresh_kw["duration_s"] == pulse.calls[7][1]["duration_s"]

        anchors = _anchors(client, pid)
        assert len(anchors) == 9  # one assessment per day; the refresh adds none
        day8 = anchors[7]
        assert day8["chain_day"] == 8
        assert day8["refresh"] == {
            "performed": True,
            "exercise_in_resume": False,
            "fresh_end": {"hr_bpm": 75.0, "map_mmhg": 90.0, "co_ml_min": 4800.0},
            "drift": {"hr_bpm": -20.0, "map_mmhg": -10.0, "co_ml_min": -800.0},
        }
        # the day's assessment still comes from the resumed run
        assert day8["today_end"]["hr_bpm"] == 55.0
        assert anchors[8]["chain_day"] == 2 and "refresh" not in anchors[8]

        assert twin["state_days"] == 1 and twin["baseline_refresh_in_days"] == 6
        with Session() as db:
            states = db.query(models.PulseState).order_by(models.PulseState.id).all()
            assert len(states) == 10  # the resumed day-8 state is kept as history
            assert states[8].state_started_at == states[8].saved_at
            assert states[9].state_started_at == states[8].state_started_at
            assert states[7].state_started_at == states[0].state_started_at

    def test_refresh_period_is_seven_days_each_time(self, anchored):
        client, _ = anchored
        pid = create_patient(client)
        pulse = TwoDfPulse()
        with _Env(pulse):
            _run_days(client, pid, 14)
        initial_calls = [i for i, (k, _) in enumerate(pulse.calls) if k == "initial"]
        # call 0 = day 1; refresh on day 8 (after its resume, call 8); next on day 15 (call 16)
        assert initial_calls == [0, 8, 16]
        refreshed = [i for i, a in enumerate(_anchors(client, pid)) if "refresh" in a]
        assert refreshed == [7, 14]

    def test_failed_refresh_keeps_the_resumed_state_and_retries_next_day(self, anchored):
        client, Session = anchored
        pid = create_patient(client)
        pulse = TwoDfPulse(fail_calls={9})  # the day-8 refresh
        with _Env(pulse):
            _run_days(client, pid, 8)
        kinds = [k for k, _ in pulse.calls]
        assert kinds == ["initial"] + ["resume"] * 7 + ["initial", "resume", "initial"]
        # day 9 resumed from day 8's resumed state, not a fresh one
        assert json.loads(pulse.calls[9][1]["state_json"])["serial"] == 8
        anchors = _anchors(client, pid)
        assert anchors[7]["refresh"]["performed"] is False
        assert "simulated Pulse crash" in anchors[7]["refresh"]["error"]
        assert anchors[8]["refresh"]["performed"] is True
        statuses = [a["risk_bucket"] is not None for a in client.get(f"/patients/{pid}/history").json()["assessments"]]
        assert statuses == [True] * 9  # the failed refresh never failed the day

    def test_exercise_day_is_marked_in_the_drift_record(self, anchored, flags_off):
        flags_off.setenv("BASELINE_REFRESH_DAYS", "2")
        client, _ = anchored
        pid = create_patient(client)
        with _Env(TwoDfPulse(), scenario="cardiac_stress", severity=0.3):
            _run_days(client, pid, 2)
        anchors = _anchors(client, pid)
        assert anchors[2]["refresh"]["exercise_in_resume"] is True

    def test_refresh_days_zero_never_refreshes(self, anchored, flags_off):
        flags_off.setenv("BASELINE_REFRESH_DAYS", "0")
        client, _ = anchored
        pid = create_patient(client)
        pulse = TwoDfPulse()
        with _Env(pulse):
            _run_days(client, pid, 10)
        assert [k for k, _ in pulse.calls].count("initial") == 1
        assert client.get(f"/patients/{pid}/twin-state").json()["baseline_refresh_in_days"] is None

    def test_refresh_gives_a_mid_chain_state_its_baseline(self, research_api, flags_off):
        flags_off.setenv("PIPELINE_MODE", "continuous")
        flags_off.setenv("BASELINE_REFRESH_DAYS", "2")
        client, _ = research_api
        pid = create_patient(client)
        with _Env(TwoDfPulse()):
            fill_window(client, pid, 21)   # flag off
            flags_off.setenv("ENABLE_BASELINE_ANCHOR", "1")
            sync(client, pid, 21)          # chain day 2, no baseline
            sync(client, pid, 22)          # chain day 3: refresh
            sync(client, pid, 23)
        anchors = _anchors(client, pid)
        assert anchors[1]["baseline"] is None and anchors[2]["refresh"]["performed"] is True
        assert anchors[3]["baseline"] == {"hr_bpm": 70.0, "map_mmhg": 95.0, "co_ml_min": 5000.0}
