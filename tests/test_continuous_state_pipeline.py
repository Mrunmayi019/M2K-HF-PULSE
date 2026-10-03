"""Tests for the 2026-10-02 continuous-state-sync / real-outcome-validation / unstable-alert-
fallback integration (docs/integration_pre_results.md): the shared risk-caveats helper (Part A)
and the alert-fallback parity fix (Part B) in src/api/continuous_state_pipeline.py.

Pulse is mocked at two points, both needed for a clean success path: run_initial()/
resume_and_advance() (src.api.continuous_state_pipeline's own imported names -- this pipeline's
day-advance calls go through the CLI-driver layer, src/pulse_runner/cli_state_runner.py, not
runner.py directly) AND src.pulse_runner.runner.run_pulse (the same point tests/test_api.py
mocks), since project_physiology()'s own 7/14/30-day horizon re-simulations call that directly,
independent of the day-advance call. No Docker needed; runs in plain pytest/CI.
"""
from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scripts.verify_continuous_state_pipeline import (
    WINDOW_DAYS,
    add_clinical_report,
    add_one_reading,
    seed_patient_and_window,
)
from src.api import models
from src.api.continuous_state_pipeline import (
    DAILY_ENCOUNTER_DURATION_S,
    run_daily_continuous_pipeline,
)
from src.api.database import Base
from src.api.routes import _build_status
from src.api.services import _run_assessment_pipeline, build_risk_caveats
from src.patient_builder.scenario_file import STABILIZATION_S


def _fake_pulse_df(hr_start=71, hr_end=71, map_start=95, map_end=95, co_start=5000, co_end=5000, sv_start=70, sv_end=70):
    """Same shape as tests/test_api.py's helper of the same name -- analyze_simulation()/
    extract_waveform_data() both need these exact column names."""
    return pd.DataFrame(
        {
            "Time(s)": [0, 600],
            "HeartRate(1/min)": [hr_start, hr_end],
            "MeanArterialPressure(mmHg)": [map_start, map_end],
            "CardiacOutput(mL/min)": [co_start, co_end],
            "HeartStrokeVolume(mL)": [sv_start, sv_end],
            "OxygenSaturation": [0.0, 0.0],
            "LeftHeart-Volume(mL)": [100.0, 100.0],
            "LeftHeart-Pressure(mmHg)": [60.0, 60.0],
            "ECG-Lead3ElectricPotential(mV)": [0.0, 0.0],
        }
    )


class _FakeModel:
    def __init__(self, value):
        self.value = value

    def predict(self, x):
        return [self.value] * len(x)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    # SCENARIOS_DIR is hardcoded to the Docker-only /workspace path (same convention
    # tests/test_api.py's `client` fixture already works around) -- redirect it here since tests
    # run on the host, not in Docker. Both pipelines' SCENARIOS_DIR are patched so the projection-
    # consistency test (TestProjectionConsistency) can call either one.
    with patch("src.api.continuous_state_pipeline.SCENARIOS_DIR", tmp_path / "scenarios_continuous"), \
         patch("src.api.services.SCENARIOS_DIR", tmp_path / "scenarios_normal"):
        yield session
    session.close()


def _fake_classifier(scenario_type="stable", severity=0.1):
    return (_FakeModel(scenario_type), _FakeModel(severity))


class TestPulseFailureHandling:
    def test_failure_is_recorded_and_matches_normal_pipeline_alert_fallback(self, db):
        patient_id = "P_FAIL"
        seed_patient_and_window(db, patient_id=patient_id, ef=30.0, bnp=2000.0)

        # Day 1: succeeds, stable/low severity -> a real RiskAssessment exists.
        with patch(
            "src.api.continuous_state_pipeline._load_scenario_classifier_models",
            return_value=_fake_classifier("stable", 0.1),
        ), patch(
            "src.api.continuous_state_pipeline.run_initial",
            return_value=('{"fake": "state1"}', {"simulation_time_s": STABILIZATION_S + DAILY_ENCOUNTER_DURATION_S}, _fake_pulse_df()),
        ), patch(
            # project_physiology()'s own 7/14/30-day horizon runs call this directly (separate
            # from run_initial/resume_and_advance) -- same mock point tests/test_api.py uses.
            "src.pulse_runner.runner.run_pulse",
            return_value=_fake_pulse_df(),
        ):
            state1 = run_daily_continuous_pipeline(patient_id, db)
        assert state1 is not None

        # Day 2: re-classified into the crash zone, Pulse fails.
        add_one_reading(db, patient_id, day=WINDOW_DAYS)
        with patch(
            "src.api.continuous_state_pipeline._load_scenario_classifier_models",
            return_value=_fake_classifier("acute_deterioration", 0.7),
        ), patch(
            "src.api.continuous_state_pipeline.resume_and_advance",
            side_effect=RuntimeError("simulated Pulse crash"),
        ):
            result = run_daily_continuous_pipeline(patient_id, db)

        assert result is None

        failed_run = (
            db.query(models.SimulationRun)
            .filter(models.SimulationRun.patient_id == patient_id, models.SimulationRun.status == "failed")
            .order_by(models.SimulationRun.started_at.desc())
            .first()
        )
        assert failed_run is not None
        assert "simulated Pulse crash" in failed_run.error_message
        assert failed_run.scenario_type == "acute_deterioration"
        assert failed_run.severity == pytest.approx(0.7)

        # _build_status() must report the failure, not hide it behind day 1's calmer assessment --
        # same contract fix/unstable-alert-fallback already guarantees for the normal pipeline.
        patient = db.get(models.Patient, patient_id)
        status = _build_status(db, patient)
        assert status.simulation_status == "failed"
        assert status.latest_assessment is not None  # day 1's assessment still exists
        assert status.latest_assessment_stale is True
        assert status.current_alert is not None
        assert status.current_alert["alert"] == "alert"
        assert status.current_alert["alert_basis"] == "classifier_only"
        assert status.current_alert["classifier_severity"] == pytest.approx(0.7)
        assert status.current_alert["pulse_risk_score"] is None

        # The last good PulseState (day 1's) must be untouched by the failed day.
        last_state = (
            db.query(models.PulseState)
            .filter(models.PulseState.patient_id == patient_id)
            .order_by(models.PulseState.saved_at.desc())
            .first()
        )
        assert last_state.id == state1.id
        assert last_state.state_json == state1.state_json
        assert last_state.simulation_time_s == state1.simulation_time_s

    def test_non_pulse_exception_is_not_swallowed_and_not_recorded_as_pulse_failure(self, db):
        """A bug in code AFTER the Pulse call (e.g. the real project_physiology TypeError found
        during this integration) must raise normally, not get misreported as a Pulse failure."""
        patient_id = "P_BUG"
        seed_patient_and_window(db, patient_id=patient_id, ef=45.0, bnp=800.0)

        with patch(
            "src.api.continuous_state_pipeline._load_scenario_classifier_models",
            return_value=_fake_classifier("stable", 0.1),
        ), patch(
            "src.api.continuous_state_pipeline.run_initial",
            return_value=('{"fake": "state1"}', {"simulation_time_s": STABILIZATION_S + DAILY_ENCOUNTER_DURATION_S}, _fake_pulse_df()),
        ), patch(
            "src.api.continuous_state_pipeline.project_physiology",
            side_effect=TypeError("got an unexpected keyword argument 'deterioration_rate_per_day'"),
        ):
            with pytest.raises(TypeError):
                run_daily_continuous_pipeline(patient_id, db)

        # The SimulationRun was pre-created (status="running") before the bug, but Pulse itself
        # never failed -- it must NOT be marked "failed" (that would misreport a code bug as an
        # unstable Pulse run and could wrongly trigger the classifier-only alert fallback).
        run = (
            db.query(models.SimulationRun)
            .filter(models.SimulationRun.patient_id == patient_id)
            .order_by(models.SimulationRun.started_at.desc())
            .first()
        )
        assert run is not None
        assert run.status == "running"
        assert run.error_message is None

    def test_day_after_failure_resumes_from_last_good_state_one_encounter_behind(self, db):
        """Pins down current behavior per explicit instruction not to change it: a failed day is
        skipped entirely, not compensated for -- the next successful day resumes from the last
        GOOD state and advances by exactly one DAILY_ENCOUNTER_DURATION_S, not two. The engine's
        simulated clock ends up permanently one encounter behind the calendar for each failed day.
        """
        patient_id = "P_GAP"
        seed_patient_and_window(db, patient_id=patient_id, ef=45.0, bnp=800.0)
        day1_time = STABILIZATION_S + DAILY_ENCOUNTER_DURATION_S

        with patch(
            "src.api.continuous_state_pipeline._load_scenario_classifier_models",
            return_value=_fake_classifier("stable", 0.1),
        ), patch(
            "src.api.continuous_state_pipeline.run_initial",
            return_value=("day1_state_json", {"simulation_time_s": day1_time}, _fake_pulse_df()),
        ), patch(
            "src.pulse_runner.runner.run_pulse",
            return_value=_fake_pulse_df(),
        ):
            state1 = run_daily_continuous_pipeline(patient_id, db)

        # Day 2 fails -- no new PulseState is written.
        add_one_reading(db, patient_id, day=WINDOW_DAYS)
        with patch(
            "src.api.continuous_state_pipeline._load_scenario_classifier_models",
            return_value=_fake_classifier("stable", 0.1),
        ), patch(
            "src.api.continuous_state_pipeline.resume_and_advance",
            side_effect=RuntimeError("simulated Pulse crash"),
        ):
            assert run_daily_continuous_pipeline(patient_id, db) is None

        # Day 3 succeeds -- must resume from day 1's state (day 2 never produced one) and advance
        # by exactly one DAILY_ENCOUNTER_DURATION_S, confirmed via the mock's call arguments.
        add_one_reading(db, patient_id, day=WINDOW_DAYS + 1)
        day3_time = day1_time + DAILY_ENCOUNTER_DURATION_S
        with patch(
            "src.api.continuous_state_pipeline._load_scenario_classifier_models",
            return_value=_fake_classifier("stable", 0.1),
        ), patch(
            "src.api.continuous_state_pipeline.resume_and_advance",
            return_value=("day3_state_json", {"simulation_time_s": day3_time}, _fake_pulse_df()),
        ) as mock_resume, patch(
            "src.pulse_runner.runner.run_pulse",
            return_value=_fake_pulse_df(),
        ):
            state3 = run_daily_continuous_pipeline(patient_id, db)

        assert state3 is not None
        _, call_kwargs = mock_resume.call_args
        assert call_kwargs["state_json"] == state1.state_json  # resumed from day 1, not a phantom day 2
        assert call_kwargs["prior_offset_s"] == pytest.approx(day1_time)
        # Exactly one encounter advanced -- NOT two (no catch-up/compensation logic exists).
        assert state3.simulation_time_s == pytest.approx(day1_time + DAILY_ENCOUNTER_DURATION_S)
        assert state3.simulation_time_s != pytest.approx(day1_time + 2 * DAILY_ENCOUNTER_DURATION_S)


class TestRiskCaveatsParity:
    def test_build_risk_caveats_always_includes_ecg_caveat(self):
        for scenario_type, ef_is_fallback, risk_bucket in [
            ("stable", False, "LOW"),
            ("fluid_overload", False, "MODERATE"),
            ("fluid_overload", True, "LOW"),
        ]:
            caveats = build_risk_caveats(scenario_type, ef_is_fallback, risk_bucket)
            assert "ECG trace is a stored reference rhythm template" in caveats

    def test_fluid_overload_ef_fallback_mask_is_selected_correctly(self):
        masked = build_risk_caveats("fluid_overload", True, "LOW")
        unmasked = build_risk_caveats("fluid_overload", False, "MODERATE")
        not_fluid = build_risk_caveats("stable", False, "LOW")

        assert "ejection_fraction_pct was not measured" in masked
        assert "risk_score is known to underestimate severity" in unmasked
        assert "risk_score is known to underestimate severity" not in not_fluid
        assert "ejection_fraction_pct was not measured" not in not_fluid

    def test_continuous_pipeline_produces_same_caveats_as_shared_helper(self, db):
        """End-to-end: a fluid_overload day through the continuous pipeline must carry the same
        caveat text build_risk_caveats() (shared with services.py) would produce directly --
        this is the gap found during the 2026-10-02 merge (continuous_state_pipeline.py previously
        built risk_caveats inline and silently omitted the ECG caveat)."""
        patient_id = "P_CAVEAT"
        seed_patient_and_window(db, patient_id=patient_id, ef=30.0, bnp=1800.0)

        with patch(
            "src.api.continuous_state_pipeline._load_scenario_classifier_models",
            return_value=_fake_classifier("fluid_overload", 0.3),
        ), patch(
            "src.api.continuous_state_pipeline.run_initial",
            return_value=('{"fake": "state1"}', {"simulation_time_s": STABILIZATION_S + DAILY_ENCOUNTER_DURATION_S}, _fake_pulse_df()),
        ), patch(
            "src.pulse_runner.runner.run_pulse",
            return_value=_fake_pulse_df(),
        ):
            state = run_daily_continuous_pipeline(patient_id, db)
        assert state is not None

        assessment = (
            db.query(models.RiskAssessment)
            .filter(models.RiskAssessment.patient_id == patient_id)
            .order_by(models.RiskAssessment.created_at.desc())
            .first()
        )
        assert assessment is not None
        expected = build_risk_caveats("fluid_overload", False, assessment.risk_bucket)
        assert assessment.risk_caveats == expected
        assert "ECG trace is a stored reference rhythm template" in assessment.risk_caveats


class TestProjectionConsistency:
    def test_continuous_and_normal_pipelines_produce_identical_projection_for_identical_inputs(self, db):
        """Step 4 of docs/integration_pre_results.md: for the same patient demographics/EF/BNP/
        wearable window and the same classifier output and the same Pulse encounter result, the
        continuous pipeline (first-ever run, last_state=None, same branch _resolve_clinical_values
        takes as _run_assessment_pipeline's own latest_report path) and the normal from-scratch
        pipeline must call project_physiology() with the same arguments and produce the same
        projection_json -- they're the same function call, not two independent implementations."""
        patient_a = "P_NORMAL"  # through services._run_assessment_pipeline
        patient_b = "P_CONTINUOUS"  # through run_daily_continuous_pipeline
        for pid in (patient_a, patient_b):
            seed_patient_and_window(db, patient_id=pid, ef=38.0, bnp=1200.0)

        with patch(
            "src.api.services._load_scenario_classifier_models",
            return_value=_fake_classifier("cardiac_stress", 0.35),
        ), patch(
            "src.pulse_runner.runner.run_pulse",
            return_value=_fake_pulse_df(),
        ):
            _run_assessment_pipeline(patient_a, db)

        with patch(
            "src.api.continuous_state_pipeline._load_scenario_classifier_models",
            return_value=_fake_classifier("cardiac_stress", 0.35),
        ), patch(
            "src.api.continuous_state_pipeline.run_initial",
            return_value=('{"fake": "state"}', {"simulation_time_s": STABILIZATION_S + DAILY_ENCOUNTER_DURATION_S}, _fake_pulse_df()),
        ), patch(
            "src.pulse_runner.runner.run_pulse",
            return_value=_fake_pulse_df(),
        ):
            state_b = run_daily_continuous_pipeline(patient_b, db)
        assert state_b is not None

        assessment_a = (
            db.query(models.RiskAssessment)
            .filter(models.RiskAssessment.patient_id == patient_a)
            .order_by(models.RiskAssessment.created_at.desc())
            .first()
        )
        assessment_b = (
            db.query(models.RiskAssessment)
            .filter(models.RiskAssessment.patient_id == patient_b)
            .order_by(models.RiskAssessment.created_at.desc())
            .first()
        )
        assert assessment_a is not None and assessment_b is not None

        assert assessment_a.projection_json == assessment_b.projection_json
        assert assessment_a.risk_score == assessment_b.risk_score
        assert assessment_a.risk_bucket == assessment_b.risk_bucket
        assert assessment_a.nyha_class == assessment_b.nyha_class
        assert assessment_a.deterioration_direction == assessment_b.deterioration_direction


class TestComputeProjectionOptOut:
    def test_default_path_still_computes_projections(self, db):
        """compute_projection defaults to True -- production/demo call sites never pass the
        argument at all, so this pins that the default preserves exact prior behavior."""
        patient_id = "P_PROJ_DEFAULT"
        seed_patient_and_window(db, patient_id=patient_id, ef=38.0, bnp=1200.0)

        with patch(
            "src.api.continuous_state_pipeline._load_scenario_classifier_models",
            return_value=_fake_classifier("cardiac_stress", 0.35),
        ), patch(
            "src.api.continuous_state_pipeline.run_initial",
            return_value=('{"fake": "state"}', {"simulation_time_s": STABILIZATION_S + DAILY_ENCOUNTER_DURATION_S}, _fake_pulse_df()),
        ), patch(
            "src.pulse_runner.runner.run_pulse",
            return_value=_fake_pulse_df(),
        ):
            state = run_daily_continuous_pipeline(patient_id, db)  # compute_projection omitted
        assert state is not None

        assessment = (
            db.query(models.RiskAssessment)
            .filter(models.RiskAssessment.patient_id == patient_id)
            .order_by(models.RiskAssessment.created_at.desc())
            .first()
        )
        assert assessment is not None
        assert assessment.projection_json is not None
        assert set(assessment.projection_json.keys()) == {"7", "14", "30"}

    def test_compute_projection_false_matches_default_path_except_projection(self, db):
        """With compute_projection=False, risk_score/nyha_class/the alert decision must be
        identical to the default (True) path for the same inputs -- only projection_json differs
        (None instead of the computed dict)."""
        patient_default = "P_PROJ_ON"
        patient_opt_out = "P_PROJ_OFF"
        for pid in (patient_default, patient_opt_out):
            seed_patient_and_window(db, patient_id=pid, ef=38.0, bnp=1200.0)

        with patch(
            "src.api.continuous_state_pipeline._load_scenario_classifier_models",
            return_value=_fake_classifier("cardiac_stress", 0.35),
        ), patch(
            "src.api.continuous_state_pipeline.run_initial",
            return_value=('{"fake": "state"}', {"simulation_time_s": STABILIZATION_S + DAILY_ENCOUNTER_DURATION_S}, _fake_pulse_df()),
        ), patch(
            "src.pulse_runner.runner.run_pulse",
            return_value=_fake_pulse_df(),
        ):
            state_on = run_daily_continuous_pipeline(patient_default, db, compute_projection=True)

        with patch(
            "src.api.continuous_state_pipeline._load_scenario_classifier_models",
            return_value=_fake_classifier("cardiac_stress", 0.35),
        ), patch(
            "src.api.continuous_state_pipeline.run_initial",
            return_value=('{"fake": "state"}', {"simulation_time_s": STABILIZATION_S + DAILY_ENCOUNTER_DURATION_S}, _fake_pulse_df()),
        ):
            # No runner.run_pulse mock needed here -- with projection off, project_physiology()
            # (the only caller of runner.run_pulse in this pipeline) is never invoked. If this
            # assumption is ever wrong, the test fails loudly with an unmocked real subprocess
            # call rather than silently passing.
            state_off = run_daily_continuous_pipeline(patient_opt_out, db, compute_projection=False)

        assert state_on is not None and state_off is not None

        assessment_on = (
            db.query(models.RiskAssessment)
            .filter(models.RiskAssessment.patient_id == patient_default)
            .order_by(models.RiskAssessment.created_at.desc())
            .first()
        )
        assessment_off = (
            db.query(models.RiskAssessment)
            .filter(models.RiskAssessment.patient_id == patient_opt_out)
            .order_by(models.RiskAssessment.created_at.desc())
            .first()
        )

        assert assessment_off.projection_json is None
        assert assessment_on.projection_json is not None

        # Everything else -- risk_score, nyha_class, and the alert decision -- must be identical.
        assert assessment_on.risk_score == assessment_off.risk_score
        assert assessment_on.risk_bucket == assessment_off.risk_bucket
        assert assessment_on.nyha_class == assessment_off.nyha_class
        assert assessment_on.deterioration_direction == assessment_off.deterioration_direction
        assert assessment_on.risk_caveats == assessment_off.risk_caveats
        assert assessment_on.score_provenance["alert"] == assessment_off.score_provenance["alert"]
        assert (
            assessment_on.score_provenance["alert_basis"]
            == assessment_off.score_provenance["alert_basis"]
        )
