"""Runs ONE patient x ONE seed through 21 baseline + 21 monitored days of the REAL continuous-
state-sync pipeline (run_daily_continuous_pipeline, compute_projection=False -- verified display-
only, docs/integration_pre_results.md), against an isolated per-patient-seed SQLite DB, and writes
results/scenario_tests/daily_results_<patient>_<seed>.csv.

One process per patient-seed (hard rule: no threads/forking inside a process). The orchestrator
(run_batch.py) launches this script as a fresh `python3 -m ...` subprocess per (patient_id, seed)
pair, up to 6 concurrently -- never multiprocessing/fork, never threads.

Must run INSIDE the m2k-hf-pulse-backend image (pinned Python 3.11 / scikit-learn 1.9.0), NOT the
raw kitware/pulse:4.3.1 image (docs/integration_pre_results.md Sec 10.5).

Before any run: verifies models/scenario_classifier.joblib and models/severity_regressor.joblib
match artifacts/results-v1/models/ by SHA-256; refuses to start otherwise.

A None return from the pipeline = a failed day. The run CONTINUES (the pipeline resumes from the
last good state, one encounter behind -- docs/integration_pre_results.md Sec 8); the failure is
recorded via the real failed SimulationRun row's error_message, never silently dropped.

Seeds (42/43/44) affect ONLY the small realistic day-to-day wearable noise layer added here -- the
story schedule itself (config/scenario_tests/cohort.yaml) is deterministic and seed-independent.

Usage:
    PYTHONPATH=/workspace python3 -m src.evaluation.scenario_tests.run_patient_seed P04 42
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import pathlib
import sys
import time
from unittest.mock import patch

import numpy as np
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Imported at module level, before any make_session()/create_all() call -- SQLAlchemy's
# declarative Base.metadata only includes models whose class body has actually executed by the
# time create_all() runs. A lazy/deferred import here left Base.metadata empty and create_all()
# silently created zero tables (found running the pilot).
from src.api import models  # noqa: F401

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
COHORT_PATH = REPO_ROOT / "config" / "scenario_tests" / "cohort.yaml"
FROZEN_MODELS_DIR = REPO_ROOT / "artifacts" / "results-v1" / "models"
LIVE_MODELS_DIR = REPO_ROOT / "models"
DB_DIR = REPO_ROOT / "results" / "scenario_tests" / "dbs"
OUTPUT_DIR = REPO_ROOT / "results" / "scenario_tests"

BASELINE_DAYS = 21
MONITORED_DAYS = 21
# Noise conventions: same relative-noise style generate_wearable_trends.py uses (NOISE_SD_FRACTION
# of each vital), plus the brief's explicit absolute figures for weight/HR.
NOISE_SD_FRACTION = 0.15
WEIGHT_NOISE_SD_KG = 0.3   # brief: "weight fluctuates by about +-0.3 kg"
HR_NOISE_SD_BPM = 2.0      # brief: "resting HR by a few bpm"
SPO2_NOISE_SD = 0.3
SLEEP_NOISE_SD_HR = 0.2

CSV_FIELDS = [
    "patient_id", "seed", "day", "story", "expected_group", "event",
    "weight_input_level_only", "sleep_input_level_only",
    "severity_injected",
    "pulse_hr_start", "pulse_hr_end", "pulse_map_start", "pulse_map_end",
    "pulse_co_start", "pulse_co_end", "pulse_sv_start", "pulse_sv_end",
    "pulse_compensation_flag", "pulse_instability_flag",
    "wearable_weight_kg", "wearable_steps_per_day", "wearable_hrv_rmssd_ms",
    "wearable_resting_hr_bpm", "wearable_spo2_pct", "spo2_flagged_unreliable",
    "predicted_scenario", "predicted_severity",
    "risk_score", "risk_bucket", "nyha_class",
    "alert_flag", "alert_source",
    "run_status", "error_message",
    "simulation_time_s", "engine_lag_days", "wall_time_s",
]


def verify_model_hashes():
    for fname in ("scenario_classifier.joblib", "severity_regressor.joblib"):
        live = LIVE_MODELS_DIR / fname
        frozen = FROZEN_MODELS_DIR / fname
        if not live.exists() or not frozen.exists():
            sys.exit(f"REFUSING TO START: missing model file ({live} or {frozen})")
        live_hash = hashlib.sha256(live.read_bytes()).hexdigest()
        frozen_hash = hashlib.sha256(frozen.read_bytes()).hexdigest()
        if live_hash != frozen_hash:
            sys.exit(
                f"REFUSING TO START: {live} sha256={live_hash} does not match frozen "
                f"{frozen} sha256={frozen_hash}"
            )
    print("Model hash check: OK (models/*.joblib matches artifacts/results-v1/models/)", flush=True)


def load_patient_cohort(patient_id):
    cohort = yaml.safe_load(COHORT_PATH.read_text())
    return cohort["patients"][patient_id]


def make_session(patient_id, seed):
    DB_DIR.mkdir(parents=True, exist_ok=True)
    db_path = DB_DIR / f"{patient_id}_seed{seed}.db"
    db_path.unlink(missing_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    from src.api.database import Base
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    return session, db_path


def seed_patient_and_clinical_report(db, patient_id, cfg):
    from src.api import models
    demo = cfg["demographics"]
    db.add(models.Patient(
        id=patient_id, age=demo["age"], sex=demo["sex"],
        height_cm=demo["height_cm"], weight_kg=demo["weight_kg"],
        label=f"{patient_id}: {cfg['story']}",
    ))
    clin = cfg["baseline_clinical_report"]
    db.add(models.ClinicalReport(
        patient_id=patient_id, ejection_fraction_pct=clin["ejection_fraction_pct"],
        nt_probnp_pg_ml=clin["nt_probnp_pg_ml"],
        reported_at=datetime.datetime.now(datetime.timezone.utc),
    ))
    db.commit()


def _n(rng, sd):
    return float(rng.normal(0, sd))


def add_baseline_window(db, patient_id, cfg, rng, base_date):
    from src.api import models
    base = cfg["baseline_wearable"]
    for day in range(BASELINE_DAYS):
        db.add(models.WearableReading(
            patient_id=patient_id,
            recorded_date=base_date + datetime.timedelta(days=day),
            resting_hr_bpm=base["resting_hr_bpm"] + _n(rng, HR_NOISE_SD_BPM),
            spo2_pct=min(100.0, base["spo2_pct"] + _n(rng, SPO2_NOISE_SD)),
            weight_kg=base["weight_kg"] + _n(rng, WEIGHT_NOISE_SD_KG),
            steps_per_day=max(0.0, base["steps_per_day"] + _n(rng, base["steps_per_day"] * NOISE_SD_FRACTION)),
            sleep_hours=max(0.0, base["sleep_hours"] + _n(rng, SLEEP_NOISE_SD_HR)),
            hrv_rmssd_ms=max(1.0, base["hrv_rmssd_ms"] + _n(rng, base["hrv_rmssd_ms"] * NOISE_SD_FRACTION)),
        ))
    db.commit()


def add_monitored_reading(db, patient_id, cfg, day_row, calendar_day, rng):
    from src.api import models
    base = cfg["baseline_wearable"]
    values = dict(
        resting_hr_bpm=day_row["resting_hr_bpm"] + _n(rng, HR_NOISE_SD_BPM),
        spo2_pct=min(100.0, base["spo2_pct"] + _n(rng, SPO2_NOISE_SD)),
        weight_kg=day_row["weight_kg"] + _n(rng, WEIGHT_NOISE_SD_KG),
        steps_per_day=max(0.0, day_row["steps_per_day"] + _n(rng, max(day_row["steps_per_day"], 1) * NOISE_SD_FRACTION)),
        sleep_hours=max(0.0, day_row["sleep_hours"] + _n(rng, SLEEP_NOISE_SD_HR)),
        hrv_rmssd_ms=max(1.0, day_row["hrv_rmssd_ms"] + _n(rng, max(day_row["hrv_rmssd_ms"], 1) * NOISE_SD_FRACTION)),
    )
    db.add(models.WearableReading(patient_id=patient_id, recorded_date=calendar_day, **values))
    db.commit()
    return values


def run(patient_id, seed):
    verify_model_hashes()
    cfg = load_patient_cohort(patient_id)
    rng = np.random.default_rng(hash((patient_id, seed)) % (2**32))

    db, db_path = make_session(patient_id, seed)
    print(f"[{patient_id} seed={seed}] DB: {db_path}", flush=True)

    from src.api import models
    from src.api.continuous_state_pipeline import run_daily_continuous_pipeline
    import src.api.continuous_state_pipeline as csp
    from src.api.routes import _build_status
    from src.analytics.simulation_features import analyze_simulation as real_analyze_simulation

    seed_patient_and_clinical_report(db, patient_id, cfg)
    base_date = datetime.date(2026, 1, 1)
    add_baseline_window(db, patient_id, cfg, rng, base_date)

    rows = []
    engine_lag_days = 0
    captured = {}

    def _capturing_analyze_simulation(df):
        result = real_analyze_simulation(df)
        captured["sim_features"] = result
        return result

    for i, day_row in enumerate(cfg["monitored_day_schedule"]):
        day = day_row["day"]
        calendar_day = base_date + datetime.timedelta(days=BASELINE_DAYS + i)
        wearable_values = add_monitored_reading(db, patient_id, cfg, day_row, calendar_day, rng)

        captured.clear()
        start = time.monotonic()
        with patch.object(csp, "analyze_simulation", side_effect=_capturing_analyze_simulation):
            state = run_daily_continuous_pipeline(patient_id, db, compute_projection=False)
        wall_time_s = time.monotonic() - start

        patient = db.get(models.Patient, patient_id)
        status = _build_status(db, patient)

        if state is None:
            engine_lag_days += 1
            run_status = "failed"
            failed_run = (
                db.query(models.SimulationRun)
                .filter(models.SimulationRun.patient_id == patient_id, models.SimulationRun.status == "failed")
                .order_by(models.SimulationRun.started_at.desc())
                .first()
            )
            error_message = failed_run.error_message if failed_run else None
            predicted_scenario = failed_run.scenario_type if failed_run else None
            predicted_severity = failed_run.severity if failed_run else None
            risk_score = risk_bucket = nyha_class = None
            simulation_time_s = None
            sf = {}
        else:
            run_status = "complete"
            error_message = None
            latest_run = (
                db.query(models.SimulationRun)
                .filter(models.SimulationRun.patient_id == patient_id)
                .order_by(models.SimulationRun.started_at.desc())
                .first()
            )
            predicted_scenario = latest_run.scenario_type if latest_run else None
            predicted_severity = latest_run.severity if latest_run else None
            assessment = (
                db.query(models.RiskAssessment)
                .filter(models.RiskAssessment.patient_id == patient_id)
                .order_by(models.RiskAssessment.created_at.desc())
                .first()
            )
            risk_score = assessment.risk_score if assessment else None
            risk_bucket = assessment.risk_bucket if assessment else None
            nyha_class = assessment.nyha_class if assessment else None
            simulation_time_s = state.simulation_time_s
            sf = captured.get("sim_features", {})

        current_alert = status.current_alert
        if current_alert is None:
            alert_flag, alert_source = False, "none"
        else:
            alert_flag = current_alert.get("alert") == "alert"
            if not alert_flag:
                alert_source = "none"
            elif current_alert.get("alert_basis") == "classifier_only":
                alert_source = "unstable_fallback"
            else:
                alert_source = "scorer"

        rows.append({
            "patient_id": patient_id, "seed": seed, "day": day,
            "story": cfg["story"], "expected_group": cfg["expected_group"],
            "event": day_row.get("event"),
            "weight_input_level_only": day_row.get("weight_input_level_only", False),
            "sleep_input_level_only": day_row.get("sleep_input_level_only", False),
            "severity_injected": day_row["severity_target"],
            "pulse_hr_start": sf.get("hr_start"), "pulse_hr_end": sf.get("hr_end"),
            "pulse_map_start": sf.get("map_start"), "pulse_map_end": sf.get("map_end"),
            "pulse_co_start": sf.get("co_start"), "pulse_co_end": sf.get("co_end"),
            "pulse_sv_start": sf.get("stroke_volume_start"), "pulse_sv_end": sf.get("stroke_volume_end"),
            "pulse_compensation_flag": sf.get("compensation_flag"),
            "pulse_instability_flag": sf.get("instability_flag"),
            "wearable_weight_kg": wearable_values["weight_kg"],
            "wearable_steps_per_day": wearable_values["steps_per_day"],
            "wearable_hrv_rmssd_ms": wearable_values["hrv_rmssd_ms"],
            "wearable_resting_hr_bpm": wearable_values["resting_hr_bpm"],
            "wearable_spo2_pct": wearable_values["spo2_pct"],
            "spo2_flagged_unreliable": True,
            "predicted_scenario": predicted_scenario, "predicted_severity": predicted_severity,
            "risk_score": risk_score, "risk_bucket": risk_bucket, "nyha_class": nyha_class,
            "alert_flag": alert_flag, "alert_source": alert_source,
            "run_status": run_status, "error_message": error_message,
            "simulation_time_s": simulation_time_s, "engine_lag_days": engine_lag_days,
            "wall_time_s": round(wall_time_s, 1),
        })
        print(f"[{patient_id} seed={seed}] day {day:2d}: {run_status:8s} wall={wall_time_s:6.1f}s "
              f"scenario={predicted_scenario} severity={predicted_severity} "
              f"risk={risk_score} alert={alert_flag}({alert_source}) lag={engine_lag_days}", flush=True)

    db.close()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"daily_results_{patient_id}_seed{seed}.csv"
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[{patient_id} seed={seed}] wrote {out_path} ({len(rows)} rows, {engine_lag_days} failed days)", flush=True)
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("patient_id")
    parser.add_argument("seed", type=int)
    args = parser.parse_args()
    run(args.patient_id, args.seed)


if __name__ == "__main__":
    main()
