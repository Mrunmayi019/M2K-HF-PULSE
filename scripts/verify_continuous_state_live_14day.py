"""Live 14-monitored-day continuous-state-sync verification against the REAL Pulse engine inside
the Docker container (not mocked) -- part of docs/integration_pre_results.md's step 4/7 live run,
run as a follow-up to scripts/verify_continuous_state_pipeline.py's 3-day check.

Uses a deliberately FLAT, non-perturbed patient -- every one of the 35 wearable readings (21
baseline + one added per monitored day, so the rolling 21-day window shifts forward but always
sees the same constant values) is identical day to day, and EF/BNP never change (no new
ClinicalReport submitted). This isolates one specific question: does a genuinely stable patient's
risk score/NYHA class/alert status drift over 14 days of continuous-state-sync just from the
resume mechanism itself (repeated reissue of CardiovascularMechanicsModification, Pulse's own
state-resume behavior), with no input signal driving any real change? If anything drifts here, the
resume mechanism itself is the only possible explanation, since every input is held constant.

Run ONCE (not twice) by explicit instruction, given the ~3-4h cost of running this live under
amd64 emulation twice; the run-to-run determinism property was already established at the 3-day
scale (scripts/verify_continuous_state_pipeline.py, 2 independent runs, identical) and in the
mocked unit tests (tests/test_continuous_state_pipeline.py).

Reports, per monitored day: wall-clock time, simulation_time_s, risk_score, risk_bucket,
nyha_class, and alert status (via RiskAssessment.score_provenance, the same property
/patients/{id}/status's alert fields are built from) -- plus confirms
CardiovascularMechanicsModification is reissued on every resume (both statically true by
construction -- build_resume_scenario() puts it unconditionally as Actions[0], no branch skips it
-- and confirmed here directly by building a real resume scenario dict and inspecting it).

Must run INSIDE the Pulse Docker container (PulseScenarioDriver is a Linux amd64 binary):

    PYTHONPATH=/workspace python3 -m scripts.verify_continuous_state_live_14day
"""
from __future__ import annotations

import datetime
import sys
import time

from scripts.verify_continuous_state_pipeline import make_session
from src.api import models
from src.api.continuous_state_pipeline import (
    DAILY_ENCOUNTER_DURATION_S,
    run_daily_continuous_pipeline,
)
from src.patient_builder.scenario_file import STABILIZATION_S
from src.pulse_runner.cli_state_scenario import build_resume_scenario

WINDOW_DAYS = 21
MONITORED_DAYS = 14
PATIENT_ID = "P_LIVE14_FLAT"
EF = 60.0   # reference_stats.yaml's healthy-population EF mean -- same value Tier-1 fallback uses
BNP = 100.0  # same "unremarkable/healthy" placeholder Tier-1 fallback uses
FLAT_READING = dict(resting_hr_bpm=70.0, spo2_pct=97.0, weight_kg=78.0, steps_per_day=6500.0,
                     sleep_hours=7.2, hrv_rmssd_ms=38.0)
BASE_DATE = datetime.date(2026, 1, 1)


def confirm_cvmod_reissue():
    """Direct, concrete confirmation (not just reading source): build a real resume scenario dict
    with representative inputs and check its first action wraps the reissue."""
    scenario = build_resume_scenario(
        state_in_path="/tmp/fake_state_in.json",
        ejection_fraction_pct=EF,
        severity=0.1,
        duration_s=DAILY_ENCOUNTER_DURATION_S,
        scenario_type="stable",
        state_out_path="/tmp/fake_state_out.json",
    )
    actions = scenario["Scenario"]["AnyAction"]
    # Every patient action is wrapped in "PatientAction" at the AnyAction list-item level (Pulse's
    # own schema requirement -- see src/patient_builder/scenario_file.py's
    # _cardiovascular_modification_action() comment).
    first_action = actions[0]
    patient_action_keys = list(first_action.get("PatientAction", {}).keys())
    print(f"CardiovascularMechanicsModification reissue check: Actions[0] keys = {list(first_action.keys())!r}, "
          f"PatientAction keys = {patient_action_keys!r}")
    if "PatientAction" not in first_action or "CardiovascularMechanicsModification" not in patient_action_keys:
        sys.exit(f"REISSUE CHECK FAILED: expected Actions[0] to wrap the reissue, got {first_action!r}")
    print("CONFIRMED: every resume's scenario unconditionally reissues "
          "CardiovascularMechanicsModification as Actions[0] -- no branch skips it.\n")


def seed_flat_patient_and_window(db):
    db.add(models.Patient(id=PATIENT_ID, age=58, sex="Male", height_cm=175.0, weight_kg=78.0))
    db.add(models.ClinicalReport(
        patient_id=PATIENT_ID, ejection_fraction_pct=EF, nt_probnp_pg_ml=BNP,
        reported_at=datetime.datetime.now(datetime.timezone.utc),
    ))
    for day in range(WINDOW_DAYS):
        db.add(models.WearableReading(
            patient_id=PATIENT_ID, recorded_date=BASE_DATE + datetime.timedelta(days=day),
            **FLAT_READING,
        ))
    db.commit()


def add_flat_reading(db, day):
    db.add(models.WearableReading(
        patient_id=PATIENT_ID, recorded_date=BASE_DATE + datetime.timedelta(days=day),
        **FLAT_READING,
    ))
    db.commit()


def main():
    confirm_cvmod_reissue()

    db, tmp_db_path = make_session()
    try:
        seed_flat_patient_and_window(db)
        day_results = []
        for day_index in range(MONITORED_DAYS):
            new_wearable_day = WINDOW_DAYS + day_index  # day 21, 22, ..., 34 -> 35 readings total
            add_flat_reading(db, day=new_wearable_day)

            start = time.monotonic()
            state = run_daily_continuous_pipeline(PATIENT_ID, db)
            elapsed = time.monotonic() - start
            if state is None:
                sys.exit(f"day {day_index + 1} FAILED -- check the SimulationRun.error_message")

            assessment = (
                db.query(models.RiskAssessment)
                .filter(models.RiskAssessment.patient_id == PATIENT_ID)
                .order_by(models.RiskAssessment.created_at.desc())
                .first()
            )
            provenance = assessment.score_provenance
            result = {
                "day": day_index + 1,
                "wall_s": round(elapsed, 1),
                "simulation_time_s": state.simulation_time_s,
                "risk_score": assessment.risk_score,
                "risk_bucket": assessment.risk_bucket,
                "nyha_class": assessment.nyha_class,
                "alert": provenance["alert"],
                "alert_basis": provenance.get("alert_basis"),
                "simulation_status": provenance["simulation_status"],
            }
            day_results.append(result)
            print(f"day {day_index + 1:2d}: wall={elapsed:6.1f}s sim_time={state.simulation_time_s:7.1f}s "
                  f"risk_score={result['risk_score']:.4f} bucket={result['risk_bucket']:9s} "
                  f"nyha={result['nyha_class']} alert={result['alert']:12s} "
                  f"sim_status={result['simulation_status']}")

        print("\n=== simulation_time_s step check (+660s day 1, then +600s/day) ===")
        expected_day1 = STABILIZATION_S + DAILY_ENCOUNTER_DURATION_S
        step_ok = abs(day_results[0]["simulation_time_s"] - expected_day1) < 1.0
        print(f"  day  1: {day_results[0]['simulation_time_s']}s (expected {expected_day1}s) "
              f"{'OK' if step_ok else 'WRONG'}")
        for i in range(1, len(day_results)):
            step = day_results[i]["simulation_time_s"] - day_results[i - 1]["simulation_time_s"]
            ok = abs(step - DAILY_ENCOUNTER_DURATION_S) < 1.0
            step_ok = step_ok and ok
            print(f"  day {i + 1:2d}: +{step}s {'OK' if ok else 'WRONG'}")

        print("\n=== Drift check: does a genuinely flat patient's risk_score/bucket/NYHA/alert change over 14 days? ===")
        first, last = day_results[0], day_results[-1]
        drifted = (
            first["risk_bucket"] != last["risk_bucket"]
            or first["nyha_class"] != last["nyha_class"]
            or first["alert"] != last["alert"]
        )
        print(f"  day 1:  risk_score={first['risk_score']:.4f} bucket={first['risk_bucket']} "
              f"nyha={first['nyha_class']} alert={first['alert']}")
        print(f"  day 14: risk_score={last['risk_score']:.4f} bucket={last['risk_bucket']} "
              f"nyha={last['nyha_class']} alert={last['alert']}")
        print(f"  risk_score range across all 14 days: "
              f"{min(d['risk_score'] for d in day_results):.4f} - {max(d['risk_score'] for d in day_results):.4f}")
        print(f"  [{'DRIFTED -- bucket/NYHA/alert changed' if drifted else 'NO DRIFT in bucket/NYHA/alert'}]")

        print("\n=== VERDICT ===")
        print(f"  [{'PASS' if step_ok else 'FAIL'}] simulation_time_s steps correctly "
              f"(+{expected_day1}s day 1, +{DAILY_ENCOUNTER_DURATION_S}s/day after)")
        return 0 if step_ok else 1
    finally:
        db.close()
        tmp_db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
