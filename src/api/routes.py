"""Phase 6: the 7 endpoints, in the dependency order they were built.

POST /patients -> POST .../clinical-report -> POST .../wearable-sync (BackgroundTasks-triggered,
returns immediately) -> GET .../status, .../history, .../projection, .../report (all fast DB reads,
zero Pulse calls in the request path -- everything Pulse-related already happened in the
background job the last /wearable-sync call that filled the 21-day window kicked off).
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api import models, schemas, services
from src.api.database import SessionLocal, get_db

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

    if assessment is not None:
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

    return schemas.StatusResponse(
        patient_id=patient.id,
        simulation_status=sim_status,
        reading_count=reading_count,
        latest_assessment=schemas.RiskAssessmentPayload.model_validate(assessment) if assessment else None,
        latest_wearable=schemas.WearableReadingResponse.model_validate(latest_wearable) if latest_wearable else None,
        error_message=latest_run.error_message if latest_run and latest_run.status == "failed" else None,
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
