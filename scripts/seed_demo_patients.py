"""Seeds five clearly labelled DEMO patients through the live API, the same way the dashboard's
Simulation Lab wizard does (POST /patients -> POST .../clinical-report -> 21 daily
POST .../wearable-sync), so a presentation starts with completed assessments instead of an empty
dashboard and no live Pulse call has to succeed on stage.

Every patient is synthetic and labelled "DEMO ..." -- none represents a real person. Trends are
linear start->end interpolations with small, seeded noise (same shape as
frontend/src/utils/syntheticTrend.js), so a re-run produces the same readings.

Patients are run ONE AT A TIME: each one triggers 4 real Pulse runs (assessment + 7/14/30-day
projections, several minutes) and Docker's memory use peaks while they run. Patients whose label
already exists are skipped (their current status is printed), so the script is safe to re-run after
an interruption. Keep the machine plugged in and awake while it runs: if the laptop sleeps, Pulse
pauses with it, and the wait here can expire even though the run resumes on wake.

Usage (stack running, e.g. `docker compose up -d`):
    python scripts/seed_demo_patients.py                      # http://localhost:8000
    python scripts/seed_demo_patients.py --base-url http://localhost:8010
    python scripts/seed_demo_patients.py --no-wait            # submit only, don't wait for Pulse

Standard library only -- no project imports, runs from any Python 3.9+.
"""
from __future__ import annotations

import argparse
import datetime
import json
import random
import sys
import time
import urllib.error
import urllib.request

WINDOW_DAYS = 21
NOISE = {"hr": 1.5, "spo2": 0.3, "weight": 0.15, "steps": 400, "sleep": 0.3, "hrv": 1.5}

# start/end vitals per day-1 and day-21; weight is a delta from the patient's baseline weight.
STABLE = {"start": dict(hr=72, spo2=97, weight=0.0, steps=7500, sleep=7.0, hrv=32),
          "end": dict(hr=73, spo2=97, weight=0.1, steps=7300, sleep=6.9, hrv=31)}
MILD_DECLINE = {"start": dict(hr=74, spo2=96.5, weight=0.0, steps=7000, sleep=7.0, hrv=30),
                "end": dict(hr=84, spo2=95.5, weight=1.2, steps=5500, sleep=6.3, hrv=24)}
FLUID_GAIN = {"start": dict(hr=74, spo2=96.5, weight=0.0, steps=6500, sleep=6.8, hrv=29),
              "end": dict(hr=79, spo2=95.5, weight=3.5, steps=5600, sleep=6.3, hrv=26)}
CARDIAC_STRESS = {"start": dict(hr=75, spo2=96.5, weight=0.0, steps=7000, sleep=6.9, hrv=31),
                  "end": dict(hr=98, spo2=95.8, weight=0.4, steps=5200, sleep=6.2, hrv=19)}

DEMO_PATIENTS = [
    {"label": "DEMO 1 - Stable (EF 58)", "age": 62, "sex": "Female", "height_cm": 163, "weight_kg": 70,
     "ef": 58.0, "bnp": 120.0, "trend": STABLE},
    {"label": "DEMO 2 - EF 30, mild decline", "age": 68, "sex": "Male", "height_cm": 172, "weight_kg": 82,
     "ef": 30.0, "bnp": 2500.0, "trend": MILD_DECLINE},
    {"label": "DEMO 3 - EF not measured", "age": 68, "sex": "Male", "height_cm": 172, "weight_kg": 82,
     "ef": None, "bnp": 2500.0, "trend": MILD_DECLINE},
    {"label": "DEMO 4 - Fluid-overload trend", "age": 71, "sex": "Female", "height_cm": 160, "weight_kg": 76,
     "ef": 35.0, "bnp": 3200.0, "trend": FLUID_GAIN},
    {"label": "DEMO 5 - Cardiac-stress trend", "age": 59, "sex": "Male", "height_cm": 178, "weight_kg": 88,
     "ef": 40.0, "bnp": 1500.0, "trend": CARDIAC_STRESS},
]


def call(base_url: str, method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base_url + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"null")


def build_readings(trend: dict, weight_kg: float, seed: int, end_date: datetime.date) -> list[dict]:
    rng = random.Random(seed)

    def noise(mag: float) -> float:
        return (rng.random() - 0.5) * 2 * mag

    readings = []
    for i in range(WINDOW_DAYS):
        t = i / (WINDOW_DAYS - 1)
        v = {k: trend["start"][k] + (trend["end"][k] - trend["start"][k]) * t for k in trend["start"]}
        readings.append({
            "recorded_date": (end_date - datetime.timedelta(days=WINDOW_DAYS - 1 - i)).isoformat(),
            "resting_hr_bpm": round(v["hr"] + noise(NOISE["hr"]), 1),
            "spo2_pct": round(min(100.0, v["spo2"] + noise(NOISE["spo2"])), 1),
            "weight_kg": round(weight_kg + v["weight"] + noise(NOISE["weight"]), 1),
            "steps_per_day": max(0, round(v["steps"] + noise(NOISE["steps"]))),
            "sleep_hours": round(max(0.0, v["sleep"] + noise(NOISE["sleep"])), 1),
            "hrv_rmssd_ms": round(max(0.0, v["hrv"] + noise(NOISE["hrv"])), 1),
        })
    return readings


def is_finished(status: dict) -> bool:
    return status["simulation_status"] == "failed" or (
        status["simulation_status"] == "complete" and status["latest_assessment"] is not None
    )


def wait_for_assessment(base_url: str, patient_id: str, timeout_s: int) -> dict | None:
    """Returns the final /status payload, or None if still running after `timeout_s`."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        status = call(base_url, "GET", f"/patients/{patient_id}/status")
        if is_finished(status):
            return status
        time.sleep(15)
    return None


def summarize(status: dict) -> str:
    a = status.get("latest_assessment")
    if status["simulation_status"] == "failed" or a is None:
        first_line = (status.get("error_message") or "").splitlines()[:1]
        return f"FAILED: {first_line}"
    alert = (status.get("alert") or {}).get("level")
    return (f"{a['scenario_type']}, severity {a['severity']:.2f}, risk {a['risk_score']:.3f} "
            f"{a['risk_bucket']}, NYHA {a['nyha_class']}, alert {alert}, "
            f"EF defaulted: {a.get('ef_is_fallback')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--no-wait", action="store_true", help="submit data without waiting for Pulse")
    parser.add_argument("--timeout", type=int, default=1800, help="seconds to wait per patient")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    try:
        existing = {p.get("label"): p["id"] for p in call(base, "GET", "/patients")}
    except urllib.error.URLError as e:
        print(f"Cannot reach the API at {base}: {e}. Is the stack running?", file=sys.stderr)
        return 1

    end_date = datetime.date.today() - datetime.timedelta(days=1)
    exit_code = 0
    for n, demo in enumerate(DEMO_PATIENTS, start=1):
        if demo["label"] in existing:
            status = call(base, "GET", f"/patients/{existing[demo['label']]}/status")
            state = summarize(status) if is_finished(status) else status["simulation_status"]
            print(f"[skip] {demo['label']} already exists -> {state}", flush=True)
            continue
        patient = call(base, "POST", "/patients", {k: demo[k] for k in ("label", "age", "sex", "height_cm", "weight_kg")})
        if patient.get("label") != demo["label"]:
            print(f"[warn] API did not store the label for {demo['label']} -- backend predates the "
                  "`label` field on POST /patients; the patient will show as 'Patient #XXXX'.")
        call(base, "POST", f"/patients/{patient['id']}/clinical-report",
             {"ejection_fraction_pct": demo["ef"], "nt_probnp_pg_ml": demo["bnp"]})
        for reading in build_readings(demo["trend"], demo["weight_kg"], seed=1000 + n, end_date=end_date):
            last = call(base, "POST", f"/patients/{patient['id']}/wearable-sync", reading)
        print(f"[submitted] {demo['label']} ({patient['id']}): {last['message']}", flush=True)
        if args.no_wait:
            continue

        status = wait_for_assessment(base, patient["id"], args.timeout)
        if status is None:
            exit_code = exit_code or 3
            print(f"  -> still running after {args.timeout}s (it continues server-side); re-run this "
                  "script later to see its result.", flush=True)
            continue
        if status["simulation_status"] == "failed" or status.get("latest_assessment") is None:
            exit_code = 2
        print(f"  -> {summarize(status)}", flush=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
