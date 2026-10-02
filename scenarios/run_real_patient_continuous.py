"""Runs the continuous-state-sync pipeline against a REAL patient in the real project DB
(data/db/m2k_hf_pulse.db, NOT a temp/throwaway DB) -- for Step 3/4 manual verification that a
continuous-synced patient's results show up through the existing API/frontend.

Additive only: creates new PulseState/SimulationRun/RiskAssessment rows for one existing patient.
Does not modify or delete any existing row. Not committed to the repo.
"""
import sys
sys.path.insert(0, "/workspace")

import datetime

from src.api.database import SessionLocal
from src.api import models
from src.api.continuous_state_pipeline import run_daily_continuous_pipeline

PATIENT_ID = "7693f167-c7ae-4f4f-bd59-18e8bb119a7a"

db = SessionLocal()
try:
    patient = db.get(models.Patient, PATIENT_ID)
    print(f"patient: age={patient.age} sex={patient.sex} height={patient.height_cm} weight={patient.weight_kg}")

    print("\n=== Day 1 (existing 21-day window, existing clinical report) ===")
    state1 = run_daily_continuous_pipeline(PATIENT_ID, db)
    print(f"PulseState id={state1.id} sim_time={state1.simulation_time_s} "
          f"ef={state1.last_ejection_fraction_pct} severity={state1.last_severity}")

    ra1 = (db.query(models.RiskAssessment)
           .filter(models.RiskAssessment.patient_id == PATIENT_ID)
           .order_by(models.RiskAssessment.created_at.desc()).first())
    print(f"RiskAssessment id={ra1.id} risk_score={ra1.risk_score} bucket={ra1.risk_bucket} "
          f"nyha={ra1.nyha_class} scenario={ra1.simulation_run.scenario_type} "
          f"severity={ra1.simulation_run.severity}")

    print("\n=== Day 2 (one new wearable reading -> resume) ===")
    last_reading = (db.query(models.WearableReading)
                     .filter(models.WearableReading.patient_id == PATIENT_ID)
                     .order_by(models.WearableReading.recorded_date.desc()).first())
    new_date = last_reading.recorded_date + datetime.timedelta(days=1)
    db.add(models.WearableReading(
        patient_id=PATIENT_ID, recorded_date=new_date,
        resting_hr_bpm=last_reading.resting_hr_bpm + 0.5,
        spo2_pct=last_reading.spo2_pct,
        weight_kg=last_reading.weight_kg,
        steps_per_day=last_reading.steps_per_day,
        sleep_hours=last_reading.sleep_hours,
        hrv_rmssd_ms=last_reading.hrv_rmssd_ms,
    ))
    db.commit()

    state2 = run_daily_continuous_pipeline(PATIENT_ID, db)
    print(f"PulseState id={state2.id} sim_time={state2.simulation_time_s} "
          f"ef={state2.last_ejection_fraction_pct} severity={state2.last_severity}")
    print(f"sim_time advanced by: {state2.simulation_time_s - state1.simulation_time_s}s "
          f"(expect exactly 600s -- confirms genuine resume, not a from-scratch rebuild)")

    ra2 = (db.query(models.RiskAssessment)
           .filter(models.RiskAssessment.patient_id == PATIENT_ID)
           .order_by(models.RiskAssessment.created_at.desc()).first())
    print(f"RiskAssessment id={ra2.id} risk_score={ra2.risk_score} bucket={ra2.risk_bucket} "
          f"nyha={ra2.nyha_class} scenario={ra2.simulation_run.scenario_type} "
          f"severity={ra2.simulation_run.severity}")

    total_assessments = (db.query(models.RiskAssessment)
                          .filter(models.RiskAssessment.patient_id == PATIENT_ID).count())
    total_states = (db.query(models.PulseState)
                     .filter(models.PulseState.patient_id == PATIENT_ID).count())
    print(f"\nTotal RiskAssessment rows for this patient now: {total_assessments}")
    print(f"Total PulseState rows for this patient now: {total_states}")
    print(f"\nPATIENT_ID for frontend lookup: {PATIENT_ID}")

finally:
    db.close()
