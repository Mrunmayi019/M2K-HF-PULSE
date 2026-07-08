"""Phase 6: Pydantic request/response models, written before any endpoint logic.

Physiological range constraints on every wearable vital are what makes malformed input reject
with FastAPI's automatic 422 before it ever reaches Pulse (per the roadmap PDF §6.5).
"""
from __future__ import annotations

import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Sex = Literal["Male", "Female"]


# ---- Patients ----

class PatientCreate(BaseModel):
    age: float = Field(ge=0, le=120)
    sex: Sex
    height_cm: float = Field(ge=50, le=250)
    weight_kg: float = Field(ge=2, le=400)


class PatientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    age: float
    sex: str
    height_cm: float
    weight_kg: float
    created_at: datetime.datetime


# ---- Clinical reports ----

class ClinicalReportCreate(BaseModel):
    ejection_fraction_pct: Optional[float] = Field(default=None, ge=0, le=100)
    nt_probnp_pg_ml: Optional[float] = Field(default=None, ge=0, le=50000)


class ClinicalReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: str
    ejection_fraction_pct: float
    nt_probnp_pg_ml: float
    ef_is_fallback: bool
    bnp_is_fallback: bool
    reported_at: datetime.datetime


# ---- Wearable readings ----

class WearableReadingCreate(BaseModel):
    recorded_date: datetime.date
    resting_hr_bpm: float = Field(ge=20, le=250)
    spo2_pct: float = Field(ge=50, le=100)
    weight_kg: float = Field(ge=20, le=300)
    steps_per_day: float = Field(ge=0, le=100_000)
    sleep_hours: float = Field(ge=0, le=24)
    hrv_rmssd_ms: float = Field(ge=0, le=300)


class WearableSyncResponse(BaseModel):
    status: Literal["collecting", "simulation_triggered"]
    reading_count: int
    message: str


class WearableReadingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recorded_date: datetime.date
    resting_hr_bpm: float
    spo2_pct: float
    weight_kg: float
    steps_per_day: float
    sleep_hours: float
    hrv_rmssd_ms: float


# ---- Shared risk payload pieces ----

RISK_CAVEATS_DESCRIPTION = (
    "Populated when the detected scenario_type is fluid_overload. Phase 5 validation "
    "(docs/methodology.md §6.1) found risk_score is structurally blind to this scenario's "
    "shifted-baseline presentation (chronically congested but acutely stable at rest) -- the "
    "5-feature delta-based formula only sees change *during* one simulated encounter, not an "
    "already-abnormal starting state. risk_score should not be relied on alone for "
    "fluid_overload patients; this field surfaces that caveat directly in the API response."
)


class ProjectionHorizon(BaseModel):
    projected_severity: float
    risk_score: Optional[float] = None
    risk_bucket: Optional[str] = None
    status: str


class RiskAssessmentPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    risk_score: float
    risk_bucket: str
    component_scores: dict
    nyha_class: str
    risk_caveats: Optional[str] = Field(default=None, description=RISK_CAVEATS_DESCRIPTION)
    deterioration_direction: Optional[str] = None
    days_to_next_stage: Optional[int] = None
    scenario_type: Optional[str] = None
    severity: Optional[float] = None
    ejection_fraction_pct: Optional[float] = None
    nt_probnp_pg_ml: Optional[float] = None
    vital_slopes: Optional[dict] = None
    created_at: datetime.datetime


# ---- Status / History / Projection / Report ----

class StatusResponse(BaseModel):
    patient_id: str
    simulation_status: Literal["collecting", "pending", "running", "complete", "failed"]
    reading_count: int
    latest_assessment: Optional[RiskAssessmentPayload] = None
    latest_wearable: Optional[WearableReadingResponse] = None
    error_message: Optional[str] = None


class HistoryResponse(BaseModel):
    patient_id: str
    assessments: list[RiskAssessmentPayload]


class ProjectionResponse(BaseModel):
    patient_id: str
    available: bool
    horizons: Optional[dict[str, ProjectionHorizon]] = None


class ReportResponse(BaseModel):
    patient_id: str
    status: StatusResponse
    projection: ProjectionResponse
