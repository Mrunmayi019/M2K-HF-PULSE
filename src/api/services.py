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

from src.analytics.deterioration_rate import compute_deterioration_rate, days_to_next_stage
from src.analytics.projection import DEFAULT_HORIZONS_DAYS, project_physiology
from src.analytics.risk_score import compute_risk_score
from src.analytics.simulation_features import analyze_simulation, extract_waveform_data
from src.analytics.staging import classify_nyha
from src.api import models
from src.data_synthesis.generate_patients import load_reference_stats
from src.patient_builder.patient_file import build_patient_file
from src.patient_builder.scenario_file import STABILIZATION_S, build_scenario_file
from src.pulse_runner.runner import run_pulse_with_preflight
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

# Diagnosed 2026-08-17 (docs/real_world_data_integration.md §8.5): the fluid_overload fix's
# baseline_deficit_score term needs the Pulse-simulated patient to reflect a congested, diseased
# state, which needs a real, disease-appropriate ejection_fraction_pct. When EF is unmeasured and
# Tier-1-fallback-defaulted to the healthy-population mean (apply_tier1_fallback()), Pulse
# simulates a structurally normal heart regardless of scenario_type/severity, so map_start comes
# out healthy and baseline_deficit_score has nothing to detect -- the FLUID_OVERLOAD_CAVEAT_MESSAGE
# above is stale and technically inaccurate for this specific failure mode (it describes the
# pre-fix blind spot; this is a different, still-open one). This message names the actual
# mechanism instead. Caveat/messaging only -- does NOT change the EF fallback value or logic, and
# deliberately does NOT make the fallback scenario-aware (that would leak the label being
# predicted into an input feature).
EF_FALLBACK_MASKS_FLUID_OVERLOAD_CAVEAT_MESSAGE = (
    "Detected scenario is fluid_overload, but risk_score is LOW for a different reason than the "
    "general fluid_overload caveat: ejection_fraction_pct was not measured for this patient and "
    "defaulted to the Tier 1 healthy-population-mean fallback (docs/data_provenance.md), so the "
    "Pulse-simulated patient has a structurally normal heart -- risk_score.py's "
    "baseline_deficit_score term (the fluid_overload fix, docs/methodology.md §6.1) has no "
    "congested baseline to detect, regardless of the wearable-trend-derived severity. Do not rely "
    "on risk_score alone; a measured ejection fraction would materially change this assessment "
    "(docs/real_world_data_integration.md §8.5)."
)

# Relabeling fix, 2026-09-01 (docs/methodology.md §4.2): the dashboard's Cardiac Waveform panel
# used to caption the ECG "simulated", implying it was patient-derived like the PV loop next to it.
# Per Kitware's Cardiovascular Methodology docs ("Electrocardiogram" section), Pulse does not
# compute this trace from cardiac electrophysiology at all -- it interpolates a stored single-cycle
# voltage template to the run's simulated cycle length, so it carries heart-rate information only.
# Unlike the two messages above, this applies to every completed run regardless of scenario_type
# (waveform_data is populated unconditionally after a successful Pulse run), so it is appended to
# risk_caveats rather than selected as an alternative.
ECG_REFERENCE_TEMPLATE_CAVEAT_MESSAGE = (
    "The Cardiac Waveform panel's ECG trace is a stored reference rhythm template scaled to this "
    "run's simulated heart rate, not a signal computed from cardiac electrophysiology (Pulse engine "
    "design -- docs/methodology.md §4.2). It reflects heart rate only and is not an input to the "
    "scenario classifier or severity regressor. Do not read patient-specific meaning into its shape."
)

def mark_simulation_run_failed(db: Session, run: models.SimulationRun, error_message: str) -> None:
    """PROPOSED 2026-10-02, part of the continuous-state-sync / real-outcome-validation /
    unstable-alert-fallback integration (docs/integration_pre_results.md): shared by
    src/api/services.py and src/api/continuous_state_pipeline.py so a Pulse failure is recorded
    identically regardless of which pipeline produced it. This is the exact behavior
    _run_assessment_pipeline() already had inline in both of its failure branches -- extracted
    here, not changed, so routes.py's _build_status() and the unstable-run alert fallback
    (fix/unstable-alert-fallback) see the same SimulationRun(status="failed") shape either way."""
    run.status = "failed"
    run.error_message = error_message
    run.completed_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()


def build_risk_caveats(scenario_type: str, ef_is_fallback: bool, risk_bucket: str) -> str:
    """Shared by src/api/services.py and src/api/continuous_state_pipeline.py so both pipelines
    attach identical risk_caveats text for the same inputs -- previously duplicated inline here
    and in continuous_state_pipeline.py, which had drifted to omit ECG_REFERENCE_TEMPLATE_CAVEAT_
    MESSAGE entirely (found during the continuous-state-sync / real-outcome-validation merge,
    2026-10-02). See the three *_CAVEAT_MESSAGE constants above for what each piece means."""
    if scenario_type != "fluid_overload":
        fluid_overload_caveat = None
    elif ef_is_fallback and risk_bucket == "LOW":
        fluid_overload_caveat = EF_FALLBACK_MASKS_FLUID_OVERLOAD_CAVEAT_MESSAGE
    else:
        fluid_overload_caveat = FLUID_OVERLOAD_CAVEAT_MESSAGE

    return " ".join(
        c for c in (fluid_overload_caveat, ECG_REFERENCE_TEMPLATE_CAVEAT_MESSAGE) if c
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
    if latest_report is not None:
        # create_clinical_report() (src/api/routes.py) already resolved and stored the fallback
        # at submission time -- ejection_fraction_pct is never NULL here even when it was a
        # fallback, so re-deriving ef_is_fallback via a second apply_tier1_fallback() call would
        # always see a concrete number and wrongly compute False. Reuse the already-stored flag
        # instead (bug found and fixed 2026-08-17 verifying the EF-fallback caveat against a real
        # patient -- docs/real_world_data_integration.md §8.5).
        ejection_fraction_pct = latest_report.ejection_fraction_pct
        nt_probnp_pg_ml = latest_report.nt_probnp_pg_ml
        ef_is_fallback = latest_report.ef_is_fallback
    else:
        ejection_fraction_pct, nt_probnp_pg_ml, ef_is_fallback, _ = apply_tier1_fallback(None, None)

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
        # run_pulse_with_preflight() (Sprint 2, docs/methodology.md Sec 8) warns (RuntimeWarning)
        # before running if (scenario_type, severity) falls in the documented crash zone -- it
        # still runs by default (never silently skips a run this pipeline expects); catches
        # PulseExecutionError internally and reports it via pulse_result["error"] instead of
        # raising, so the failure handling below is unchanged in observable behavior.
        pulse_result = run_pulse_with_preflight(
            str(scenario_path), scenario_type, severity,
            expected_duration_s=expected_duration_s, timeout_sec=180,
        )
    except Exception as e:  # defensive: never leave a run stuck at "running" on an unexpected error
        mark_simulation_run_failed(db, run, f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
        return

    if not pulse_result["pulse_succeeded"]:
        run.scenario_json_path = str(scenario_path)
        mark_simulation_run_failed(db, run, pulse_result["error"])
        return

    df = pulse_result["df"]
    sim_features = analyze_simulation(df)
    run.waveform_data = extract_waveform_data(df)
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
        # Raw, scale-agnostic rate -- project_physiology()/project_severity() do their own
        # severity-scoped conversion internally. Passing a risk_score-pre-converted rate here
        # (SD_RATE_TO_RISK_SCORE_PER_DAY) was the bug fixed 2026-09-10 (docs/methodology.md Sec 8).
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

    risk_caveats = build_risk_caveats(scenario_type, ef_is_fallback, risk["risk_bucket"])

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
    run.status = "complete"
    run.completed_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
