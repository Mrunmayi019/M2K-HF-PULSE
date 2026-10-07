"""Phase 6: the 7 endpoints, in the dependency order they were built.

POST /patients -> POST .../clinical-report -> POST .../wearable-sync (BackgroundTasks-triggered,
returns immediately) -> GET .../status, .../history, .../projection, .../report (all fast DB reads,
zero Pulse calls in the request path -- everything Pulse-related already happened in the
background job the last /wearable-sync call that filled the 21-day window kicked off).
"""
from __future__ import annotations

import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from src import feature_flags
from src.analytics.score_reporting import (
    AlertAssessmentView, apply_hysteresis_to_ml_alert, apply_severity_hysteresis, build_score_report,
    decide_alert, determine_simulation_status, ml_severity_alert, signals_disagree,
)
from src.api import continuous_state_pipeline, models, schemas, services
from src.api.database import SessionLocal, get_db
from src.patient_builder.patient_file import HFREF_EF_THRESHOLD_PCT

router = APIRouter()


def get_patient_or_404(patient_id: str, db: Session = Depends(get_db)) -> models.Patient:
    patient = db.get(models.Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail=f"patient {patient_id!r} not found")
    return patient


@router.post("/patients", response_model=schemas.PatientResponse, status_code=201)
def create_patient(payload: schemas.PatientCreate, db: Session = Depends(get_db)):
    patient = models.Patient(**payload.model_dump())
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


@router.get("/patients", response_model=list[schemas.PatientResponse])
def list_patients(db: Session = Depends(get_db)):
    return db.query(models.Patient).order_by(models.Patient.created_at.asc()).all()


@router.post(
    "/patients/{patient_id}/clinical-report",
    response_model=schemas.ClinicalReportResponse,
    status_code=201,
)
def create_clinical_report(
    payload: schemas.ClinicalReportCreate,
    patient: models.Patient = Depends(get_patient_or_404),
    db: Session = Depends(get_db),
):
    ef, bnp, ef_is_fallback, bnp_is_fallback = services.apply_tier1_fallback(
        payload.ejection_fraction_pct, payload.nt_probnp_pg_ml
    )
    report = models.ClinicalReport(
        patient_id=patient.id,
        ejection_fraction_pct=ef,
        nt_probnp_pg_ml=bnp,
        ef_is_fallback=ef_is_fallback,
        bnp_is_fallback=bnp_is_fallback,
        rj_interval_ms=payload.rj_interval_ms,
        ij_amplitude=payload.ij_amplitude,
        jk_amplitude=payload.jk_amplitude,
        hr_baseline_bpm=payload.hr_baseline_bpm,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


@router.post(
    "/patients/{patient_id}/wearable-sync",
    response_model=schemas.WearableSyncResponse,
    status_code=202,
)
def sync_wearable_reading(
    payload: schemas.WearableReadingCreate,
    background_tasks: BackgroundTasks,
    patient: models.Patient = Depends(get_patient_or_404),
    db: Session = Depends(get_db),
):
    reading = models.WearableReading(patient_id=patient.id, **payload.model_dump())
    db.add(reading)
    db.commit()

    reading_count = (
        db.query(models.WearableReading).filter(models.WearableReading.patient_id == patient.id).count()
    )

    if reading_count < services.WEARABLE_WINDOW_DAYS:
        return schemas.WearableSyncResponse(
            status="collecting",
            reading_count=reading_count,
            message=f"{reading_count}/{services.WEARABLE_WINDOW_DAYS} days collected; "
            "simulation triggers once the window is full.",
        )

    if feature_flags.pipeline_mode() == "continuous":
        # Only a reading dated after every earlier one advances the twin by a day; an older or
        # same-date reading is kept and joins the window from the next run on (see
        # continuous_state_pipeline's module docstring). Fresh mode is unchanged below.
        newest_before = (
            db.query(func.max(models.WearableReading.recorded_date))
            .filter(models.WearableReading.patient_id == patient.id, models.WearableReading.id != reading.id)
            .scalar()
        )
        if newest_before is not None and reading.recorded_date <= newest_before:
            return schemas.WearableSyncResponse(
                status="stored_not_newest",
                reading_count=reading_count,
                message=f"Stored. {reading.recorded_date} is not after the newest reading ({newest_before}), "
                "so the twin is not advanced; it joins the window from the next run on.",
            )
        background_tasks.add_task(continuous_state_pipeline.run_continuous_pipeline_task, patient.id, SessionLocal)
        return schemas.WearableSyncResponse(
            status="simulation_triggered",
            reading_count=reading_count,
            message="Continuous mode: advancing the twin by one day in the background.",
        )

    background_tasks.add_task(services.run_assessment_pipeline, patient.id, SessionLocal)
    return schemas.WearableSyncResponse(
        status="simulation_triggered",
        reading_count=reading_count,
        message="21-day window complete -- assessment running in the background.",
    )


@router.get("/patients/{patient_id}/wearable-history", response_model=schemas.WearableHistoryResponse)
def get_wearable_history(patient: models.Patient = Depends(get_patient_or_404), db: Session = Depends(get_db)):
    readings = (
        db.query(models.WearableReading)
        .filter(models.WearableReading.patient_id == patient.id)
        .order_by(models.WearableReading.recorded_date.asc())
        .all()
    )
    return schemas.WearableHistoryResponse(
        patient_id=patient.id,
        readings=[schemas.WearableReadingResponse.model_validate(r) for r in readings],
    )


def _latest_assessment(db: Session, patient_id: str) -> models.RiskAssessment | None:
    return (
        db.query(models.RiskAssessment)
        .filter(models.RiskAssessment.patient_id == patient_id)
        .order_by(models.RiskAssessment.created_at.desc())
        .first()
    )


def _build_status(db: Session, patient: models.Patient) -> schemas.StatusResponse:
    reading_count = (
        db.query(models.WearableReading).filter(models.WearableReading.patient_id == patient.id).count()
    )
    latest_run = (
        db.query(models.SimulationRun)
        .filter(models.SimulationRun.patient_id == patient.id)
        .order_by(models.SimulationRun.id.desc())
        .first()
    )
    assessment = _latest_assessment(db, patient.id)

    # A failed run newer than the latest assessment means that assessment is out of date -- the
    # patient was re-classified (possibly as sicker, e.g. into the acute_deterioration crash zone)
    # and Pulse failed. Previously "any assessment wins" hid that failure behind a stale "complete".
    newer_run_failed = (
        latest_run is not None
        and latest_run.status == "failed"
        and (assessment is None or latest_run.id > assessment.simulation_run_id)
    )

    if newer_run_failed:
        sim_status = "failed"
    elif assessment is not None:
        sim_status = "complete"
    elif latest_run is not None:
        sim_status = latest_run.status
    elif reading_count < services.WEARABLE_WINDOW_DAYS:
        sim_status = "collecting"
    else:
        sim_status = "pending"

    latest_wearable = (
        db.query(models.WearableReading)
        .filter(models.WearableReading.patient_id == patient.id)
        .order_by(models.WearableReading.recorded_date.desc())
        .first()
    )

    # services.py never creates a RiskAssessment for a failed Pulse run, but the classifier's
    # scenario_type/severity are already stored on the SimulationRun before Pulse starts -- so the
    # alert decision for a failed run is built from those (classifier-only; decide_alert() alerts
    # on high severity even when the simulation is unstable). `current_alert` (legacy, kept for the
    # diagnostic fields it still carries -- severity_score/severity_band/confidence/
    # simulation_status) and `alert` (fix/unified-alert-decision -- THE alert decision; every
    # consumer, frontend included, should read this one and nothing else) are computed from the
    # same inputs, via decide_alert(), not two competing pieces of logic.
    if newer_run_failed and latest_run.severity is not None:
        current_alert = build_score_report(
            classifier_severity=latest_run.severity,
            pulse_risk_score=None,
            scenario_type=latest_run.scenario_type,
            pulse_attempted=True,
            pulse_succeeded=False,
        )
        status = determine_simulation_status(
            latest_run.scenario_type, latest_run.severity, pulse_attempted=True, pulse_succeeded=False,
        )
        decide_status = "unstable_failed" if status == "unstable" else status
        report = apply_severity_hysteresis(
            decide_alert(AlertAssessmentView(severity=latest_run.severity), decide_status),
            latest_run.severity_hysteresis_state,
        )
        alert = {"level": report.level, "source": report.source}
        ml_alert = apply_hysteresis_to_ml_alert(ml_severity_alert(latest_run.severity), latest_run.severity_hysteresis_state)
    elif assessment is not None and not newer_run_failed:
        current_alert = assessment.score_provenance
        alert = assessment.alert
        ml_alert = assessment.ml_severity_alert
    else:
        current_alert = None
        alert = None
        ml_alert = None

    return schemas.StatusResponse(
        patient_id=patient.id,
        simulation_status=sim_status,
        reading_count=reading_count,
        latest_assessment=schemas.RiskAssessmentPayload.model_validate(assessment) if assessment else None,
        latest_assessment_stale=assessment is not None and newer_run_failed,
        current_alert=current_alert,
        alert=alert,
        ml_severity_alert=ml_alert,
        signals_disagree=signals_disagree(alert["level"] if alert else None, ml_alert),
        latest_wearable=schemas.WearableReadingResponse.model_validate(latest_wearable) if latest_wearable else None,
        error_message=latest_run.error_message if latest_run and latest_run.status == "failed" else None,
        # From the assessment's own linked run, not `latest_run` -- if a newer run failed after
        # this assessment's run succeeded, `latest_run` would already be that failed run (see
        # sim_status logic above, which has the same "assessment wins" precedent).
        waveform_data=(
            db.get(models.SimulationRun, assessment.simulation_run_id).waveform_data
            if assessment
            else None
        ),
    )


@router.get("/patients/{patient_id}/status", response_model=schemas.StatusResponse)
def get_status(patient: models.Patient = Depends(get_patient_or_404), db: Session = Depends(get_db)):
    return _build_status(db, patient)


@router.get("/patients/{patient_id}/history", response_model=schemas.HistoryResponse)
def get_history(patient: models.Patient = Depends(get_patient_or_404), db: Session = Depends(get_db)):
    assessments = (
        db.query(models.RiskAssessment)
        .filter(models.RiskAssessment.patient_id == patient.id)
        .order_by(models.RiskAssessment.created_at.asc())
        .all()
    )
    return schemas.HistoryResponse(
        patient_id=patient.id,
        assessments=[schemas.RiskAssessmentPayload.model_validate(a) for a in assessments],
    )


@router.get("/patients/{patient_id}/projection", response_model=schemas.ProjectionResponse)
def get_projection(patient: models.Patient = Depends(get_patient_or_404), db: Session = Depends(get_db)):
    assessment = _latest_assessment(db, patient.id)
    if assessment is None or assessment.projection_json is None:
        return schemas.ProjectionResponse(patient_id=patient.id, available=False)
    return schemas.ProjectionResponse(
        patient_id=patient.id,
        available=True,
        horizons={k: schemas.ProjectionHorizon(**v) for k, v in assessment.projection_json.items()},
    )


@router.get("/patients/{patient_id}/report", response_model=schemas.ReportResponse)
def get_report(patient: models.Patient = Depends(get_patient_or_404), db: Session = Depends(get_db)):
    return schemas.ReportResponse(
        patient_id=patient.id,
        status=_build_status(db, patient),
        projection=get_projection(patient, db),
    )



# ---- Twin state (feature/wire-research-features) ----

@router.post("/patients/{patient_id}/reset-state", response_model=schemas.ResetStateResponse)
def reset_twin_state(patient: models.Patient = Depends(get_patient_or_404), db: Session = Depends(get_db)):
    """Start a fresh Pulse state from the next continuous run. Keeps every saved state, run and
    assessment; the next run simply ignores states saved before this request. Never triggered
    automatically."""
    reset = models.TwinStateReset(patient_id=patient.id)
    db.add(reset)
    db.commit()
    db.refresh(reset)
    mode = feature_flags.pipeline_mode()
    message = "The next run starts a fresh twin state. History is kept."
    if mode == "fresh":
        message += " PIPELINE_MODE is fresh, which rebuilds the twin every run anyway; this only matters in continuous mode."
    return schemas.ResetStateResponse(
        patient_id=patient.id, reset_requested_at=reset.requested_at, pipeline_mode=mode, message=message,
    )


def _continuous_runs(db: Session, patient_id: str, after: datetime.datetime):
    return (
        db.query(models.SimulationRun)
        .filter(
            models.SimulationRun.patient_id == patient_id,
            models.SimulationRun.started_at > after,
            or_(models.SimulationRun.pipeline_mode.is_(None), models.SimulationRun.pipeline_mode == "continuous"),
        )
        .order_by(models.SimulationRun.id.asc())
        .all()
    )


@router.get("/patients/{patient_id}/twin-state", response_model=schemas.TwinStateResponse)
def get_twin_state(patient: models.Patient = Depends(get_patient_or_404), db: Session = Depends(get_db)):
    reset = continuous_state_pipeline.latest_reset(db, patient.id)
    state = continuous_state_pipeline.current_state(db, patient.id)
    response = schemas.TwinStateResponse(
        patient_id=patient.id,
        flags=feature_flags.all_flags(),
        pipeline_mode=feature_flags.pipeline_mode(),
        last_reset_at=reset.requested_at if reset else None,
        reset_pending=reset is not None and state is None,
    )
    if state is None:
        return response

    started_at = state.state_started_at
    if started_at is None:
        # States saved before state_started_at existed: the oldest state since the last reset.
        query = db.query(func.min(models.PulseState.saved_at)).filter(models.PulseState.patient_id == patient.id)
        if reset is not None:
            query = query.filter(models.PulseState.saved_at > reset.requested_at)
        started_at = query.scalar()

    # The initial run started before started_at (its state is saved at the end); every later run
    # in this state started after it.
    later_runs = _continuous_runs(db, patient.id, started_at)
    completed = [r for r in later_runs if r.status == "complete"]
    exercise_idx = [i for i, r in enumerate(completed) if r.exercise_applied]

    report = services.latest_clinical_report(db, patient.id)
    mismatch = False
    if report is not None and state.hfref_condition_applied is not None:
        mismatch = (report.ejection_fraction_pct <= HFREF_EF_THRESHOLD_PCT) != state.hfref_condition_applied

    response.state_started_at = started_at
    response.state_simulation_time_s = state.simulation_time_s
    response.state_days = 1 + len(completed)
    response.engine_lag_days = sum(1 for r in later_runs if r.status == "failed")
    if exercise_idx:
        last = exercise_idx[-1]
        response.days_since_exercise_label = len(completed) - 1 - last
        response.last_exercise_scenario_type = completed[last].scenario_type
    response.hfref_condition_mismatch = mismatch
    return response
