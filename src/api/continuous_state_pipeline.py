"""Continuous-state-sync feature (feature/continuous-state-sync branch, 2026-08-30): the new
daily pipeline that resumes a patient's Pulse state instead of rebuilding it from scratch every
time. Deliberately a separate module from src/api/services.py -- nothing there is modified, and
nothing currently calls into this module. Not wired into any route yet; that integration is
explicitly out of scope until this is reviewed and approved.

Multi-rate update strategy:
  - severity/scenario_type: recomputed EVERY resume (fast-rate) -- driven by the 21-day sliding
    wearable window, which shifts daily, same classifier services.py already uses.
  - ejection_fraction_pct/nt_probnp_pg_ml: only updated when a NEW ClinicalReport has arrived
    since the last saved PulseState (slow-rate) -- otherwise the last-used values carry forward
    unchanged. Clinical reports (echo/labs) don't arrive daily in reality; re-deriving EF from
    nothing every day would be fabricating data that doesn't exist.
  - CardiovascularMechanicsModification: reissued on EVERY resume regardless of whether EF/BNP
    changed -- required for correctness (see src/pulse_runner/sdk_runner.py's module docstring,
    re-verified at the CLI layer in docs/continuous_state_sync_status.md), not just to reflect new
    data. Uses whatever ejection_fraction_pct/severity apply that day (carried-forward EF +
    freshly recomputed severity, or a newly-arrived EF).
  - Exercise (today's fresh scenario-specific action): applied every resume based on that day's
    freshly-classified scenario_type -- see cli_state_scenario.build_exercise_action().

RiskAssessment/SimulationRun (2026-09-01, Step 3): each day's encounter also produces a real
SimulationRun + RiskAssessment row, via the SAME analytics code src/api/services.py's from-scratch
pipeline already uses (analyze_simulation, compute_risk_score, classify_nyha,
compute_deterioration_rate, project_physiology) -- fed by this pipeline's own Pulse output instead
of a fresh from-scratch run. This is deliberate reuse, not a parallel implementation: it's what
lets the existing API endpoints (/status, /history, /projection, /report) and frontend display a
continuous-synced patient with zero changes to either.

CAVEAT worth flagging (not a bug, a semantic difference from the from-scratch pipeline): on day 1
(run_initial), the returned df spans stabilize+CVMod+advance, so hr_rise/map_drop/co_drop_pct
measure the same "healthy baseline -> modified+advanced end state" swing services.py's pipeline
measures. On day 2+ (resume_and_advance), the df spans only THAT day's reissue+[Exercise]+advance
window (no stabilization -- already done on a prior day), so those same deltas measure "state
right after today's reissue -> end of today's advance", not "healthy baseline -> now". This is an
arguably more natural notion for a continuous-monitoring feature (how much did today's encounter
move the patient), but it is NOT numerically the same quantity the from-scratch pipeline computes,
and risk_score.py/staging.py were calibrated against the from-scratch semantics. Flagged for
review before this feature is used for anything beyond a demo; not resolved here.
"""
from __future__ import annotations

import datetime
import json
import pathlib

import joblib
from sqlalchemy.orm import Session

from src.analytics.deterioration_rate import (
    SD_RATE_TO_RISK_SCORE_PER_DAY,
    compute_deterioration_rate,
    days_to_next_stage,
)
from src.analytics.projection import DEFAULT_HORIZONS_DAYS, project_physiology
from src.analytics.risk_score import compute_risk_score
from src.analytics.simulation_features import analyze_simulation, extract_waveform_data
from src.analytics.staging import classify_nyha
from src.api import models
from src.api.services import (
    EF_FALLBACK_MASKS_FLUID_OVERLOAD_CAVEAT_MESSAGE,
    FLUID_OVERLOAD_CAVEAT_MESSAGE,
    WEARABLE_WINDOW_DAYS,
    apply_tier1_fallback,
    get_wearable_window,
)
from src.data_synthesis.generate_patients import load_reference_stats
from src.patient_builder.patient_file import build_patient_file
from src.patient_builder.scenario_file import STABILIZATION_S
from src.pulse_runner.cli_state_runner import PulseSdkError, resume_and_advance, run_initial
from src.scenario_classifier.features import build_inference_features, feature_columns

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
MODELS_DIR = REPO_ROOT / "models"
SCENARIOS_DIR = pathlib.Path("/workspace/scenarios/continuous_state")

# Matches the existing pipeline's single-encounter convention (services.py's
# `expected_duration_s = STABILIZATION_S + 10.0 * 60`) -- kept consistent so risk_score.py's
# clinically-anchored features are measuring the same kind of window they were calibrated against
# (see module docstring's CAVEAT for the one respect in which this isn't fully true on resumes).
DAILY_ENCOUNTER_DURATION_S = 10.0 * 60

_model_cache: dict[str, object] = {}


class NotEnoughDataError(Exception):
    """Raised when the 21-day wearable window isn't full yet -- same gate services.py's pipeline
    already uses; the daily resume pipeline doesn't run before then either."""


def _load_scenario_classifier_models() -> tuple[object, object]:
    """Independent of services.py's own _model_cache -- deliberately not importing that private,
    module-level cache, to keep this feature fully decoupled from the pipeline it must not touch."""
    if "clf" not in _model_cache:
        _model_cache["clf"] = joblib.load(MODELS_DIR / "scenario_classifier.joblib")
        _model_cache["reg"] = joblib.load(MODELS_DIR / "severity_regressor.joblib")
    return _model_cache["clf"], _model_cache["reg"]


def _resolve_clinical_values(
    db: Session, patient_id: str, last_state: models.PulseState | None
) -> tuple[float, float, bool, bool]:
    """Returns (ejection_fraction_pct, nt_probnp_pg_ml, is_new_report_since_last_resume,
    ef_is_fallback).

    Multi-rate: only adopts a ClinicalReport's values if it arrived after the last saved
    PulseState (or none exists yet, i.e. day 1) -- otherwise reuses the EF the last state was
    computed with, so EF doesn't silently drift day-to-day with no new clinical data behind it.
    """
    latest_report = (
        db.query(models.ClinicalReport)
        .filter(models.ClinicalReport.patient_id == patient_id)
        .order_by(models.ClinicalReport.reported_at.desc())
        .first()
    )

    if latest_report is None:
        ef, bnp, ef_is_fallback, _ = apply_tier1_fallback(None, None)
        return ef, bnp, last_state is None, ef_is_fallback

    is_new = last_state is None or latest_report.reported_at > last_state.saved_at
    if is_new:
        return (
            latest_report.ejection_fraction_pct,
            latest_report.nt_probnp_pg_ml,
            True,
            latest_report.ef_is_fallback,
        )

    # No new report since last resume -- carry the EF that was actually used last time forward,
    # not a fresh apply_tier1_fallback() call (which could silently override it with the healthy
    # default if latest_report happens to be older than expected in some edge case).
    return (
        last_state.last_ejection_fraction_pct,
        latest_report.nt_probnp_pg_ml,
        False,
        latest_report.ef_is_fallback,
    )


def run_daily_continuous_pipeline(patient_id: str, db: Session) -> models.PulseState:
    """One day's continuous-state-sync step. Raises NotEnoughDataError if the 21-day wearable
    window isn't full yet (same gate as services.py's existing pipeline). Returns the newly
    created PulseState row (already committed) -- a SimulationRun + RiskAssessment row are also
    created as a side effect (see module docstring), discoverable via the normal
    /patients/{id}/status|history|projection|report endpoints like any other assessment.
    """
    patient = db.get(models.Patient, patient_id)
    if patient is None:
        raise ValueError(f"no such patient: {patient_id}")

    trends_df = get_wearable_window(db, patient_id, n=WEARABLE_WINDOW_DAYS)
    if trends_df is None:
        raise NotEnoughDataError(
            f"patient {patient_id} has fewer than {WEARABLE_WINDOW_DAYS} wearable readings"
        )

    last_state = (
        db.query(models.PulseState)
        .filter(models.PulseState.patient_id == patient_id)
        .order_by(models.PulseState.saved_at.desc())
        .first()
    )

    ejection_fraction_pct, nt_probnp_pg_ml, _, ef_is_fallback = _resolve_clinical_values(
        db, patient_id, last_state
    )

    bmi = patient.weight_kg / (patient.height_cm / 100.0) ** 2
    ml_row = {
        "patient_id": patient_id,
        "age": patient.age,
        "sex": patient.sex,
        "bmi": bmi,
        "ejection_fraction_pct": ejection_fraction_pct,
        "nt_probnp_pg_ml": nt_probnp_pg_ml,
    }
    demo_row = {
        "patient_id": patient_id,
        "sex": patient.sex,
        "age": patient.age,
        "height_cm": patient.height_cm,
        "weight_kg": patient.weight_kg,
        # project_physiology()'s _run_at_severity() needs this alongside the demographic fields,
        # same as services.py's own demo_row.
        "ejection_fraction_pct": ejection_fraction_pct,
    }
    clf, reg = _load_scenario_classifier_models()
    features_df = build_inference_features(ml_row, trends_df)
    cols = feature_columns(features_df)
    scenario_type = str(clf.predict(features_df[cols])[0])
    severity = float(reg.predict(features_df[cols])[0])

    output_dir = SCENARIOS_DIR / patient_id
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        if last_state is None:
            patient_path = output_dir / "patient.json"
            patient_path.write_text(json.dumps(build_patient_file(demo_row), indent=2))

            new_state_json, snap, df = run_initial(
                patient_json_path=str(patient_path),
                ejection_fraction_pct=ejection_fraction_pct,
                severity=severity,
                stabilization_s=STABILIZATION_S,
                duration_s=DAILY_ENCOUNTER_DURATION_S,
            )
        else:
            new_state_json, snap, df = resume_and_advance(
                state_json=last_state.state_json,
                ejection_fraction_pct=ejection_fraction_pct,
                severity=severity,
                duration_s=DAILY_ENCOUNTER_DURATION_S,
                prior_offset_s=last_state.simulation_time_s,
                scenario_type=scenario_type,
            )
    except PulseSdkError:
        raise

    new_state = models.PulseState(
        patient_id=patient_id,
        state_json=new_state_json,
        last_ejection_fraction_pct=ejection_fraction_pct,
        last_severity=severity,
        simulation_time_s=snap["simulation_time_s"],
        saved_at=datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(new_state)

    # --- SimulationRun + RiskAssessment, via the same analytics code services.py uses (Step 3) ---
    run = models.SimulationRun(
        patient_id=patient_id,
        scenario_type=scenario_type,
        severity=severity,
        status="complete",
        started_at=datetime.datetime.now(datetime.timezone.utc),
        completed_at=datetime.datetime.now(datetime.timezone.utc),
        waveform_data=extract_waveform_data(df),
    )
    db.add(run)
    db.flush()  # assigns run.id without a second round-trip commit

    sim_features = analyze_simulation(df)
    risk = compute_risk_score(
        hr_rise=sim_features["hr_rise"],
        map_drop=sim_features["map_drop"],
        co_drop_pct=sim_features["co_drop_pct"],
        compensation_flag=sim_features["compensation_flag"],
        instability_flag=sim_features["instability_flag"],
        map_start=sim_features["map_start"],
    )
    nyha_class = classify_nyha(
        ejection_fraction_pct=ejection_fraction_pct,
        nt_probnp_pg_ml=nt_probnp_pg_ml,
        age=patient.age,
        risk_score=risk["risk_score"],
        instability_flag=sim_features["instability_flag"],
    )
    rate_info = compute_deterioration_rate(trends_df)
    days_forward = days_to_next_stage(risk["risk_score"], rate_info["composite_rate"])

    projection = project_physiology(
        patient=demo_row,
        scenario_type=scenario_type,
        current_severity=severity,
        deterioration_rate_per_day=rate_info["composite_rate"] * SD_RATE_TO_RISK_SCORE_PER_DAY,
        horizons=DEFAULT_HORIZONS_DAYS,
        output_dir=output_dir / "projection",
    )
    projection_json = {
        str(horizon): {
            "projected_severity": r["projected_severity"],
            "risk_score": r.get("risk_score"),
            "risk_bucket": r.get("risk_bucket"),
            "status": r["status"],
        }
        for horizon, r in projection.items()
    }

    if scenario_type != "fluid_overload":
        risk_caveats = None
    elif ef_is_fallback and risk["risk_bucket"] == "LOW":
        risk_caveats = EF_FALLBACK_MASKS_FLUID_OVERLOAD_CAVEAT_MESSAGE
    else:
        risk_caveats = FLUID_OVERLOAD_CAVEAT_MESSAGE

    db.add(
        models.RiskAssessment(
            patient_id=patient_id,
            simulation_run_id=run.id,
            risk_score=risk["risk_score"],
            risk_bucket=risk["risk_bucket"],
            component_scores=risk["component_scores"],
            baseline_deficit_score=risk["baseline_deficit_score"],
            dominant_mechanism=risk["dominant_mechanism"],
            nyha_class=nyha_class,
            risk_caveats=risk_caveats,
            deterioration_direction=rate_info["direction"],
            days_to_next_stage=days_forward,
            projection_json=projection_json,
            ejection_fraction_pct=ejection_fraction_pct,
            nt_probnp_pg_ml=nt_probnp_pg_ml,
            vital_slopes=rate_info["vital_slopes"],
        )
    )

    db.commit()
    db.refresh(new_state)
    return new_state
