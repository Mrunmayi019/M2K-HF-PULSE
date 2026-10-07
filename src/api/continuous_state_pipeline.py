"""Continuous-state-sync feature (feature/continuous-state-sync branch, 2026-08-30): the new
daily pipeline that resumes a patient's Pulse state instead of rebuilding it from scratch every
time. Deliberately a separate module from src/api/services.py.

Wired to POST /patients/{id}/wearable-sync when PIPELINE_MODE=continuous (feature/wire-research-
features); the default, PIPELINE_MODE=fresh, never calls into this module from the API. The
scenario-test harness (src/evaluation/scenario_tests/run_patient_seed.py) calls
run_daily_continuous_pipeline() directly, independent of the flag.

Behaviour added by feature/wire-research-features (each case is pinned by
tests/test_continuous_mode.py):
  - Two runs for the same patient at once: a per-patient lock serialises them inside one
    process, so the second resumes from the first's saved state instead of both resuming from the
    same parent and one day being lost. Not a cross-process lock: with several uvicorn workers
    (or the API plus a script on the same DB) two runs can still fork the state; the API runs one
    worker (docker-compose.yml) and this is documented, not solved.
  - Readings sent out of order: routes.py only triggers a run when the new reading's date is
    after every earlier reading's. An older or same-date reading is stored and joins the window
    from the next run on; the twin is never rewound. The engine advances one 600 s encounter per
    run, not per calendar day, so a gap in dates is not simulated as elapsed time either.
  - A clinical report that changes mid-stream: picked up on the next run by report id (not by
    timestamp, which skipped a report submitted while a run was in progress). EF is reapplied
    through the reissued CardiovascularMechanicsModification. If the new EF crosses the 40% HFrEF
    cutoff, the ChronicVentricularSystolicDysfunction condition cannot follow (it is only set when
    a state starts) -- reported as hfref_condition_mismatch on GET /twin-state; only a manual reset
    fixes it. There is no automatic reset rule.
  - POST /patients/{id}/reset-state: the next run ignores every PulseState saved before the
    latest reset and starts a fresh one (initial run). Nothing is deleted.

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
import threading

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
from src import feature_flags
from src.api.services import (
    WEARABLE_WINDOW_DAYS,
    apply_tier1_fallback,
    build_risk_caveats,
    get_wearable_window,
    latest_clinical_report,
    mark_simulation_run_failed,
    resolve_hysteresis_state,
    resolve_scenario_type,
)
from src.data_synthesis.generate_patients import load_reference_stats
from src.patient_builder import personalisation
from src.patient_builder.patient_file import build_patient_file, ef_to_cardiovascular_modifiers
from src.patient_builder.scenario_file import STABILIZATION_S
from src.pulse_runner.cli_state_runner import resume_and_advance, run_initial
from src.pulse_runner.cli_state_scenario import build_exercise_action
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

# One lock per patient, so two runs for the same patient in this process happen one after the
# other (see module docstring). Different patients still run in parallel.
_patient_locks: dict[str, threading.Lock] = {}
_patient_locks_guard = threading.Lock()


def _patient_lock(patient_id: str) -> threading.Lock:
    with _patient_locks_guard:
        return _patient_locks.setdefault(patient_id, threading.Lock())


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


def latest_reset(db: Session, patient_id: str) -> models.TwinStateReset | None:
    return (
        db.query(models.TwinStateReset)
        .filter(models.TwinStateReset.patient_id == patient_id)
        .order_by(models.TwinStateReset.requested_at.desc(), models.TwinStateReset.id.desc())
        .first()
    )


def current_state(db: Session, patient_id: str) -> models.PulseState | None:
    """The PulseState the next run resumes from: the newest one saved after the latest reset, or
    None (next run is an initial run). Older states stay in the table as history."""
    query = db.query(models.PulseState).filter(models.PulseState.patient_id == patient_id)
    reset = latest_reset(db, patient_id)
    if reset is not None:
        query = query.filter(models.PulseState.saved_at > reset.requested_at)
    return query.order_by(models.PulseState.saved_at.desc(), models.PulseState.id.desc()).first()


def _resolve_clinical_values(
    db: Session, patient_id: str, last_state: models.PulseState | None
) -> tuple[float, float, bool, bool, bool]:
    """Returns (ejection_fraction_pct, nt_probnp_pg_ml, is_new_report_since_last_resume,
    ef_is_fallback, bnp_is_fallback).

    Multi-rate: only adopts a ClinicalReport's values if it arrived after the last saved
    PulseState (or none exists yet, i.e. day 1) -- otherwise reuses the EF the last state was
    computed with, so EF doesn't silently drift day-to-day with no new clinical data behind it.

    "Arrived after" is decided by report id when the last state recorded which report it used
    (feature/wire-research-features); comparing reported_at with saved_at skipped a report that
    was submitted while a run was in progress (reported before the run saved, but after it read
    its inputs). States saved before that column existed fall back to the timestamp comparison.
    """
    latest_report = latest_clinical_report(db, patient_id)

    if latest_report is None:
        ef, bnp, ef_is_fallback, bnp_is_fallback = apply_tier1_fallback(None, None)
        return ef, bnp, last_state is None, ef_is_fallback, bnp_is_fallback

    if last_state is None:
        is_new = True
    elif last_state.clinical_report_id is not None:
        is_new = latest_report.id != last_state.clinical_report_id
    else:
        is_new = latest_report.reported_at > last_state.saved_at
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
    with _patient_lock(patient_id):
        return _run_daily_continuous_pipeline(patient_id, db, compute_projection)


def run_continuous_pipeline_task(patient_id: str, session_factory) -> None:
    """BackgroundTasks entry point for PIPELINE_MODE=continuous (routes.py). Opens its own session,
    same as services.run_assessment_pipeline()."""
    db = session_factory()
    try:
        run_daily_continuous_pipeline(patient_id, db)
    except NotEnoughDataError:
        logger.warning("continuous pipeline: window not full yet for patient_id=%s", patient_id)
    finally:
        db.close()


def _continuous_personalisation(
    report, last_state: models.PulseState | None
) -> tuple[dict | None, float | None, dict | None]:
    """ENABLE_BCG_MODIFIERS / ENABLE_HR_BASELINE in continuous mode. Returns (extra_modifiers for
    the reissued CardiovascularMechanicsModification, hr_baseline_bpm for an initial run's patient
    file, record).

    BCG modifiers are reissued with the core modification every day, so they apply on every day
    including stable ones (unlike fresh mode, where a stable day has no modification action).
    The HR baseline lives in the patient file, which Pulse only reads on an initial run: it is set
    when a state starts and carried by that state until a reset, whatever the flag or the report
    says later. The record says so whenever the two disagree."""
    record: dict = {}
    extra = None
    hr_for_initial = None

    if feature_flags.bcg_modifiers_enabled() and personalisation.report_has_bcg(report):
        extra = personalisation.bcg_modifiers_for(report)
        record["bcg"] = personalisation.bcg_record(report, extra, applied=True)

    requested = report.hr_baseline_bpm if report is not None else None
    if last_state is None:
        if feature_flags.hr_baseline_enabled() and requested is not None:
            hr_for_initial = requested
            record["hr_baseline"] = personalisation.hr_baseline_record(requested, applied=True)
    elif last_state.hr_baseline_bpm is not None:
        note = "set when the current state started; Pulse does not re-read the patient file on resume"
        if requested != last_state.hr_baseline_bpm:
            note += f"; the latest report says {requested}, which needs a twin reset to take effect"
        record["hr_baseline"] = personalisation.hr_baseline_record(last_state.hr_baseline_bpm, True, note)
    elif feature_flags.hr_baseline_enabled() and requested is not None:
        record["hr_baseline"] = personalisation.hr_baseline_record(
            requested, False, "the current state started without an HR baseline; reset the twin to apply it"
        )

    if not record:
        return None, None, None
    record["projection_personalised"] = False
    return extra, hr_for_initial, record


def _run_daily_continuous_pipeline(
    patient_id: str, db: Session, compute_projection: bool
) -> models.PulseState | None:
    patient = db.get(models.Patient, patient_id)
    if patient is None:
        raise ValueError(f"no such patient: {patient_id}")

    trends_df = get_wearable_window(db, patient_id, n=WEARABLE_WINDOW_DAYS)
    if trends_df is None:
        raise NotEnoughDataError(
            f"patient {patient_id} has fewer than {WEARABLE_WINDOW_DAYS} wearable readings"
        )

    last_state = current_state(db, patient_id)

    ejection_fraction_pct, nt_probnp_pg_ml, _, ef_is_fallback, bnp_is_fallback = _resolve_clinical_values(
        db, patient_id, last_state
    )
    latest_report = latest_clinical_report(db, patient_id)

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
    raw_scenario_type = str(clf.predict(features_df[cols])[0])
    severity = float(reg.predict(features_df[cols])[0])
    scenario_type = resolve_scenario_type(db, patient_id, raw_scenario_type)
    bcg_extra, hr_baseline_bpm, personalisation_record = _continuous_personalisation(latest_report, last_state)
    exercise_applied = last_state is not None and build_exercise_action(scenario_type, severity) is not None

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
        pipeline_mode="continuous",
        raw_scenario_type=raw_scenario_type,
        severity_hysteresis_state=resolve_hysteresis_state(db, patient_id, severity),
        personalisation_json=personalisation_record,
        exercise_applied=exercise_applied,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Pulse-call kwargs are only passed when a flag produced something, so a flag-off run makes
    # exactly the call it always made (tests mock these functions and check their arguments).
    flag_kwargs = {"extra_modifiers": bcg_extra} if bcg_extra else {}

    try:
        if last_state is None:
            patient_path = output_dir / "patient.json"
            patient_path.write_text(json.dumps(build_patient_file(demo_row, hr_baseline_bpm=hr_baseline_bpm), indent=2))

            new_state_json, snap, df = run_initial(
                patient_json_path=str(patient_path),
                ejection_fraction_pct=ejection_fraction_pct,
                severity=severity,
                stabilization_s=STABILIZATION_S,
                duration_s=DAILY_ENCOUNTER_DURATION_S,
                **flag_kwargs,
            )
        else:
            new_state_json, snap, df = resume_and_advance(
                state_json=last_state.state_json,
                ejection_fraction_pct=ejection_fraction_pct,
                severity=severity,
                duration_s=DAILY_ENCOUNTER_DURATION_S,
                prior_offset_s=last_state.simulation_time_s,
                scenario_type=scenario_type,
                **flag_kwargs,
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

    saved_at = datetime.datetime.now(datetime.timezone.utc)
    if last_state is None:
        state_started_at = saved_at
        hfref_condition_applied = ef_to_cardiovascular_modifiers(ejection_fraction_pct, severity)[
            "apply_systolic_dysfunction_condition"
        ]
        state_hr_baseline = hr_baseline_bpm
    else:
        state_started_at = last_state.state_started_at
        hfref_condition_applied = last_state.hfref_condition_applied
        state_hr_baseline = last_state.hr_baseline_bpm
    new_state = models.PulseState(
        patient_id=patient_id,
        state_json=new_state_json,
        last_ejection_fraction_pct=ejection_fraction_pct,
        last_severity=severity,
        simulation_time_s=snap["simulation_time_s"],
        saved_at=saved_at,
        state_started_at=state_started_at,
        clinical_report_id=latest_report.id if latest_report is not None else None,
        hfref_condition_applied=hfref_condition_applied,
        hr_baseline_bpm=state_hr_baseline,
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

    risk_caveats = build_risk_caveats(scenario_type, ef_is_fallback, risk["risk_bucket"], personalisation_record)

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
