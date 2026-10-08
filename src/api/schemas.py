"""Phase 6: Pydantic request/response models, written before any endpoint logic.

Physiological range constraints on every wearable vital are what makes malformed input reject
with FastAPI's automatic 422 before it ever reaches Pulse (per the roadmap PDF §6.5).
"""
from __future__ import annotations

import datetime
from typing import Any, ClassVar, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from src.patient_builder.personalisation import (
    BCG_FIELDS, HR_BASELINE_BPM_RANGE, IJ_AMPLITUDE_RANGE, JK_AMPLITUDE_RANGE, RJ_INTERVAL_MS_RANGE,
)

Sex = Literal["Male", "Female"]


class _OmitNewFieldsWhenNone(BaseModel):
    """feature/wire-research-features: fields added by this branch are left out of the JSON
    entirely when they are None, so with every flag off a response is exactly what main returned
    (tests/test_flags_off_parity.py). Fields that existed on main are untouched."""
    _omit_when_none: ClassVar[tuple[str, ...]] = ()

    @model_serializer(mode="wrap")
    def _omit_new_none_fields(self, handler) -> dict[str, Any]:
        data = handler(self)
        for name in self._omit_when_none:
            if data.get(name) is None:
                data.pop(name, None)
        return data


# ---- Patients ----

class PatientCreate(BaseModel):
    age: float = Field(ge=0, le=120)
    sex: Sex
    height_cm: float = Field(ge=50, le=250)
    weight_kg: float = Field(ge=2, le=400)
    # Optional display name for demo patients (scripts/seed_demo_patients.py). Never a real name.
    label: Optional[str] = Field(default=None, max_length=80)


class PatientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    age: float
    sex: str
    height_cm: float
    weight_kg: float
    created_at: datetime.datetime
    label: Optional[str] = None


# ---- Clinical reports ----

_EXPERIMENTAL_NOTE = (
    "Optional, experimental. Accepted range is what the 2 calibration subjects (Zhan et al. 2025 "
    "BCG dataset, subjects 14 and 102) cover; values outside it are rejected. Stored always, used "
    "only when the matching flag is on (src/patient_builder/personalisation.py)."
)


class ClinicalReportCreate(BaseModel):
    ejection_fraction_pct: Optional[float] = Field(default=None, ge=0, le=100)
    nt_probnp_pg_ml: Optional[float] = Field(default=None, ge=0, le=50000)
    # feature/wire-research-features -- ENABLE_BCG_MODIFIERS. All three or none.
    rj_interval_ms: Optional[float] = Field(
        default=None, ge=RJ_INTERVAL_MS_RANGE[0], le=RJ_INTERVAL_MS_RANGE[1],
        description="ECG R-peak to BCG J-peak interval, ms. " + _EXPERIMENTAL_NOTE,
    )
    ij_amplitude: Optional[float] = Field(
        default=None, ge=IJ_AMPLITUDE_RANGE[0], le=IJ_AMPLITUDE_RANGE[1],
        description="BCG I-J amplitude in that dataset's own units (not g-force). " + _EXPERIMENTAL_NOTE,
    )
    jk_amplitude: Optional[float] = Field(
        default=None, ge=JK_AMPLITUDE_RANGE[0], le=JK_AMPLITUDE_RANGE[1],
        description="BCG J-K amplitude in that dataset's own units (not g-force). " + _EXPERIMENTAL_NOTE,
    )
    # feature/wire-research-features -- ENABLE_HR_BASELINE. Clinician-entered measured resting HR.
    hr_baseline_bpm: Optional[float] = Field(
        default=None, ge=HR_BASELINE_BPM_RANGE[0], le=HR_BASELINE_BPM_RANGE[1],
        description=(
            "Measured resting heart rate from a clinical source (not derived from wearables). "
            "Pulse clamps it to 110. " + _EXPERIMENTAL_NOTE
        ),
    )

    @model_validator(mode="after")
    def _bcg_all_or_none(self):
        given = [f for f in BCG_FIELDS if getattr(self, f) is not None]
        if given and len(given) != len(BCG_FIELDS):
            missing = [f for f in BCG_FIELDS if getattr(self, f) is None]
            raise ValueError(f"BCG features must be given together; missing {missing}")
        return self


class ClinicalReportResponse(_OmitNewFieldsWhenNone):
    model_config = ConfigDict(from_attributes=True)
    _omit_when_none: ClassVar[tuple[str, ...]] = (*BCG_FIELDS, "hr_baseline_bpm")

    id: int
    patient_id: str
    ejection_fraction_pct: float
    nt_probnp_pg_ml: float
    ef_is_fallback: bool
    bnp_is_fallback: bool
    reported_at: datetime.datetime
    rj_interval_ms: Optional[float] = None
    ij_amplitude: Optional[float] = None
    jk_amplitude: Optional[float] = None
    hr_baseline_bpm: Optional[float] = None


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
    # "stored_not_newest": PIPELINE_MODE=continuous only -- the reading is saved (it joins the
    # 21-day window from the next run on) but its date is not after every earlier reading, so it
    # does not advance the twin by a day. Never returned in fresh mode.
    status: Literal["collecting", "simulation_triggered", "stored_not_newest"]
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
    "Always populated for a completed run: it carries the ECG-reference-template caveat "
    "(docs/methodology.md §4.2 -- the dashboard's ECG trace is heart-rate-scaled template output, "
    "not computed from cardiac electrophysiology) for every scenario_type. When scenario_type is "
    "fluid_overload, a scenario-specific caveat is prepended: risk_score.py's baseline_deficit_score "
    "term (docs/methodology.md §6.1) fixes this scenario's shifted-baseline blind spot (chronically "
    "congested but acutely stable at rest) when a real, measured ejection_fraction_pct is available "
    "-- in that case the prepended text is the general fluid_overload caveat (the fix is a "
    "hand-tuned approximation, not a guarantee). When EF is unmeasured and Tier-1-fallback-defaulted "
    "instead, the fix has no congested baseline to detect and risk_score can still understate "
    "severity for a different, specific reason -- the prepended text is that mechanism-specific "
    "caveat instead (docs/real_world_data_integration.md §8.5). Either way, risk_score should not be "
    "relied on alone for fluid_overload patients."
)


class AlertReportPayload(BaseModel):
    """src.analytics.score_reporting.decide_alert()'s output (fix/unified-alert-decision) -- the
    ONE alert decision. `level`: ALERT (urgent) / WATCH (elevated, not urgent) / NONE. `source`:
    'risk_scorer' (normal risk-scorer-driven ALERT or NONE), 'moderate' (risk_bucket=='MODERATE'
    WATCH), 'c3_downgraded' (a sustained baseline-only HIGH streak downgraded to WATCH -- never
    to NONE), 'failed_fallback' (Pulse run failed; classifier-severity-only fallback),
    'unstable_completed' (Pulse succeeded but landed in the documented crash zone; same
    classifier-only fallback, Pulse's own output untrusted either way)."""
    level: Literal["ALERT", "WATCH", "NONE"]
    source: Literal["risk_scorer", "c3_downgraded", "failed_fallback", "unstable_completed", "moderate"]


class MlSeverityAlertPayload(_OmitNewFieldsWhenNone):
    """src.analytics.score_reporting.ml_severity_alert() (fix/alert-both-signals): ML Model 1's
    own signal, reported SEPARATELY from the twin-based `alert`. `level` is ALERT when `severity`
    exceeds `threshold` (STABLE_SEVERITY_CAP, 0.15 -- the existing, unvalidated engineering
    placeholder; no new threshold), otherwise NONE."""
    level: Literal["ALERT", "NONE"]
    severity: float
    threshold: float
    source: Literal["ml_severity"]
    _omit_when_none: ClassVar[tuple[str, ...]] = ("hysteresis_applied",)
    hysteresis_applied: Optional[bool] = Field(
        default=None,
        description="Present (true) only when ENABLE_ALERT_HYSTERESIS set `level` from the multi-day state.",
    )


SIGNALS_DISAGREE_DESCRIPTION = (
    "True when exactly one of the two signals fires: the twin-based `alert` (fires at ALERT or "
    "WATCH) and `ml_severity_alert` (fires at ALERT). Always False on a failed or crash-zone Pulse "
    "run, where `alert` itself falls back to the same severity rule. None when either is missing."
)


class ProjectionHorizon(BaseModel):
    projected_severity: float
    risk_score: Optional[float] = None
    risk_bucket: Optional[str] = None
    status: str


class RiskAssessmentPayload(_OmitNewFieldsWhenNone):
    model_config = ConfigDict(from_attributes=True)
    _omit_when_none: ClassVar[tuple[str, ...]] = ("personalisation",)

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
    alert: Optional[AlertReportPayload] = Field(
        default=None,
        description=(
            "THE alert decision for this assessment (fix/unified-alert-decision) -- "
            "src.analytics.score_reporting.decide_alert()'s {level, source}. Every consumer, "
            "frontend included, should read this field and nothing else for alert/watch state."
        ),
    )
    ml_severity_alert: Optional[MlSeverityAlertPayload] = Field(
        default=None,
        description=(
            "ML Model 1's own severity signal (fix/alert-both-signals), separate from the "
            "twin-based `alert`. For a valid Pulse run `alert` does not use severity at all, so "
            "this is where the classifier's opinion is reported."
        ),
    )
    signals_disagree: Optional[bool] = Field(default=None, description=SIGNALS_DISAGREE_DESCRIPTION)
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
    ef_is_fallback: Optional[bool] = Field(
        default=None,
        description=(
            "True when ejection_fraction_pct above was NOT measured and the Tier-1 healthy-population "
            "default was used instead (docs/data_provenance.md). The default gives Pulse a "
            "structurally normal heart and also feeds the classifier, so it can make a sick patient "
            "look LOW-risk for any scenario_type. None for assessments that predate this field."
        ),
    )
    bnp_is_fallback: Optional[bool] = Field(
        default=None,
        description="True when nt_probnp_pg_ml above was the Tier-1 fallback default, not measured.",
    )
    vital_slopes: Optional[dict] = None
    created_at: datetime.datetime
    personalisation: Optional[dict] = Field(
        default=None,
        description=(
            "Present only when an experimental personalisation flag was on for this run: "
            "{'bcg': {...inputs, 'modifiers', 'applied', 'note'?}, 'hr_baseline': {'requested_bpm', "
            "'simulated_bpm', 'applied', 'note'?}}. When anything was applied, risk_caveats also "
            "carries the experimental caveat."
        ),
    )


# ---- Status / History / Projection / Report ----

class StatusResponse(BaseModel):
    patient_id: str
    simulation_status: Literal["collecting", "pending", "running", "complete", "failed"]
    reading_count: int
    latest_assessment: Optional[RiskAssessmentPayload] = None
    latest_assessment_stale: bool = Field(
        default=False,
        description=(
            "True when a SimulationRun newer than `latest_assessment` failed -- the assessment "
            "shown is from an earlier run and no longer reflects the patient's latest "
            "classification. `simulation_status` is 'failed' in this case, not 'complete'."
        ),
    )
    current_alert: Optional[dict] = Field(
        default=None,
        description=(
            "LEGACY diagnostic payload (src.analytics.score_reporting.build_score_report()'s "
            "shape) -- kept for its severity_score/severity_band/confidence/simulation_status "
            "fields. Its own 'alert'/'alert_basis' keys are SUPERSEDED by the `alert` field below "
            "and must not be used for alert/watch state -- see `alert`'s description."
        ),
    )
    alert: Optional[AlertReportPayload] = Field(
        default=None,
        description=(
            "THE alert decision (fix/unified-alert-decision) -- src.analytics.score_reporting."
            "decide_alert()'s output. The single source of truth across this API and every "
            "consumer, frontend included; nothing else (not `current_alert`, not a frontend's own "
            "risk_bucket=='HIGH' check) should be read for alert/watch state. None only when "
            "there is nothing to decide from yet (no run, no failure -- `simulation_status` is "
            "'collecting' or 'pending')."
        ),
    )
    ml_severity_alert: Optional[MlSeverityAlertPayload] = Field(
        default=None,
        description=(
            "ML Model 1's own severity signal for the same run `alert` is about (the latest run "
            "when it failed, otherwise latest_assessment's), reported separately from the twin "
            "(fix/alert-both-signals)."
        ),
    )
    signals_disagree: Optional[bool] = Field(default=None, description=SIGNALS_DISAGREE_DESCRIPTION)
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


# ---- Twin state (feature/wire-research-features) ----

class TwinStateResponse(BaseModel):
    """GET /patients/{id}/twin-state -- what the dashboard's twin-state panel shows."""
    patient_id: str
    flags: dict = Field(description="Current value of every research feature flag (src/feature_flags.py).")
    pipeline_mode: Literal["fresh", "continuous"]
    state_started_at: Optional[datetime.datetime] = Field(
        default=None,
        description="When the current continuous Pulse state began (its initial run). None before the "
        "first continuous run, right after a reset, or for a patient only ever run in fresh mode.",
    )
    state_simulation_time_s: Optional[float] = None
    state_days: int = Field(default=0, description="Successful daily runs in the current state.")
    engine_lag_days: int = Field(
        default=0,
        description="Failed daily runs since the current state began. Each one leaves the simulated "
        "clock one 600 s encounter behind the calendar; there is no catch-up.",
    )
    days_since_exercise_label: Optional[int] = Field(
        default=None,
        description="Successful daily runs since the last one that added an Exercise action "
        "(cardiac_stress / acute_deterioration on a resumed day). 0 = the latest run. None if none in "
        "the current state. Exercise stays active in the saved state after it is applied.",
    )
    last_exercise_scenario_type: Optional[str] = None
    hfref_condition_mismatch: bool = Field(
        default=False,
        description="True when the latest EF is on the other side of the 40% HFrEF cutoff from the EF "
        "the current state started with. The chronic-dysfunction condition can only be set when a state "
        "starts, so the twin cannot follow this change until it is reset.",
    )
    last_reset_at: Optional[datetime.datetime] = None
    reset_pending: bool = Field(
        default=False, description="A reset was requested and no run has started a new state since."
    )


class ResetStateResponse(BaseModel):
    patient_id: str
    reset_requested_at: datetime.datetime
    pipeline_mode: Literal["fresh", "continuous"]
    message: str
