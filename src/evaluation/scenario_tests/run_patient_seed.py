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
import os
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
# feature/wire-research-features: a flag-on rerun (e.g. ENABLE_SCENARIO_PERSISTENCE=1) must not
# overwrite the frozen flags-off outputs above. Unset (the default) leaves both paths unchanged.
if os.environ.get("SCENARIO_TEST_OUTPUT_DIR"):
    OUTPUT_DIR = pathlib.Path(os.environ["SCENARIO_TEST_OUTPUT_DIR"])
    DB_DIR = OUTPUT_DIR / "dbs"
# Experiment 2 (results/scenario_tests/exp2/PREREGISTRATION.md) points this at
# config/scenario_tests/cohort_exp2.yaml. Unset leaves the Experiment 1 cohort.
if os.environ.get("SCENARIO_TEST_COHORT"):
    COHORT_PATH = pathlib.Path(os.environ["SCENARIO_TEST_COHORT"])

BASELINE_DAYS = 21
MONITORED_DAYS = 21
# BUGFIX 2026-10-03 (results/scenario_tests/protocol_amendments.md): noise SD for resting_hr_bpm/
# steps_per_day/hrv_rmssd_ms/spo2_pct/sleep_hours must be calibrated against the POPULATION SD in
# reference_stats.yaml (the same convention generate_wearable_trends.py uses, and what the
# classifier/regressor were actually trained against) -- NOT against each patient's own current
# value. The original version used `current_value * NOISE_SD_FRACTION` for steps/HRV, producing
# noise 2-2.7x larger than the training distribution ever saw for exactly the two features the
# regressor is most sensitive to (resting_hr_bpm and steps_per_day delta/slope, ~90% combined
# importance) -- traced as the root cause of a spurious pre-story "deconditioning" alert on P10's
# day 3 (before its story starts on day 4).
NOISE_SD_FRACTION = 0.15
WEIGHT_NOISE_SD_KG = 0.3   # brief: "weight fluctuates by about +-0.3 kg" -- explicit instruction, not population-derived

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


def load_warmup_days():
    """meta.warmup_days from the cohort file; 0 (Experiment 1 behaviour) when absent."""
    return int(yaml.safe_load(COHORT_PATH.read_text())["meta"].get("warmup_days", 0))


def _population_noise_sds():
    """Population-calibrated noise SD per vital (population_sd * NOISE_SD_FRACTION), the same
    convention generate_wearable_trends.py uses and what the classifier/regressor were trained
    against -- see the BUGFIX note on NOISE_SD_FRACTION above."""
    from src.data_synthesis.generate_patients import load_reference_stats
    wb = load_reference_stats()["wearable_baseline"]
    return {v: wb[v]["sd"] * NOISE_SD_FRACTION for v in
            ("resting_hr_bpm", "steps_per_day", "hrv_rmssd_ms", "spo2_pct", "sleep_hours")}


NOISE_SD = _population_noise_sds()


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
            resting_hr_bpm=base["resting_hr_bpm"] + _n(rng, NOISE_SD["resting_hr_bpm"]),
            spo2_pct=min(100.0, base["spo2_pct"] + _n(rng, NOISE_SD["spo2_pct"])),
            weight_kg=base["weight_kg"] + _n(rng, WEIGHT_NOISE_SD_KG),
            steps_per_day=max(0.0, base["steps_per_day"] + _n(rng, NOISE_SD["steps_per_day"])),
            sleep_hours=max(0.0, base["sleep_hours"] + _n(rng, NOISE_SD["sleep_hours"])),
            hrv_rmssd_ms=max(1.0, base["hrv_rmssd_ms"] + _n(rng, NOISE_SD["hrv_rmssd_ms"])),
        ))
    db.commit()


def add_monitored_reading(db, patient_id, cfg, day_row, calendar_day, rng):
    from src.api import models
    base = cfg["baseline_wearable"]
    values = dict(
        resting_hr_bpm=day_row["resting_hr_bpm"] + _n(rng, NOISE_SD["resting_hr_bpm"]),
        spo2_pct=min(100.0, base["spo2_pct"] + _n(rng, NOISE_SD["spo2_pct"])),
        weight_kg=day_row["weight_kg"] + _n(rng, WEIGHT_NOISE_SD_KG),
        steps_per_day=max(0.0, day_row["steps_per_day"] + _n(rng, NOISE_SD["steps_per_day"])),
        sleep_hours=max(0.0, day_row["sleep_hours"] + _n(rng, NOISE_SD["sleep_hours"])),
        hrv_rmssd_ms=max(1.0, day_row["hrv_rmssd_ms"] + _n(rng, NOISE_SD["hrv_rmssd_ms"])),
    )
    db.add(models.WearableReading(patient_id=patient_id, recorded_date=calendar_day, **values))
    db.commit()
    return values


def _derive_rng_seed(patient_id, seed):
    """Deterministic (patient_id, seed) -> uint32 seed for np.random.default_rng.

    BUGFIX (2026-10-03): the original version used Python's built-in `hash((patient_id, seed))`.
    CPython salts str/tuple hashing per-process by default (hash randomization, PYTHONHASHSEED),
    so the SAME (patient_id, seed) pair produced a DIFFERENT RNG seed -- and therefore a different
    wearable-noise realization -- on every separate `python3 -m ...` subprocess invocation, even
    though the CLI argument "42" was unchanged. This silently broke the documented guarantee that
    "seeds 42/43/44" are reproducible noise draws: reruns of "the same seed" were not comparable.
    hashlib.sha256 is unsalted and stable across processes/platforms, so it is used instead.
    """
    digest = hashlib.sha256(f"{patient_id}:{seed}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def run(patient_id, seed):
    verify_model_hashes()
    cfg = load_patient_cohort(patient_id)
    rng = np.random.default_rng(_derive_rng_seed(patient_id, seed))

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

    # Experiment 2 harness-only warm-up: the continuous pipeline's first call is run_initial(),
    # which applies only the base CardiovascularMechanicsModification -- no scenario extras, no
    # Exercise (docs/research_flags_evaluation.md Sec 7.1). Running warm-up days at baseline
    # wearable levels first means every scored monitored day is a resumed run. Warm-up days are
    # never written to the CSV. System code (run_initial, the pipeline) is unchanged.
    warmup_days = load_warmup_days()
    base = cfg["baseline_wearable"]
    for w in range(warmup_days):
        warmup_row = {k: base[k] for k in ("resting_hr_bpm", "weight_kg", "steps_per_day", "sleep_hours", "hrv_rmssd_ms")}
        add_monitored_reading(db, patient_id, cfg, warmup_row, base_date + datetime.timedelta(days=BASELINE_DAYS + w), rng)
        warmup_state = run_daily_continuous_pipeline(patient_id, db, compute_projection=False)
        print(f"[{patient_id} seed={seed}] warm-up day {w + 1}/{warmup_days}: "
              f"{'complete' if warmup_state is not None else 'failed'} (not scored)", flush=True)

    rows = []
    engine_lag_days = 0
    captured = {}

    def _capturing_analyze_simulation(df):
        result = real_analyze_simulation(df)
        captured["sim_features"] = result
        return result

    for i, day_row in enumerate(cfg["monitored_day_schedule"]):
        day = day_row["day"]
        calendar_day = base_date + datetime.timedelta(days=BASELINE_DAYS + warmup_days + i)
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
                # BUGFIX (2026-10-03): this used to collapse to one label, "unstable_fallback",
                # regardless of whether Pulse actually failed. determine_simulation_status()
                # takes the classifier-only path for two distinct reasons -- a real Pulse failure
                # (run_status == "failed") vs. a run that completed but landed in the documented
                # crash zone (run_status == "complete", still not trusted per that function's own
                # docstring). Splitting these per the pre-registered labelling change.
                alert_source = "failed_fallback" if run_status == "failed" else "unstable_completed"
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
