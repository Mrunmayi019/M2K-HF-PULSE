"""Continuous-state-sync feature (feature/continuous-state-sync branch, 2026-08-30): the new
daily pipeline that resumes a patient's Pulse state instead of rebuilding it from scratch every
time. Deliberately a separate module from src/api/services.py -- nothing there is modified, and
nothing currently calls into this module. Not wired into any route yet; that integration (and
whatever changes to risk_score.py's baseline assumptions Sec 5's classifier re-check below flags)
is explicitly out of scope until this is reviewed and approved.

Multi-rate update strategy:
  - severity/scenario_type: recomputed EVERY resume (fast-rate) -- driven by the 21-day sliding
    wearable window, which shifts daily, same classifier services.py already uses.
  - ejection_fraction_pct/nt_probnp_pg_ml: only updated when a NEW ClinicalReport has arrived
    since the last saved PulseState (slow-rate) -- otherwise the last-used values carry forward
    unchanged. Clinical reports (echo/labs) don't arrive daily in reality; re-deriving EF from
    nothing every day would be fabricating data that doesn't exist.
  - CardiovascularMechanicsModification: reissued on EVERY resume regardless of whether EF/BNP
    changed -- required for correctness (see src/pulse_runner/sdk_runner.py's module docstring),
    not just to reflect new data. Uses whatever ejection_fraction_pct/severity apply that day
    (carried-forward EF + freshly recomputed severity, or a newly-arrived EF).
  - Exercise (today's fresh scenario-specific action): applied every resume based on that day's
    freshly-classified scenario_type -- see sdk_runner.build_exercise_action().
"""
from __future__ import annotations

import datetime
import json
import pathlib

import joblib
from sqlalchemy.orm import Session

from src.api import models
from src.api.services import WEARABLE_WINDOW_DAYS, apply_tier1_fallback, get_wearable_window
from src.data_synthesis.generate_patients import load_reference_stats
from src.patient_builder.patient_file import build_patient_file
from src.patient_builder.scenario_file import STABILIZATION_S
from src.pulse_runner.sdk_runner import PulseSdkError, resume_and_advance, run_initial
from src.scenario_classifier.features import build_inference_features, feature_columns

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
MODELS_DIR = REPO_ROOT / "models"
SCENARIOS_DIR = pathlib.Path("/workspace/scenarios/continuous_state")

# Matches the existing pipeline's single-encounter convention (services.py's
# `expected_duration_s = STABILIZATION_S + 10.0 * 60`) -- kept consistent so risk_score.py's
# clinically-anchored features, if this is later wired in, are measuring the same kind of window
# they were calibrated against. A design choice worth review, not an empirically re-derived value.
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
) -> tuple[float, float, bool]:
    """Returns (ejection_fraction_pct, nt_probnp_pg_ml, is_new_report_since_last_resume).

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
        ef, bnp, _, _ = apply_tier1_fallback(None, None)
        return ef, bnp, last_state is None

    is_new = last_state is None or latest_report.reported_at > last_state.saved_at
    if is_new:
        return latest_report.ejection_fraction_pct, latest_report.nt_probnp_pg_ml, True

    # No new report since last resume -- carry the EF that was actually used last time forward,
    # not a fresh apply_tier1_fallback() call (which could silently override it with the healthy
    # default if latest_report happens to be older than expected in some edge case).
    return last_state.last_ejection_fraction_pct, latest_report.nt_probnp_pg_ml, False


def run_daily_continuous_pipeline(patient_id: str, db: Session) -> models.PulseState:
    """One day's continuous-state-sync step. Raises NotEnoughDataError if the 21-day wearable
    window isn't full yet (same gate as services.py's existing pipeline). Returns the newly
    created PulseState row (already committed).
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

    ejection_fraction_pct, nt_probnp_pg_ml, _ = _resolve_clinical_values(db, patient_id, last_state)

    bmi = patient.weight_kg / (patient.height_cm / 100.0) ** 2
    ml_row = {
        "patient_id": patient_id,
        "age": patient.age,
        "sex": patient.sex,
        "bmi": bmi,
        "ejection_fraction_pct": ejection_fraction_pct,
        "nt_probnp_pg_ml": nt_probnp_pg_ml,
    }
    clf, reg = _load_scenario_classifier_models()
    features_df = build_inference_features(ml_row, trends_df)
    cols = feature_columns(features_df)
    scenario_type = str(clf.predict(features_df[cols])[0])
    severity = float(reg.predict(features_df[cols])[0])

    try:
        if last_state is None:
            demo_row = {
                "patient_id": patient_id,
                "sex": patient.sex,
                "age": patient.age,
                "height_cm": patient.height_cm,
                "weight_kg": patient.weight_kg,
            }
            output_dir = SCENARIOS_DIR / patient_id
            output_dir.mkdir(parents=True, exist_ok=True)
            patient_path = output_dir / "patient.json"
            patient_path.write_text(json.dumps(build_patient_file(demo_row), indent=2))

            new_state_json, snap = run_initial(
                patient_json_path=str(patient_path),
                ejection_fraction_pct=ejection_fraction_pct,
                severity=severity,
                stabilization_s=STABILIZATION_S,
                duration_s=DAILY_ENCOUNTER_DURATION_S,
            )
        else:
            new_state_json, snap = resume_and_advance(
                state_json=last_state.state_json,
                ejection_fraction_pct=ejection_fraction_pct,
                severity=severity,
                duration_s=DAILY_ENCOUNTER_DURATION_S,
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
    db.commit()
    db.refresh(new_state)
    return new_state
