"""Shared fixtures for the feature-flag tests (feature/wire-research-features). Only defines new,
uniquely named fixtures, so existing test files are unaffected."""
from __future__ import annotations

import datetime
import json
import pathlib
import threading
import time
from unittest.mock import patch

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.database import Base, get_db
from src.patient_builder.scenario_file import STABILIZATION_S

FLAG_ENV_VARS = (
    "PIPELINE_MODE",
    "ENABLE_BCG_MODIFIERS",
    "ENABLE_HR_BASELINE",
    "ENABLE_ALERT_HYSTERESIS",
    "ENABLE_SCENARIO_PERSISTENCE",
)

READING = {
    "resting_hr_bpm": 70,
    "spo2_pct": 97,
    "weight_kg": 80,
    "steps_per_day": 6000,
    "sleep_hours": 7,
    "hrv_rmssd_ms": 35,
}
START_DATE = datetime.date(2026, 1, 1)


def fake_pulse_df(hr_start=71, hr_end=71, map_start=95, map_end=95, co_start=5000, co_end=5000, sv_start=70, sv_end=70):
    return pd.DataFrame(
        {
            "Time(s)": [0, 600],
            "HeartRate(1/min)": [hr_start, hr_end],
            "MeanArterialPressure(mmHg)": [map_start, map_end],
            "CardiacOutput(mL/min)": [co_start, co_end],
            "HeartStrokeVolume(mL)": [sv_start, sv_end],
            "OxygenSaturation": [0.0, 0.0],
            "LeftHeart-Volume(mL)": [100.0, 100.0],
            "LeftHeart-Pressure(mmHg)": [60.0, 60.0],
            "ECG-Lead3ElectricPotential(mV)": [0.0, 0.0],
        }
    )


class FakeModel:
    def __init__(self, value):
        self.value = value

    def predict(self, x):
        return [self.value] * len(x)


def classifier(scenario_type="stable", severity=0.1):
    return (FakeModel(scenario_type), FakeModel(severity))


class FakeContinuousPulse:
    """Stands in for cli_state_runner.run_initial()/resume_and_advance(). Each saved state is a
    JSON blob naming its own serial number and its parent's, so a test can check exactly which
    state each run resumed from. Records every call's kwargs. `fail_days` are 1-based call
    numbers that raise; `delay_s` makes each call slow enough for two threads to overlap."""

    def __init__(self, fail_calls=(), delay_s=0.0, df=None):
        self.calls: list[tuple[str, dict]] = []
        self.fail_calls = set(fail_calls)
        self.delay_s = delay_s
        self.df = df if df is not None else fake_pulse_df()
        self._lock = threading.Lock()
        self._serial = 0

    def _next(self, kind, kwargs):
        with self._lock:
            self.calls.append((kind, kwargs))
            n = len(self.calls)
            self._serial += 1
            serial = self._serial
        if self.delay_s:
            time.sleep(self.delay_s)
        if n in self.fail_calls:
            raise RuntimeError(f"simulated Pulse crash on call {n}")
        return serial

    def run_initial(self, **kwargs):
        serial = self._next("initial", kwargs)
        t = STABILIZATION_S + kwargs["duration_s"]
        return json.dumps({"serial": serial, "parent": None, "t": t}), {"simulation_time_s": t}, self.df

    def resume_and_advance(self, **kwargs):
        serial = self._next("resume", kwargs)
        parent = json.loads(kwargs["state_json"])["serial"]
        t = kwargs["prior_offset_s"] + kwargs["duration_s"]
        return json.dumps({"serial": serial, "parent": parent, "t": t}), {"simulation_time_s": t}, self.df

    def patches(self):
        return [
            patch("src.api.continuous_state_pipeline.run_initial", side_effect=self.run_initial),
            patch("src.api.continuous_state_pipeline.resume_and_advance", side_effect=self.resume_and_advance),
        ]


@pytest.fixture()
def flags_off(monkeypatch):
    for var in FLAG_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


@pytest.fixture()
def research_api(tmp_path, flags_off):
    """(TestClient, session_factory) on an isolated file SQLite DB, every flag off to start with
    (set them with the returned monkeypatch via `flags_off`). Pulse is NOT mocked here -- each test
    patches what it needs."""
    from fastapi.testclient import TestClient

    from src.api.main import app

    engine = create_engine(f"sqlite:///{tmp_path / 'research.db'}", connect_args={"check_same_thread": False})
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with patch("src.api.routes.SessionLocal", Session), \
         patch("src.api.services.SCENARIOS_DIR", tmp_path / "scenarios_fresh"), \
         patch("src.api.continuous_state_pipeline.SCENARIOS_DIR", tmp_path / "scenarios_continuous"), \
         TestClient(app) as client:
        yield client, Session
    app.dependency_overrides.clear()
    engine.dispose()


def create_patient(client, **overrides) -> str:
    body = {"age": 60, "sex": "Male", "height_cm": 175, "weight_kg": 80, **overrides}
    r = client.post("/patients", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def sync(client, patient_id, day: int, **reading_overrides):
    body = {"recorded_date": str(START_DATE + datetime.timedelta(days=day)), **READING, **reading_overrides}
    return client.post(f"/patients/{patient_id}/wearable-sync", json=body)


def fill_window(client, patient_id, days: int = 21):
    r = None
    for i in range(days):
        r = sync(client, patient_id, i)
    return r
