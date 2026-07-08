"""Phase 6: business logic -- Tier 1 fallback defaults, wearable-window accumulation, and the
background assessment pipeline that BackgroundTasks runs after /wearable-sync.

The pipeline reuses every prior phase's code unchanged: src/scenario_classifier/ (ML Model 1),
src/patient_builder/ + src/pulse_runner/runner.py (Phase 2), src/analytics/simulation_features.py
(Phase 4), src/analytics/risk_score.py + staging.py + deterioration_rate.py + projection.py
(Phase 5). This module is the orchestration glue, not new modeling logic.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import traceback

import joblib
import pandas as pd
from sqlalchemy.orm import Session

from src.analytics.deterioration_rate import (
    SD_RATE_TO_RISK_SCORE_PER_DAY,
    compute_deterioration_rate,
    days_to_next_stage,
)
from src.analytics.projection import DEFAULT_HORIZONS_DAYS, project_physiology
from src.analytics.risk_score import compute_risk_score
from src.analytics.simulation_features import analyze_simulation
from src.analytics.staging import classify_nyha
from src.api import models
from src.data_synthesis.generate_patients import load_reference_stats
from src.patient_builder.patient_file import build_patient_file
from src.patient_builder.scenario_file import STABILIZATION_S, build_scenario_file
from src.pulse_runner.runner import PulseExecutionError, run_pulse
from src.scenario_classifier.features import build_inference_features, feature_columns

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
MODELS_DIR = REPO_ROOT / "models"
SCENARIOS_DIR = pathlib.Path("/workspace/scenarios/api")

WEARABLE_WINDOW_DAYS = 21
NT_PROBNP_FALLBACK_PG_ML = 100.0  # assumed_default -- see docs/data_provenance.md

FLUID_OVERLOAD_CAVEAT_MESSAGE = (
    "Detected scenario is fluid_overload -- risk_score is known to underestimate severity for "
    "this presentation (see docs/methodology.md §6.1). Do not rely on risk_score alone."
)

_model_cache: dict[str, object] = {}


class PatientNotFoundError(Exception):
    pass


# ---- Tier 1 fallback ----

def apply_tier1_fallback(
    ejection_fraction_pct: float | None, nt_probnp_pg_ml: float | None
) -> tuple[float, float, bool, bool]:
    """Returns (ejection_fraction_pct, nt_probnp_pg_ml, ef_is_fallback, bnp_is_fallback).

    Missing EF defaults to reference_stats.yaml's healthy-population mean (already flagged
    assumed_default there). Missing NT-proBNP defaults to a normal/unremarkable placeholder --
    see docs/data_provenance.md for why 100 pg/mL, well under even the youngest age band's
    diagnostic cutoff (450).
    """
    ef_is_fallback = ejection_fraction_pct is None
    bnp_is_fallback = nt_probnp_pg_ml is None

    if ef_is_fallback:
        ejection_fraction_pct = load_reference_stats()["ejection_fraction"]["healthy"]["mean"]
    if bnp_is_fallback:
        nt_probnp_pg_ml = NT_PROBNP_FALLBACK_PG_ML

    return ejection_fraction_pct, nt_probnp_pg_ml, ef_is_fallback, bnp_is_fallback


# ---- Wearable window ----

def get_wearable_window(db: Session, patient_id: str, n: int = WEARABLE_WINDOW_DAYS) -> pd.DataFrame | None:
    """Most recent `n` wearable_readings, reshaped into the (patient_id, day, <vitals>) format
    src/scenario_classifier/features.py's _wearable_features() expects. None if fewer than `n`
    readings exist yet.
    """
    readings = (
        db.query(models.WearableReading)
        .filter(models.WearableReading.patient_id == patient_id)
        .order_by(models.WearableReading.recorded_date.desc())
        .limit(n)
        .all()
    )
    if len(readings) < n:
        return None

    readings = sorted(readings, key=lambda r: r.recorded_date)
    return pd.DataFrame(
        [
            {
                "patient_id": patient_id,
                "day": i,
                "resting_hr_bpm": r.resting_hr_bpm,
                "spo2_pct": r.spo2_pct,
                "weight_kg": r.weight_kg,
                "steps_per_day": r.steps_per_day,
                "sleep_hours": r.sleep_hours,
                "hrv_rmssd_ms": r.hrv_rmssd_ms,
            }
            for i, r in enumerate(readings)
        ]
    )


# ---- Model loading (cached) ----

def _load_scenario_classifier_models() -> tuple[object, object]:
    if "clf" not in _model_cache:
        _model_cache["clf"] = joblib.load(MODELS_DIR / "scenario_classifier.joblib")
        _model_cache["reg"] = joblib.load(MODELS_DIR / "severity_regressor.joblib")
    return _model_cache["clf"], _model_cache["reg"]


# ---- Background pipeline ----

def run_assessment_pipeline(patient_id: str, session_factory) -> None:
    """Runs inside FastAPI's BackgroundTasks -- must open its own DB session (the request's
    session is already closed by the time this runs)."""
    db = session_factory()
    try:
        _run_assessment_pipeline(patient_id, db)
    finally:
        db.close()


def _run_assessment_pipeline(patient_id: str, db: Session) -> None:
    patient = db.get(models.Patient, patient_id)
    latest_report = (
        db.query(models.ClinicalReport)
        .filter(models.ClinicalReport.patient_id == patient_id)
        .order_by(models.ClinicalReport.reported_at.desc())
        .first()
    )
    ejection_fraction_pct = latest_report.ejection_fraction_pct if latest_report else None
    nt_probnp_pg_ml = latest_report.nt_probnp_pg_ml if latest_report else None
    ejection_fraction_pct, nt_probnp_pg_ml, _, _ = apply_tier1_fallback(
        ejection_fraction_pct, nt_probnp_pg_ml
    )

    trends_df = get_wearable_window(db, patient_id)
    if trends_df is None:
        return  # shouldn't happen -- caller only triggers this once the window is full

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
        # project_physiology()'s _run_at_severity() needs this alongside the demographic fields
        # (it calls both build_patient_file() and build_scenario_file() from the same dict).
        "ejection_fraction_pct": ejection_fraction_pct,
    }

    clf, reg = _load_scenario_classifier_models()
    features_df = build_inference_features(ml_row, trends_df)
    cols = feature_columns(features_df)
    scenario_type = clf.predict(features_df[cols])[0]
    severity = float(reg.predict(features_df[cols])[0])

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

    output_dir = SCENARIOS_DIR / patient_id
    output_dir.mkdir(parents=True, exist_ok=True)
    patient_path = output_dir / "patient.json"
    scenario_path = output_dir / "scenario.json"

    try:
        patient_path.write_text(json.dumps(build_patient_file(demo_row), indent=2))
        scenario = build_scenario_file(
            patient_json_path=str(patient_path),
            scenario_type=scenario_type,
            severity=severity,
            ejection_fraction_pct=ejection_fraction_pct,
        )
        scenario_path.write_text(json.dumps(scenario, indent=2))

        expected_duration_s = STABILIZATION_S + 10.0 * 60
        df = run_pulse(str(scenario_path), expected_duration_s=expected_duration_s, timeout_sec=180)
    except PulseExecutionError as e:
        run.status = "failed"
        run.error_message = str(e)
        run.scenario_json_path = str(scenario_path)
        run.completed_at = datetime.datetime.now(datetime.timezone.utc)
        db.commit()
        return
    except Exception as e:  # defensive: never leave a run stuck at "running" on an unexpected error
        run.status = "failed"
        run.error_message = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        run.completed_at = datetime.datetime.now(datetime.timezone.utc)
        db.commit()
        return

    sim_features = analyze_simulation(df)
    risk = compute_risk_score(
        hr_rise=sim_features["hr_rise"],
        map_drop=sim_features["map_drop"],
        co_drop_pct=sim_features["co_drop_pct"],
        compensation_flag=sim_features["compensation_flag"],
        instability_flag=sim_features["instability_flag"],
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

    risk_caveats = FLUID_OVERLOAD_CAVEAT_MESSAGE if scenario_type == "fluid_overload" else None

    db.add(
        models.RiskAssessment(
            patient_id=patient_id,
            simulation_run_id=run.id,
            risk_score=risk["risk_score"],
            risk_bucket=risk["risk_bucket"],
            component_scores=risk["component_scores"],
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
    run.status = "complete"
    run.completed_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
