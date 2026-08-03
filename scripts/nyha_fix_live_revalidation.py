"""One-off re-validation of the nyha_ordinal fix (see docs/methodology.md Sec 9,
docs/real_world_data_integration.md Sec 8.2): replays a small stratified sample of SYNTHETIC
patients (known ground-truth severity, unlike the real PerHeart cohort) through the live,
already-fixed API, using the same proven-reliable infrastructure as this session's PerHeart replay
-- not the standalone kitware/pulse:4.3.1 image, which was observed to time out on every call in
this environment regardless of scenario type (an unrelated, pre-existing environment issue, not
something introduced by the fix).

Directly computes live severity MAE against real ground truth, the same comparison Phase 8 (real
mode) makes -- gives an apples-to-apples number against the documented 0.271 baseline.

Usage: python -m scripts.nyha_fix_live_revalidation [n_per_scenario]
"""
import datetime
import sys

import httpx
import pandas as pd

REPO_ROOT = r"C:\Users\sange\Downloads\M2K-HF-PULSE-repo"
BASE_URL = "http://localhost:8000"
WINDOW_DAYS = 21

n_per_scenario = int(sys.argv[1]) if len(sys.argv) > 1 else 2

patients_df = pd.read_csv(f"{REPO_ROOT}/data/synthetic/patients.csv")
wearable_df = pd.read_csv(f"{REPO_ROOT}/data/synthetic/wearable_trends.csv")

sample = (
    patients_df.groupby("scenario_type", group_keys=False)
    .sample(n=n_per_scenario, random_state=99)
    .reset_index(drop=True)
)

client = httpx.Client(base_url=BASE_URL, timeout=60.0)
results = []

for _, patient in sample.iterrows():
    pid_label = patient["patient_id"]
    print(f"\n=== {pid_label} ({patient['scenario_type']}, true severity={patient['severity']:.3f}) ===")

    r = client.post("/patients", json={
        "age": int(round(patient["age"])),
        "sex": patient["sex"],
        "height_cm": float(patient["height_cm"]),
        "weight_kg": float(patient["weight_kg"]),
    })
    r.raise_for_status()
    api_id = r.json()["id"]

    client.post(f"/patients/{api_id}/clinical-report", json={
        "ejection_fraction_pct": float(patient["ejection_fraction_pct"]),
        "nt_probnp_pg_ml": float(patient["nt_probnp_pg_ml"]),
    }).raise_for_status()

    rows = (
        wearable_df[wearable_df["patient_id"] == pid_label]
        .sort_values("day")
        .head(WINDOW_DAYS)
        .to_dict("records")
    )
    if len(rows) < WINDOW_DAYS:
        print(f"  SKIP: only {len(rows)} wearable rows")
        continue

    start_date = datetime.date.today() - datetime.timedelta(days=WINDOW_DAYS)
    for i, row in enumerate(rows):
        resp = client.post(f"/patients/{api_id}/wearable-sync", json={
            "recorded_date": str(start_date + datetime.timedelta(days=i)),
            "resting_hr_bpm": row["resting_hr_bpm"],
            "spo2_pct": row["spo2_pct"],
            "weight_kg": row["weight_kg"],
            "steps_per_day": row["steps_per_day"],
            "sleep_hours": row["sleep_hours"],
            "hrv_rmssd_ms": row["hrv_rmssd_ms"],
        })
        resp.raise_for_status()

    print("  synced 21 days, polling for completion...")
    import time
    status = None
    for _ in range(90):
        s = client.get(f"/patients/{api_id}/status").json()
        if s["simulation_status"] in ("complete", "failed"):
            status = s
            break
        time.sleep(10)
    if status is None:
        status = client.get(f"/patients/{api_id}/status").json()

    assessment = status.get("latest_assessment") or {}
    pred_severity = assessment.get("severity")
    true_severity = float(patient["severity"])
    results.append({
        "patient_id": pid_label,
        "true_scenario_type": patient["scenario_type"],
        "true_severity": true_severity,
        "predicted_scenario_type": assessment.get("scenario_type"),
        "predicted_severity": pred_severity,
        "severity_abs_error": abs(pred_severity - true_severity) if pred_severity is not None else None,
        "simulation_status": status["simulation_status"],
    })
    print(f"  -> {status['simulation_status']}: predicted severity={pred_severity}, "
          f"abs_error={results[-1]['severity_abs_error']}")

results_df = pd.DataFrame(results)
print("\n\n=== SUMMARY ===")
print(results_df.to_string(index=False))
completed = results_df[results_df.simulation_status == "complete"]
if len(completed):
    print(f"\nCompleted: {len(completed)}/{len(results_df)}")
    print(f"Live severity MAE (post-fix): {completed['severity_abs_error'].mean():.3f}")
    print("Compare against: 0.048 offline (this session's retrain), 0.271 live pre-fix (Phase 8, methodology.md Sec 7/8)")
results_df.to_csv(f"{REPO_ROOT}/data/validation_runs/nyha_fix_live_revalidation.csv", index=False)
print(f"\nWrote {REPO_ROOT}/data/validation_runs/nyha_fix_live_revalidation.csv")
