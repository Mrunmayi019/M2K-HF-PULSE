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
import logging
import pathlib

import joblib
from sqlalchemy.orm import Session

from src.analytics.deterioration_rate import (
    compute_deterioration_rate,
    days_to_next_stage,
)
from src.analytics.projection import DEFAULT_HORIZONS_DAYS, project_physiology
from src.analytics.risk_score import compute_risk_score
from src.analytics.score_reporting import compute_baseline_high_streak
from src.analytics.simulation_features import analyze_simulation, extract_waveform_data
from src.analytics.staging import classify_nyha
from src.api import models
from src.api.services import (
    WEARABLE_WINDOW_DAYS,
    apply_tier1_fallback,
    build_risk_caveats,
    get_wearable_window,
    mark_simulation_run_failed,
)
from src.data_synthesis.generate_patients import load_reference_stats
from src.patient_builder.patient_file import build_patient_file
from src.patient_builder.scenario_file import STABILIZATION_S
from src.pulse_runner.cli_state_runner import resume_and_advance, run_initial
from src.scenario_classifier.features import build_inference_features, feature_columns

logger = logging.getLogger(__name__)

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
) -> tuple[float, float, bool, bool, bool]:
    """Returns (ejection_fraction_pct, nt_probnp_pg_ml, is_new_report_since_last_resume,
    ef_is_fallback, bnp_is_fallback).

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
        ef, bnp, ef_is_fallback, bnp_is_fallback = apply_tier1_fallback(None, None)
        return ef, bnp, last_state is None, ef_is_fallback, bnp_is_fallback

    is_new = last_state is None or latest_report.reported_at > last_state.saved_at
    if is_new:
        return (
            latest_report.ejection_fraction_pct,
            latest_report.nt_probnp_pg_ml,
            True,
            latest_report.ef_is_fallback,
            latest_report.bnp_is_fallback,
        )

    # No new report since last resume -- carry the EF that was actually used last time forward,
    # not a fresh apply_tier1_fallback() call (which could silently override it with the healthy
    # default if latest_report happens to be older than expected in some edge case).
    return (
        last_state.last_ejection_fraction_pct,
        latest_report.nt_probnp_pg_ml,
        False,
        latest_report.ef_is_fallback,
        latest_report.bnp_is_fallback,
    )


def run_daily_continuous_pipeline(
    patient_id: str, db: Session, compute_projection: bool = True
) -> models.PulseState | None:
    """One day's continuous-state-sync step. Raises NotEnoughDataError if the 21-day wearable
    window isn't full yet (same gate as services.py's existing pipeline). On success, returns the
    newly created PulseState row (already committed) -- a SimulationRun + RiskAssessment row are
    also created as a side effect (see module docstring), discoverable via the normal
    /patients/{id}/status|history|projection|report endpoints like any other assessment.

    `compute_projection` (default True, preserving exact prior behavior): set False to skip the
    project_physiology() call and store `projection_json=None` instead -- test/scenario-test-only,
    for wall-time (project_physiology() makes 3 extra real Pulse calls per day, one per horizon).
    Safe because projection is a pure write-only, display-only side effect of this day's
    assessment (docs/integration_pre_results.md) -- risk_score, nyha_class, the alert decision, and
    what the next day's PulseState reads back are all computed before this call and never read
    projection output back. Production/demo code paths never pass False.

    On a Pulse failure (run_initial()/resume_and_advance() raising), returns None instead of
    raising -- a SimulationRun(status="failed") row is recorded first via services.mark_
    simulation_run_failed(), the exact same helper and shape _run_assessment_pipeline() uses on
    failure, so routes.py's _build_status() and the unstable-run alert fallback (fix/unstable-
    alert-fallback) work identically regardless of which pipeline produced the failure. No
    PulseState row is created on failure -- the most recent PulseState (queried fresh as
    `last_state` below, every call) remains whatever the last *successful* day wrote, so the next
    call resumes from the last good state automatically; this was already true before that change
    (PulseState rows are append-only and the old code only ever constructed one after a successful
    run_initial()/resume_and_advance() call), not a new guarantee added then.
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

    ejection_fraction_pct, nt_probnp_pg_ml, _, ef_is_fallback, bnp_is_fallback = _resolve_clinical_values(
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

    # --- SimulationRun created BEFORE the Pulse call, same ordering as services.py's
    # _run_assessment_pipeline(): if Pulse fails below, this row is already committed and can be
    # marked "failed" in place, giving routes.py's _build_status() / the unstable-run alert
    # fallback the same SimulationRun(status="failed") shape regardless of pipeline. ---
    run = models.SimulationRun(
        patient_id=patient_id,
        scenario_type=scenario_type,
        severity=severity,
        status="running",
        started_at=datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

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
    except Exception as e:
        # Mirrors services.py's defensive "never leave a run stuck at running" -- catches
        # PulseSdkError (the documented failure mode) and anything else unexpected alike, but
        # ONLY around the two Pulse-call branches above -- nothing after this except block (the
        # PulseState write, risk scoring, projection, the RiskAssessment insert) is in scope, so a
        # non-Pulse bug there still raises normally and is never recorded as a Pulse failure. No
        # PulseState row is created here: the most recent PulseState queried as `last_state` above
        # is unaffected, so the next call's `last_state` lookup still resumes from the last
        # genuinely successful day, not this failed one.
        logger.exception(
            "run_daily_continuous_pipeline: Pulse execution failed for patient_id=%s (run_id=%s)",
            patient_id, run.id,
        )
        mark_simulation_run_failed(db, run, f"{type(e).__name__}: {e}")
        return None

    new_state = models.PulseState(
        patient_id=patient_id,
        state_json=new_state_json,
        last_ejection_fraction_pct=ejection_fraction_pct,
        last_severity=severity,
        simulation_time_s=snap["simulation_time_s"],
        saved_at=datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(new_state)

    # --- RiskAssessment, via the same analytics code services.py uses (Step 3) ---
    run.waveform_data = extract_waveform_data(df)

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

    if compute_projection:
        projection = project_physiology(
            patient=demo_row,
            scenario_type=scenario_type,
            current_severity=severity,
            # Raw, scale-agnostic rate -- project_physiology()/project_severity() do their own
            # severity-scoped conversion internally. Passing a risk_score-pre-converted rate here
            # (SD_RATE_TO_RISK_SCORE_PER_DAY) was the bug fixed 2026-09-10 in services.py
            # (docs/methodology.md Sec 8) -- this call site was never updated to match.
            composite_rate=rate_info["composite_rate"],
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
    else:
        # Test-only opt-out (docs/integration_pre_results.md): project_physiology() is a pure
        # write-only, display-only side effect of this day's assessment -- confirmed by tracing
        # every downstream consumer (risk_score, nyha_class, the alert decision, and what the
        # NEXT day's PulseState reads back all come from today's actual Pulse run, computed above
        # this block, never from projection output). Skipping it changes nothing else.
        projection_json = None

    risk_caveats = build_risk_caveats(scenario_type, ef_is_fallback, risk["risk_bucket"])

    # decide_alert()'s C3 persistence state -- O(1), reads only this patient's most recent prior
    # RiskAssessment (see compute_baseline_high_streak()'s docstring).
    previous_assessment = (
        db.query(models.RiskAssessment)
        .filter(models.RiskAssessment.patient_id == patient_id)
        .order_by(models.RiskAssessment.id.desc())
        .first()
    )
    streak_days, instability_seen = compute_baseline_high_streak(
        previous_streak_days=previous_assessment.baseline_high_streak_days if previous_assessment else None,
        previous_instability_seen=previous_assessment.instability_seen_in_streak if previous_assessment else None,
        risk_bucket=risk["risk_bucket"],
        dominant_mechanism=risk["dominant_mechanism"],
        instability_flag=sim_features["instability_flag"],
    )

    db.add(
        models.RiskAssessment(
            patient_id=patient_id,
            simulation_run_id=run.id,
            risk_score=risk["risk_score"],
            risk_bucket=risk["risk_bucket"],
            component_scores=risk["component_scores"],
            baseline_deficit_score=risk["baseline_deficit_score"],
            dominant_mechanism=risk["dominant_mechanism"],
            baseline_high_streak_days=streak_days,
            instability_seen_in_streak=instability_seen,
            nyha_class=nyha_class,
            risk_caveats=risk_caveats,
            deterioration_direction=rate_info["direction"],
            days_to_next_stage=days_forward,
            projection_json=projection_json,
            ejection_fraction_pct=ejection_fraction_pct,
            nt_probnp_pg_ml=nt_probnp_pg_ml,
            ef_is_fallback=ef_is_fallback,
            bnp_is_fallback=bnp_is_fallback,
            vital_slopes=rate_info["vital_slopes"],
        )
    )

    run.status = "complete"
    run.completed_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    db.refresh(new_state)
    return new_state
