"""Continuous-state-sync feature (feature/continuous-state-sync branch) verification driver:
exercises src/api/continuous_state_pipeline.run_daily_continuous_pipeline() against an isolated
temp-file SQLite DB (never the real data/db/m2k_hf_pulse.db) across several simulated days, and
checks the behaviors the feature is supposed to have:

  - Day 1 (window just filled): creates the first PulseState via run_initial().
  - Day 2 (new wearable reading, no new clinical report): creates a second PulseState via
    resume_and_advance(); simulation_time_s should advance by exactly
    DAILY_ENCOUNTER_DURATION_S from day 1's; last_ejection_fraction_pct should be UNCHANGED
    (multi-rate: no new clinical report arrived).
  - Day 3 (new clinical report arrives with a different EF): last_ejection_fraction_pct on the
    new PulseState should reflect the NEW report's EF, not the carried-forward one.

Must run INSIDE the Pulse Docker container (src/pulse_runner/sdk_runner.py imports the `pulse`
SDK, only present there):

    PYTHONPATH=/workspace:/pulse/bin:/pulse/python python3 -m scripts.verify_continuous_state_pipeline
"""
from __future__ import annotations

import datetime
import pathlib
import tempfile

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api import models
from src.api.database import Base
from src.api.continuous_state_pipeline import (
    DAILY_ENCOUNTER_DURATION_S,
    run_daily_continuous_pipeline,
)

WINDOW_DAYS = 21


def make_session():
    tmp_db = pathlib.Path(tempfile.mktemp(suffix=".db"))
    engine = create_engine(f"sqlite:///{tmp_db}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session(), tmp_db


def seed_patient_and_window(db, patient_id="P_TEST", ef=45.0, bnp=800.0, start_day=0):
    if db.get(models.Patient, patient_id) is None:
        db.add(models.Patient(
            id=patient_id, age=58, sex="Male", height_cm=175.0, weight_kg=82.0,
        ))
        db.add(models.ClinicalReport(
            patient_id=patient_id, ejection_fraction_pct=ef, nt_probnp_pg_ml=bnp,
            reported_at=datetime.datetime.now(datetime.timezone.utc),
        ))
        db.commit()

    base_date = datetime.date(2026, 1, 1)
    for i in range(WINDOW_DAYS):
        day = start_day + i
        db.add(models.WearableReading(
            patient_id=patient_id,
            recorded_date=base_date + datetime.timedelta(days=day),
            resting_hr_bpm=70.0 + 0.5 * day,
            spo2_pct=97.0 - 0.05 * day,
            weight_kg=82.0 + 0.05 * day,
            steps_per_day=6000.0 - 20.0 * day,
            sleep_hours=7.0,
            hrv_rmssd_ms=35.0 - 0.2 * day,
        ))
    db.commit()


def add_one_reading(db, patient_id, day, **overrides):
    base_date = datetime.date(2026, 1, 1)
    defaults = dict(
        resting_hr_bpm=70.0 + 0.5 * day, spo2_pct=97.0 - 0.05 * day,
        weight_kg=82.0 + 0.05 * day, steps_per_day=6000.0 - 20.0 * day,
        sleep_hours=7.0, hrv_rmssd_ms=35.0 - 0.2 * day,
    )
    defaults.update(overrides)
    db.add(models.WearableReading(
        patient_id=patient_id, recorded_date=base_date + datetime.timedelta(days=day), **defaults
    ))
    db.commit()


def add_clinical_report(db, patient_id, ef, bnp):
    db.add(models.ClinicalReport(
        patient_id=patient_id, ejection_fraction_pct=ef, nt_probnp_pg_ml=bnp,
        reported_at=datetime.datetime.now(datetime.timezone.utc),
    ))
    db.commit()


def main():
    db, tmp_db_path = make_session()
    print(f"Isolated test DB: {tmp_db_path}")
    checks = []

    try:
        patient_id = "P_TEST"
        seed_patient_and_window(db, patient_id=patient_id, ef=45.0, bnp=800.0, start_day=0)

        # --- Day 1: window just filled -> run_initial() path ---
        state1 = run_daily_continuous_pipeline(patient_id, db)
        print(f"\n[day1] simulation_time_s={state1.simulation_time_s} "
              f"last_ejection_fraction_pct={state1.last_ejection_fraction_pct} "
              f"last_severity={state1.last_severity} state_json_len={len(state1.state_json)}")
        expected_day1_time = 60 + DAILY_ENCOUNTER_DURATION_S  # STABILIZATION_S + encounter
        checks.append((
            "day1 simulation_time_s matches STABILIZATION_S + DAILY_ENCOUNTER_DURATION_S",
            abs(state1.simulation_time_s - expected_day1_time) < 1.0,
        ))
        checks.append(("day1 EF is the seeded clinical report's EF (45.0)",
                        abs(state1.last_ejection_fraction_pct - 45.0) < 1e-6))

        # --- Day 2: one new wearable reading, NO new clinical report -> resume_and_advance() ---
        add_one_reading(db, patient_id, day=WINDOW_DAYS)
        state2 = run_daily_continuous_pipeline(patient_id, db)
        print(f"[day2] simulation_time_s={state2.simulation_time_s} "
              f"last_ejection_fraction_pct={state2.last_ejection_fraction_pct} "
              f"last_severity={state2.last_severity}")
        checks.append((
            "day2 simulation_time_s advanced by exactly DAILY_ENCOUNTER_DURATION_S from day1",
            abs((state2.simulation_time_s - state1.simulation_time_s) - DAILY_ENCOUNTER_DURATION_S) < 1.0,
        ))
        checks.append((
            "day2 EF UNCHANGED from day1 (multi-rate: no new clinical report)",
            state2.last_ejection_fraction_pct == state1.last_ejection_fraction_pct,
        ))
        checks.append(("two separate PulseState rows exist (append-only, not upserted)",
                        state2.id != state1.id))

        # --- Day 3: new clinical report arrives with a DIFFERENT EF -> should be adopted ---
        add_one_reading(db, patient_id, day=WINDOW_DAYS + 1)
        add_clinical_report(db, patient_id, ef=30.0, bnp=1500.0)
        state3 = run_daily_continuous_pipeline(patient_id, db)
        print(f"[day3] simulation_time_s={state3.simulation_time_s} "
              f"last_ejection_fraction_pct={state3.last_ejection_fraction_pct} "
              f"last_severity={state3.last_severity}")
        checks.append((
            "day3 EF UPDATED to the new clinical report's value (30.0)",
            abs(state3.last_ejection_fraction_pct - 30.0) < 1e-6,
        ))

    finally:
        db.close()
        tmp_db_path.unlink(missing_ok=True)

    print("\n=== VERDICT ===")
    all_pass = True
    for desc, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}")
        all_pass = all_pass and ok
    print(f"\nOVERALL: {'PASS' if all_pass else 'FAIL'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
