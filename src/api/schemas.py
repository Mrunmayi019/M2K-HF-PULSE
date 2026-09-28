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


class WearableHistoryResponse(BaseModel):
    patient_id: str
    readings: list[WearableReadingResponse]


# ---- Shared risk payload pieces ----

RISK_CAVEATS_DESCRIPTION = (
    "Populated when the detected scenario_type is fluid_overload. risk_score.py's "
    "baseline_deficit_score term (docs/methodology.md §6.1) fixes this scenario's shifted-baseline "
    "blind spot (chronically congested but acutely stable at rest) when a real, measured "
    "ejection_fraction_pct is available -- in that case this field carries the general "
    "fluid_overload caveat (the fix is a hand-tuned approximation, not a guarantee). When EF is "
    "unmeasured and Tier-1-fallback-defaulted instead, the fix has no congested baseline to "
    "detect and risk_score can still understate severity for a different, specific reason -- this "
    "field then carries that mechanism-specific caveat instead (docs/real_world_data_integration.md "
    "§8.5). Either way, risk_score should not be relied on alone for fluid_overload patients."
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
    baseline_deficit_score: Optional[float] = Field(
        default=None,
        description=(
            "The chronic-baseline-congestion sub-score (fluid_overload's map_start-driven fix, "
            "docs/methodology.md §6.1) -- risk_score = max(acute_score, baseline_deficit_score). "
            "component_scores only covers the acute mechanism, so a fluid_overload patient whose "
            "risk is baseline-driven can show every component_scores entry as 0 while risk_score "
            "is nonzero -- this field is what actually explains that case. None for runs that "
            "predate this field (2026-08-28)."
        ),
    )
    dominant_mechanism: Optional[Literal["acute", "baseline"]] = Field(
        default=None, description="Which of the two mechanisms above produced risk_score."
    )
    nyha_class: str
    risk_caveats: Optional[str] = Field(default=None, description=RISK_CAVEATS_DESCRIPTION)
    deterioration_direction: Optional[str] = None
    days_to_next_stage: Optional[int] = None
    scenario_type: Optional[str] = None
    severity: Optional[float] = None
    severity_band: Optional[str] = Field(
        default=None,
        description=(
            "Descriptive label for `severity` -- 'within_stable_range' or 'exceeds_stable_range', "
            "relative to this project's own training-data stable-scenario severity ceiling "
            "(0.15, docs/methodology.md Sec 8). Explicitly NOT a clinical alert threshold: no "
            "cutoff has been derived from real outcome data. Do not treat this as equivalent to "
            "risk_bucket."
        ),
    )
    score_provenance: Optional[dict] = Field(
        default=None,
        description=(
            "{'classifier_severity', 'pulse_risk_score', 'source', 'severity_score', "
            "'severity_band', 'alert', 'alert_basis', 'confidence', 'simulation_status', "
            "'threshold_clinically_validated'} -- src.analytics.score_reporting."
            "build_score_report()'s full output. 'source' is 'not_fused' whenever "
            "both scores are present (the only state reachable when this payload exists at all) -- "
            "severity and risk_score are never combined into one number (docs/methodology.md "
            "Sec 8's 'blocked on data' note: no real outcome-calibration data exists yet for a "
            "fused score). 'simulation_status' ('valid'|'unstable'|'not_run') and 'confidence' "
            "(0-1, derived from simulation_status) are Sprint 2 additions -- 'unstable' covers both "
            "an outright Pulse failure and a 'lucky' success inside the documented "
            "acute_deterioration crash zone (severity 0.6-0.85), either way not a reliable data "
            "point. 'alert' ('alert'|'no_alert'|'indeterminate') is produced by a function "
            "structurally separate from score production (project_severity() and friends only "
            "ever produce a number, never an alert decision). When 'simulation_status' is "
            "'unstable' and severity exceeds the stable range, 'alert' is still 'alert' (classifier "
            "fallback) and 'alert_basis' is 'classifier_only'; 'alert_basis' is "
            "'classifier_and_simulation' only for a 'valid' run -- its underlying threshold logic "
            "remains an unvalidated engineering placeholder pending real outcome data, same as "
            "'severity_band'; do not read 'alert' as a clinically validated determination. "
            "'threshold_clinically_validated' (Sprint 2.5) is always `false` -- a fixed, explicit "
            "statement that none of this payload's thresholds (STABLE_SEVERITY_CAP, "
            "MIN_CONFIDENCE_FOR_ALERT, CONFIDENCE_BY_STATUS, ENTER/EXIT_THRESHOLD, "
            "SCENARIO_TYPE_PERSISTENCE_N, or risk_score.py's own LOW/MODERATE_HIGH_BOUNDARY) has "
            "been checked against real outcome data, so a caller never has to infer this from "
            "scattered docstrings."
        ),
    )
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
    waveform_data: Optional[dict] = Field(
        default=None,
        description=(
            "Steady-state ECG trace + pressure-volume (PV) loop from the latest completed "
            "simulation run, if any. {'cycle_duration_s', 'pv_loop': [{'volume_ml', "
            "'pressure_mmhg'}, ...], 'ecg': [{'t_s', 'mv'}, ...]} -- see "
            "src.analytics.simulation_features.extract_waveform_data(). None for runs that "
            "predate this field (2026-08-28) or that failed/are still in progress."
        ),
    )


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
