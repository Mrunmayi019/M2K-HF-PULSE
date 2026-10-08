"""PIPELINE_MODE=continuous (feature/wire-research-features, section A). Pulse is replaced by
conftest.FakeContinuousPulse, which chains fake states and records each call, so every test can
check which state a run resumed from. No Docker needed.

Cases pinned here, as documented in src/api/continuous_state_pipeline.py's module docstring:
  - first qualifying day -> initial run, later days -> resume (+600 s each)
  - fresh mode never touches the continuous pipeline
  - a failed day: recorded as failed, next day resumes from the last good state, one encounter behind
  - two runs for one patient at once: serialised, the second resumes from the first
  - readings out of order / same date: stored, no run, no rewind
  - clinical report mid-stream: adopted next run (by id, including one sent during a run);
    crossing the 40% EF cutoff is reported as a condition mismatch, not silently "fixed"
  - reset-state: next run starts fresh, history kept, no automatic reset
  - twin-state: state start, engine_lag_days, days since an Exercise-triggering label
"""
from __future__ import annotations

import datetime
import json
import threading
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from conftest import FakeContinuousPulse, classifier, create_patient, fake_pulse_df, fill_window, sync
from src.api import models
from src.api.continuous_state_pipeline import DAILY_ENCOUNTER_DURATION_S, run_daily_continuous_pipeline
from src.api.database import Base
from src.patient_builder.scenario_file import STABILIZATION_S

INITIAL_T = STABILIZATION_S + DAILY_ENCOUNTER_DURATION_S


def _states(Session, patient_id):
    with Session() as db:
        rows = (
            db.query(models.PulseState)
            .filter(models.PulseState.patient_id == patient_id)
            .order_by(models.PulseState.id.asc())
            .all()
        )
        return [(json.loads(r.state_json), r.simulation_time_s, r.last_ejection_fraction_pct) for r in rows]


def _runs(Session, patient_id):
    with Session() as db:
        return [
            (r.status, r.scenario_type, r.pipeline_mode)
            for r in db.query(models.SimulationRun)
            .filter(models.SimulationRun.patient_id == patient_id)
            .order_by(models.SimulationRun.id.asc())
        ]


class _Env:
    """Patches the classifier, both continuous Pulse calls, and the projection's run_pulse."""

    def __init__(self, pulse, scenario="stable", severity=0.1, projection_df=None):
        self.pulse = pulse
        self.models = classifier(scenario, severity)
        self.projection_df = projection_df if projection_df is not None else fake_pulse_df()

    def __enter__(self):
        self._patches = [
            patch("src.api.continuous_state_pipeline._load_scenario_classifier_models", return_value=self.models),
            patch("src.pulse_runner.runner.run_pulse", return_value=self.projection_df),
            *self.pulse.patches(),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()


@pytest.fixture()
def continuous(research_api, flags_off):
    flags_off.setenv("PIPELINE_MODE", "continuous")
    return research_api


# ---- A1: routing ----

class TestRouting:
    def test_first_qualifying_day_runs_initial_then_later_days_resume(self, continuous):
        client, Session = continuous
        pid = create_patient(client)
        client.post(f"/patients/{pid}/clinical-report", json={"ejection_fraction_pct": 45, "nt_probnp_pg_ml": 400})
        pulse = FakeContinuousPulse()
        with _Env(pulse):
            for i in range(20):
                assert sync(client, pid, i).json()["status"] == "collecting"
            r = sync(client, pid, 20)
            assert r.json()["status"] == "simulation_triggered"
            for day in (21, 22, 23):
                assert sync(client, pid, day).json()["status"] == "simulation_triggered"

        assert [kind for kind, _ in pulse.calls] == ["initial", "resume", "resume", "resume"]
        states = _states(Session, pid)
        assert [t for _, t, _ in states] == [INITIAL_T + 600 * k for k in range(4)]
        # each state resumes from the one before it
        assert [s["parent"] for s, _, _ in states] == [None, 1, 2, 3]
        assert {mode for _, _, mode in _runs(Session, pid)} == {"continuous"}
        # the normal endpoints read the continuous assessments unchanged
        status = client.get(f"/patients/{pid}/status").json()
        assert status["simulation_status"] == "complete"
        assert len(client.get(f"/patients/{pid}/history").json()["assessments"]) == 4

    def test_fresh_mode_never_calls_continuous_pipeline(self, research_api):
        client, Session = research_api
        pid = create_patient(client)
        pulse = FakeContinuousPulse()
        with _Env(pulse), \
             patch("src.api.services._load_scenario_classifier_models", return_value=classifier()), \
             patch("src.api.continuous_state_pipeline.run_continuous_pipeline_task") as task:
            fill_window(client, pid, 22)
        task.assert_not_called()
        assert pulse.calls == []
        assert {mode for _, _, mode in _runs(Session, pid)} == {"fresh"}
        assert _states(Session, pid) == []

    def test_failed_day_resumes_from_last_good_state_one_encounter_behind(self, continuous):
        client, Session = continuous
        pid = create_patient(client)
        pulse = FakeContinuousPulse(fail_calls={2})  # day 2 (first resume) crashes
        with _Env(pulse):
            fill_window(client, pid, 21)     # call 1: initial
            sync(client, pid, 21)            # call 2: fails
            assert client.get(f"/patients/{pid}/status").json()["simulation_status"] == "failed"
            sync(client, pid, 22)            # call 3: resumes from call 1's state

        states = _states(Session, pid)
        assert len(states) == 2
        assert states[1][0]["parent"] == states[0][0]["serial"]
        assert states[1][1] == INITIAL_T + 600  # one encounter, not two: no catch-up
        assert [s for s, _, _ in _runs(Session, pid)] == ["complete", "failed", "complete"]
        twin = client.get(f"/patients/{pid}/twin-state").json()
        assert twin["engine_lag_days"] == 1
        assert twin["state_days"] == 2


# ---- A2: concurrency, ordering, clinical reports mid-stream ----

class TestConcurrentSubmissions:
    def _two_at_once(self, tmp_path, lock_patch=None):
        engine = create_engine(f"sqlite:///{tmp_path / 'conc.db'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        from scripts.verify_continuous_state_pipeline import add_one_reading, seed_patient_and_window

        with Session() as db:
            seed_patient_and_window(db, patient_id="P_CONC", ef=45.0, bnp=400.0)
        pulse = FakeContinuousPulse()
        with patch("src.api.continuous_state_pipeline.SCENARIOS_DIR", tmp_path / "s"), _Env(pulse):
            with Session() as db:
                run_daily_continuous_pipeline("P_CONC", db, compute_projection=False)  # day 1, initial
                add_one_reading(db, "P_CONC", day=21)
                add_one_reading(db, "P_CONC", day=22)
            pulse.delay_s = 0.3
            barrier = threading.Barrier(2)
            errors = []

            def worker():
                try:
                    with Session() as db:
                        barrier.wait()
                        run_daily_continuous_pipeline("P_CONC", db, compute_projection=False)
                except Exception as e:  # pragma: no cover - surfaced below
                    errors.append(e)

            extra = [lock_patch] if lock_patch else []
            for p in extra:
                p.start()
            try:
                threads = [threading.Thread(target=worker) for _ in range(2)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
            finally:
                for p in extra:
                    p.stop()
        assert not errors, errors
        states = _states(Session, "P_CONC")
        engine.dispose()
        return states

    def test_two_runs_at_once_are_serialised_and_chain(self, tmp_path, flags_off):
        states = self._two_at_once(tmp_path)
        assert [s["parent"] for s, _, _ in states] == [None, 1, 2]
        assert [t for _, t, _ in states] == [INITIAL_T, INITIAL_T + 600, INITIAL_T + 1200]

    def test_without_the_lock_both_resume_from_the_same_parent(self, tmp_path, flags_off):
        """Documents what the lock prevents (and what still happens across processes, where an
        in-process lock can't reach): both runs resume from day 1, one day of simulated time is
        lost, and the newer of the two forks silently becomes the current state."""
        import threading as _t

        no_lock = patch("src.api.continuous_state_pipeline._patient_lock", side_effect=lambda pid: _t.Lock())
        states = self._two_at_once(tmp_path, lock_patch=no_lock)
        assert [s["parent"] for s, _, _ in states[1:]] == [1, 1]
        assert [t for _, t, _ in states[1:]] == [INITIAL_T + 600, INITIAL_T + 600]


class TestOutOfOrder:
    def test_older_and_same_date_readings_are_stored_without_advancing(self, continuous):
        client, Session = continuous
        pid = create_patient(client)
        pulse = FakeContinuousPulse()
        with _Env(pulse):
            fill_window(client, pid, 21)                       # days 0..20 -> initial
            assert sync(client, pid, 22).json()["status"] == "simulation_triggered"  # skips day 21
            late = sync(client, pid, 21, resting_hr_bpm=99)    # day 21 arrives late
            assert late.json()["status"] == "stored_not_newest"
            dup = sync(client, pid, 22, resting_hr_bpm=98)     # same date again
            assert dup.json()["status"] == "stored_not_newest"
            assert sync(client, pid, 23).json()["status"] == "simulation_triggered"

        assert [kind for kind, _ in pulse.calls] == ["initial", "resume", "resume"]
        assert [t for _, t, _ in _states(Session, pid)] == [INITIAL_T, INITIAL_T + 600, INITIAL_T + 1200]
        # the late reading is kept and is part of the window used from then on
        dates = [r["recorded_date"] for r in client.get(f"/patients/{pid}/wearable-history").json()["readings"]]
        assert dates.count("2026-01-22") == 1 and dates.count("2026-01-23") == 2

    def test_fresh_mode_still_runs_on_every_reading(self, research_api):
        client, _ = research_api
        pid = create_patient(client)
        with patch("src.api.services._load_scenario_classifier_models", return_value=classifier()), \
             patch("src.pulse_runner.runner.run_pulse", return_value=fake_pulse_df()):
            fill_window(client, pid, 22)
            assert sync(client, pid, 5).json()["status"] == "simulation_triggered"


class TestClinicalReportMidStream:
    def test_new_report_is_adopted_on_next_run(self, continuous):
        client, Session = continuous
        pid = create_patient(client)
        client.post(f"/patients/{pid}/clinical-report", json={"ejection_fraction_pct": 45, "nt_probnp_pg_ml": 400})
        pulse = FakeContinuousPulse()
        with _Env(pulse):
            fill_window(client, pid, 21)
            sync(client, pid, 21)
            client.post(f"/patients/{pid}/clinical-report", json={"ejection_fraction_pct": 42, "nt_probnp_pg_ml": 900})
            sync(client, pid, 22)
            sync(client, pid, 23)
        assert [kw["ejection_fraction_pct"] for _, kw in pulse.calls] == [45, 45, 42, 42]
        assert [ef for _, _, ef in _states(Session, pid)] == [45, 45, 42, 42]
        hist = client.get(f"/patients/{pid}/history").json()["assessments"]
        assert [a["nt_probnp_pg_ml"] for a in hist] == [400, 400, 900, 900]
        assert client.get(f"/patients/{pid}/twin-state").json()["hfref_condition_mismatch"] is False

    def test_report_sent_while_a_run_is_in_progress_is_not_skipped(self, continuous):
        """The old timestamp rule (reported_at > last saved_at) dropped this report forever: it
        was reported before the run saved its state, but after the run had read its inputs."""
        client, Session = continuous
        pid = create_patient(client)
        client.post(f"/patients/{pid}/clinical-report", json={"ejection_fraction_pct": 45, "nt_probnp_pg_ml": 400})
        pulse = FakeContinuousPulse()
        original_resume = pulse.resume_and_advance

        def resume_and_report_midway(**kwargs):
            if len(pulse.calls) == 1:  # during the first resume
                with Session() as db:
                    db.add(models.ClinicalReport(patient_id=pid, ejection_fraction_pct=35.0, nt_probnp_pg_ml=1200.0))
                    db.commit()
            return original_resume(**kwargs)

        pulse.resume_and_advance = resume_and_report_midway
        with _Env(pulse):
            fill_window(client, pid, 21)
            sync(client, pid, 21)   # report arrives during this run
            sync(client, pid, 22)
        assert [kw["ejection_fraction_pct"] for _, kw in pulse.calls] == [45, 45, 35]

    def test_crossing_the_hfref_cutoff_is_reported_not_fixed(self, continuous):
        client, Session = continuous
        pid = create_patient(client)
        client.post(f"/patients/{pid}/clinical-report", json={"ejection_fraction_pct": 45, "nt_probnp_pg_ml": 400})
        pulse = FakeContinuousPulse()
        with _Env(pulse):
            fill_window(client, pid, 21)
            client.post(f"/patients/{pid}/clinical-report", json={"ejection_fraction_pct": 30, "nt_probnp_pg_ml": 2500})
            sync(client, pid, 21)
        assert pulse.calls[-1][0] == "resume"  # no automatic reset
        assert pulse.calls[-1][1]["ejection_fraction_pct"] == 30
        twin = client.get(f"/patients/{pid}/twin-state").json()
        assert twin["hfref_condition_mismatch"] is True


# ---- A3/A4: reset-state and twin-state ----

class TestResetAndTwinState:
    def test_reset_starts_fresh_from_next_run_and_keeps_history(self, continuous):
        client, Session = continuous
        pid = create_patient(client)
        pulse = FakeContinuousPulse()
        with _Env(pulse):
            fill_window(client, pid, 21)
            sync(client, pid, 21)
            before = client.get(f"/patients/{pid}/twin-state").json()
            r = client.post(f"/patients/{pid}/reset-state")
            assert r.status_code == 200 and r.json()["pipeline_mode"] == "continuous"
            pending = client.get(f"/patients/{pid}/twin-state").json()
            sync(client, pid, 22)
            sync(client, pid, 23)
        assert [kind for kind, _ in pulse.calls] == ["initial", "resume", "initial", "resume"]
        states = _states(Session, pid)
        assert len(states) == 4  # nothing deleted
        assert [t for _, t, _ in states] == [INITIAL_T, INITIAL_T + 600, INITIAL_T, INITIAL_T + 600]
        assert states[3][0]["parent"] == states[2][0]["serial"]
        assert len(client.get(f"/patients/{pid}/history").json()["assessments"]) == 4

        assert before["state_days"] == 2 and before["reset_pending"] is False
        assert pending["reset_pending"] is True and pending["state_started_at"] is None
        after = client.get(f"/patients/{pid}/twin-state").json()
        assert after["reset_pending"] is False
        assert after["state_days"] == 2
        assert after["state_started_at"] > before["state_started_at"]
        assert after["last_reset_at"] is not None

    def test_reset_in_fresh_mode_is_recorded_with_a_note(self, research_api):
        client, _ = research_api
        pid = create_patient(client)
        r = client.post(f"/patients/{pid}/reset-state")
        assert r.status_code == 200
        assert r.json()["pipeline_mode"] == "fresh"
        assert "only matters in continuous mode" in r.json()["message"]

    def test_reset_unknown_patient_404(self, research_api):
        client, _ = research_api
        assert client.post("/patients/nope/reset-state").status_code == 404
        assert client.get("/patients/nope/twin-state").status_code == 404

    def test_days_since_exercise_label(self, continuous):
        client, Session = continuous
        pid = create_patient(client)
        pulse = FakeContinuousPulse()
        with _Env(pulse, "cardiac_stress", 0.4):
            fill_window(client, pid, 21)   # initial: no Exercise on an initial run
        assert client.get(f"/patients/{pid}/twin-state").json()["days_since_exercise_label"] is None
        with _Env(pulse, "cardiac_stress", 0.4):
            sync(client, pid, 21)          # resume + Exercise
        twin = client.get(f"/patients/{pid}/twin-state").json()
        assert twin["days_since_exercise_label"] == 0
        assert twin["last_exercise_scenario_type"] == "cardiac_stress"
        with _Env(pulse, "stable", 0.1):
            sync(client, pid, 22)
            sync(client, pid, 23)
        twin = client.get(f"/patients/{pid}/twin-state").json()
        assert twin["days_since_exercise_label"] == 2
        assert twin["flags"]["PIPELINE_MODE"] == "continuous"
        assert twin["state_simulation_time_s"] == INITIAL_T + 3 * 600

    def test_twin_state_before_any_run(self, continuous):
        client, _ = continuous
        pid = create_patient(client)
        twin = client.get(f"/patients/{pid}/twin-state").json()
        assert twin["pipeline_mode"] == "continuous"
        assert twin["state_started_at"] is None and twin["state_days"] == 0 and twin["engine_lag_days"] == 0


def test_invalid_pipeline_mode_fails_loudly(flags_off):
    from src import feature_flags

    flags_off.setenv("PIPELINE_MODE", "contnuous")
    with pytest.raises(ValueError):
        feature_flags.pipeline_mode()
    flags_off.setenv("PIPELINE_MODE", "fresh")
    flags_off.setenv("ENABLE_BCG_MODIFIERS", "maybe")
    with pytest.raises(ValueError):
        feature_flags.validate_all()
