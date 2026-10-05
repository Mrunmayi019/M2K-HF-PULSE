"""results-v1 offline analysis (4/4): API read-endpoint timing. Real FastAPI app + SQLite (no
Pulse mocking needed for the READ endpoints themselves -- Pulse only runs on write/sync; this
seeds one patient through a mocked-Pulse pipeline once, then times repeated reads).

Usage:
    PYTHONPATH=. python3 -m src.evaluation.results_v1_offline.api_timing
"""
from __future__ import annotations

import datetime
import json
import pathlib
import statistics
import tempfile
import time
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from src.api.database import Base, get_db
from src.api.main import app
from src.api.services import WEARABLE_WINDOW_DAYS

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "results" / "results_v1_offline"

VALID_READING = {
    "resting_hr_bpm": 70, "spo2_pct": 97, "weight_kg": 80,
    "steps_per_day": 6000, "sleep_hours": 7, "hrv_rmssd_ms": 35,
}


class _FakeModel:
    def __init__(self, value):
        self.value = value

    def predict(self, x):
        return [self.value] * len(x)


def _fake_pulse_df():
    return pd.DataFrame({
        "Time(s)": [0, 600], "HeartRate(1/min)": [71, 71], "MeanArterialPressure(mmHg)": [95, 95],
        "CardiacOutput(mL/min)": [5000, 5000], "HeartStrokeVolume(mL)": [70, 70],
        "OxygenSaturation": [0.0, 0.0], "LeftHeart-Volume(mL)": [100.0, 100.0],
        "LeftHeart-Pressure(mmHg)": [80.0, 80.0], "ECG-Lead3ElectricPotential(mV)": [0.0, 0.0],
    })


def time_calls(fn, n=50):
    times = []
    for _ in range(n):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000)
    times.sort()
    return {
        "n": n, "mean_ms": round(statistics.mean(times), 2),
        "median_ms": round(statistics.median(times), 2),
        "p95_ms": round(times[int(0.95 * n) - 1], 2),
        "min_ms": round(min(times), 2), "max_ms": round(max(times), 2),
    }


def main():
    tmp_dir = tempfile.mkdtemp()
    db_path = pathlib.Path(tmp_dir) / "timing.db"
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    scenarios_dir = pathlib.Path(tmp_dir) / "scenarios"

    with patch("src.api.routes.SessionLocal", TestSessionLocal), \
         patch("src.api.services.SCENARIOS_DIR", scenarios_dir), \
         TestClient(app) as client:

        r = client.post("/patients", json={"age": 65, "sex": "Male", "height_cm": 175, "weight_kg": 80})
        pid = r.json()["id"]
        client.post(f"/patients/{pid}/clinical-report", json={"ejection_fraction_pct": 55, "nt_probnp_pg_ml": 300})

        with patch("src.api.services._load_scenario_classifier_models",
                   return_value=(_FakeModel("stable"), _FakeModel(0.1))), \
             patch("src.pulse_runner.runner.run_pulse", return_value=_fake_pulse_df()):
            start = datetime.date(2026, 1, 1)
            for i in range(WEARABLE_WINDOW_DAYS):
                client.post(f"/patients/{pid}/wearable-sync",
                            json={"recorded_date": str(start + datetime.timedelta(days=i)), **VALID_READING})

        assert client.get(f"/patients/{pid}/status").json()["simulation_status"] == "complete"

        results = {
            "status": time_calls(lambda: client.get(f"/patients/{pid}/status")),
            "history": time_calls(lambda: client.get(f"/patients/{pid}/history")),
            "wearable_history": time_calls(lambda: client.get(f"/patients/{pid}/wearable-history")),
            "projection": time_calls(lambda: client.get(f"/patients/{pid}/projection")),
            "report": time_calls(lambda: client.get(f"/patients/{pid}/report")),
        }

    app.dependency_overrides.clear()

    print(json.dumps(results, indent=2))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "api_timing.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
