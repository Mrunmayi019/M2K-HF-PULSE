"""Diagnostic helper for HANDOFF.md P1 "diagnose the Pulse timeout/degradation behavior":
replays ONE specific synthetic patient through the live API, timing the pipeline precisely.

Built to re-attempt a patient_id already known to have hit the 180s Pulse-subprocess timeout in a
prior run (data/validation_runs/20260812_184726_nyha_fix_revalidation/combined_results.csv), right
after a clean Docker Desktop restart -- to distinguish "resolved by restart" (resource-leak/
degradation across long sessions) from "still failing on the same patient" (input-specific,
engine-level).

Same request construction as scripts/nyha_fix_live_revalidation.py's run_one_patient(), reused
rather than reinvented -- deliberately NOT importing that script's asyncio/semaphore machinery
since this is a single, sequential, clearly-attributable run, not a batch.

Usage: python -m scripts.reattempt_single_patient PATIENT_ID
"""
from __future__ import annotations

import datetime
import pathlib
import sys
import time

import httpx
import pandas as pd

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE_URL = "http://localhost:8000"
WINDOW_DAYS = 21
HTTP_TIMEOUT_S = 60.0
POLL_INTERVAL_S = 10
POLL_TIMEOUT_S = 900


def main() -> None:
    patient_id = sys.argv[1]

    patients = pd.read_csv(REPO_ROOT / "data" / "synthetic" / "patients.csv")
    wearable = pd.read_csv(REPO_ROOT / "data" / "synthetic" / "wearable_trends.csv")

    patient = patients[patients["patient_id"] == patient_id].iloc[0]
    rows = (
        wearable[wearable["patient_id"] == patient_id]
        .sort_values("day")
        .head(WINDOW_DAYS)
        .to_dict("records")
    )
    print(f"=== {patient_id} ({patient['scenario_type']}, true severity={patient['severity']:.3f}) ===")
    print(f"{len(rows)} wearable rows available (need {WINDOW_DAYS})")

    started = time.monotonic()
    with httpx.Client(base_url=BASE_URL, timeout=HTTP_TIMEOUT_S) as client:
        r = client.post("/patients", json={
            "age": int(round(patient["age"])),
            "sex": patient["sex"],
            "height_cm": float(patient["height_cm"]),
            "weight_kg": float(patient["weight_kg"]),
        })
        r.raise_for_status()
        api_id = r.json()["id"]
        print(f"created patient {api_id}")

        r = client.post(f"/patients/{api_id}/clinical-report", json={
            "ejection_fraction_pct": float(patient["ejection_fraction_pct"]),
            "nt_probnp_pg_ml": float(patient["nt_probnp_pg_ml"]),
        })
        r.raise_for_status()

        start_date = datetime.date.today() - datetime.timedelta(days=WINDOW_DAYS)
        for i, row in enumerate(rows):
            r = client.post(f"/patients/{api_id}/wearable-sync", json={
                "recorded_date": str(start_date + datetime.timedelta(days=i)),
                "resting_hr_bpm": row["resting_hr_bpm"],
                "spo2_pct": row["spo2_pct"],
                "weight_kg": row["weight_kg"],
                "steps_per_day": row["steps_per_day"],
                "sleep_hours": row["sleep_hours"],
                "hrv_rmssd_ms": row["hrv_rmssd_ms"],
            })
            r.raise_for_status()
        print(f"{len(rows)} days synced -- background Pulse pipeline should now be running")

        elapsed = 0
        status = None
        while elapsed < POLL_TIMEOUT_S:
            status = client.get(f"/patients/{api_id}/status").json()
            wall = time.monotonic() - started
            print(f"  [t={wall:.1f}s] status: {status['simulation_status']}")
            if status["simulation_status"] in ("complete", "failed"):
                break
            time.sleep(POLL_INTERVAL_S)
            elapsed += POLL_INTERVAL_S

    wall_clock_s = time.monotonic() - started
    print()
    print(f"FINAL: status={status.get('simulation_status')}, wall_clock_s={wall_clock_s:.1f}")
    print(f"error_message: {status.get('error_message')}")
    if status.get("latest_assessment"):
        a = status["latest_assessment"]
        print(f"predicted scenario_type={a.get('scenario_type')}, severity={a.get('severity')}")


if __name__ == "__main__":
    main()
