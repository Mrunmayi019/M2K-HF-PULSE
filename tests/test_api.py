"""Validation tests for the Phase 6 FastAPI backend (src/api/).

No Docker/Pulse required: the background pipeline's run_pulse() calls (both the current-state run
in services.py and the 3 projection re-simulations in src/analytics/projection.py) are mocked,
consistent with every prior phase's testing convention -- pure-Python/DB logic gets full pytest
coverage here; the real Pulse execution path is verified manually inside Docker once (see
docs/methodology.md).

FastAPI's TestClient runs BackgroundTasks synchronously (inline, before the triggering request
returns) when used as a context manager, so the pipeline's DB effects are immediately observable
in the same test -- no polling/sleeping needed.

Run from repo root: pytest tests/test_api.py -v
"""
from __future__ import annotations

import datetime
import pathlib
import tempfile
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src.api.database import Base, get_db
from src.api.main import app
from src.api.services import WEARABLE_WINDOW_DAYS
from src.pulse_runner.runner import PulseExecutionError

VALID_READING = {
    "resting_hr_bpm": 70,
    "spo2_pct": 97,
    "weight_kg": 80,
    "steps_per_day": 6000,
    "sleep_hours": 7,
    "hrv_rmssd_ms": 35,
}


def _fake_pulse_df(hr_start=71, hr_end=71, map_start=95, map_end=95, co_start=5000, co_end=5000, sv_start=70, sv_end=70):
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


class _FakeModel:
    def __init__(self, value):
        self.value = value

    def predict(self, x):
        return [self.value] * len(x)


@pytest.fixture()
def client():
    tmp_dir = tempfile.mkdtemp()
    db_path = pathlib.Path(tmp_dir) / "test.db"
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
    # routes.py imports SessionLocal directly (used as the background task's session factory) --
    # must patch it there, not in services.py, which only receives whatever factory is passed in.
    # SCENARIOS_DIR is hardcoded to the Docker-only /workspace path (matches every other Pulse-
    # writing module's convention) -- redirect it here since tests run on the host, not in Docker.
    with patch("src.api.routes.SessionLocal", TestSessionLocal), \
         patch("src.api.services.SCENARIOS_DIR", scenarios_dir), \
         TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _create_patient(client) -> str:
    r = client.post("/patients", json={"age": 65, "sex": "Male", "height_cm": 175, "weight_kg": 80})
    assert r.status_code == 201
    return r.json()["id"]


def _fill_wearable_window(client, patient_id: str, n: int = WEARABLE_WINDOW_DAYS):
    start = datetime.date(2026, 1, 1)
    for i in range(n):
        r = client.post(
            f"/patients/{patient_id}/wearable-sync",
            json={"recorded_date": str(start + datetime.timedelta(days=i)), **VALID_READING},
        )
    return r  # last response (the one that may trigger the pipeline)


# ---- POST /patients ----

class TestCreatePatient:
    def test_happy_path(self, client):
        r = client.post("/patients", json={"age": 65, "sex": "Male", "height_cm": 175, "weight_kg": 80})
        assert r.status_code == 201
        assert r.json()["age"] == 65

    def test_invalid_age_rejected_422(self, client):
        r = client.post("/patients", json={"age": -5, "sex": "Male", "height_cm": 175, "weight_kg": 80})
        assert r.status_code == 422


# ---- POST /patients/{id}/clinical-report ----

class TestClinicalReport:
    def test_with_values_no_fallback(self, client):
        patient_id = _create_patient(client)
        r = client.post(
            f"/patients/{patient_id}/clinical-report",
            json={"ejection_fraction_pct": 35, "nt_probnp_pg_ml": 1200},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["ejection_fraction_pct"] == 35
        assert body["ef_is_fallback"] is False
        assert body["bnp_is_fallback"] is False

    def test_missing_values_uses_tier1_fallback(self, client):
        patient_id = _create_patient(client)
        r = client.post(f"/patients/{patient_id}/clinical-report", json={})
        assert r.status_code == 201
        body = r.json()
        assert body["ef_is_fallback"] is True
        assert body["bnp_is_fallback"] is True
        assert body["ejection_fraction_pct"] == 62.0
        assert body["nt_probnp_pg_ml"] == 100.0

    def test_unknown_patient_404(self, client):
        r = client.post("/patients/does-not-exist/clinical-report", json={})
        assert r.status_code == 404


# ---- POST /patients/{id}/wearable-sync ----

class TestWearableSync:
    def test_malformed_vitals_422(self, client):
        patient_id = _create_patient(client)
        r = client.post(
            f"/patients/{patient_id}/wearable-sync",
            json={"recorded_date": "2026-01-01", **{**VALID_READING, "resting_hr_bpm": 500}},
        )
        assert r.status_code == 422

    def test_unknown_patient_404(self, client):
        r = client.post(
            "/patients/does-not-exist/wearable-sync",
            json={"recorded_date": "2026-01-01", **VALID_READING},
        )
        assert r.status_code == 404

    def test_collecting_before_window_full(self, client):
        patient_id = _create_patient(client)
        r = client.post(
            f"/patients/{patient_id}/wearable-sync",
            json={"recorded_date": "2026-01-01", **VALID_READING},
        )
        assert r.status_code == 202
        assert r.json()["status"] == "collecting"
        assert r.json()["reading_count"] == 1

    def test_triggers_pipeline_at_window_threshold(self, client):
        patient_id = _create_patient(client)
        client.post(f"/patients/{patient_id}/clinical-report", json={"ejection_fraction_pct": 55, "nt_probnp_pg_ml": 300})

        with patch("src.api.services._load_scenario_classifier_models", return_value=(_FakeModel("stable"), _FakeModel(0.1))), \
             patch("src.api.services.run_pulse", return_value=_fake_pulse_df()), \
             patch("src.analytics.projection.run_pulse", return_value=_fake_pulse_df()):
            r = _fill_wearable_window(client, patient_id)

        assert r.status_code == 202
        assert r.json()["status"] == "simulation_triggered"

        status = client.get(f"/patients/{patient_id}/status").json()
        assert status["simulation_status"] == "complete"
        assert status["latest_assessment"] is not None
        assert status["latest_assessment"]["risk_bucket"] in {"LOW", "MODERATE", "HIGH"}

    def test_pulse_failure_marks_simulation_failed(self, client):
        patient_id = _create_patient(client)
        client.post(f"/patients/{patient_id}/clinical-report", json={"ejection_fraction_pct": 30, "nt_probnp_pg_ml": 2000})

        with patch("src.api.services._load_scenario_classifier_models", return_value=(_FakeModel("acute_deterioration"), _FakeModel(0.8))), \
             patch("src.api.services.run_pulse", side_effect=PulseExecutionError("simulated crash")):
            _fill_wearable_window(client, patient_id)

        status = client.get(f"/patients/{patient_id}/status").json()
        assert status["simulation_status"] == "failed"
        assert "simulated crash" in status["error_message"]


class TestFluidOverloadCaveat:
    def test_risk_caveats_populated_for_fluid_overload(self, client):
        patient_id = _create_patient(client)
        client.post(f"/patients/{patient_id}/clinical-report", json={"ejection_fraction_pct": 30, "nt_probnp_pg_ml": 1500})

        # Matches the real Phase 5 finding: flat deltas, MAP already low but stable at rest.
        flat_df = _fake_pulse_df(hr_start=72, hr_end=70, map_start=78, map_end=78, co_start=4800, co_end=5400, sv_start=67, sv_end=67)
        with patch("src.api.services._load_scenario_classifier_models", return_value=(_FakeModel("fluid_overload"), _FakeModel(0.6))), \
             patch("src.api.services.run_pulse", return_value=flat_df), \
             patch("src.analytics.projection.run_pulse", return_value=flat_df):
            _fill_wearable_window(client, patient_id)

        status = client.get(f"/patients/{patient_id}/status").json()
        assert status["latest_assessment"]["risk_caveats"] is not None
        assert "fluid_overload" in status["latest_assessment"]["risk_caveats"]

    def test_ef_fallback_masking_gets_specific_caveat(self, client):
        """A clinical report IS submitted, with ejection_fraction_pct explicitly null -- matching
        scripts/perheart_real_data_replay.py's real submission shape, not just an absent report
        (a real bug: create_clinical_report() resolves and stores the fallback value at submission
        time, so a naive second apply_tier1_fallback() call downstream always sees a concrete
        number; must reuse the already-stored ef_is_fallback column instead -- see
        docs/real_world_data_integration.md §8.5). A healthy-baseline Pulse df (map_start=95, no
        acute deltas, the _fake_pulse_df default) gives risk_score=0/LOW -> this is the diagnosed
        EF-fallback-masks-the-fix case, not the generic fluid_overload caveat."""
        patient_id = _create_patient(client)
        client.post(f"/patients/{patient_id}/clinical-report", json={"ejection_fraction_pct": None, "nt_probnp_pg_ml": None})

        with patch("src.api.services._load_scenario_classifier_models", return_value=(_FakeModel("fluid_overload"), _FakeModel(0.6))), \
             patch("src.api.services.run_pulse", return_value=_fake_pulse_df()), \
             patch("src.analytics.projection.run_pulse", return_value=_fake_pulse_df()):
            _fill_wearable_window(client, patient_id)

        status = client.get(f"/patients/{patient_id}/status").json()
        assessment = status["latest_assessment"]
        assert assessment["risk_bucket"] == "LOW"
        assert "ejection_fraction_pct was not measured" in assessment["risk_caveats"]
        assert "healthy-population-mean fallback" in assessment["risk_caveats"]

    def test_real_ef_still_gets_generic_caveat_not_the_fallback_one(self, client):
        """Same congested-but-flat Pulse response as test_risk_caveats_populated_for_fluid_overload
        (a real, measured EF submitted) -> must stay on the generic message; the fallback-specific
        one requires ef_is_fallback, which is False here."""
        patient_id = _create_patient(client)
        client.post(f"/patients/{patient_id}/clinical-report", json={"ejection_fraction_pct": 30, "nt_probnp_pg_ml": 1500})

        flat_df = _fake_pulse_df(hr_start=72, hr_end=70, map_start=78, map_end=78, co_start=4800, co_end=5400, sv_start=67, sv_end=67)
        with patch("src.api.services._load_scenario_classifier_models", return_value=(_FakeModel("fluid_overload"), _FakeModel(0.6))), \
             patch("src.api.services.run_pulse", return_value=flat_df), \
             patch("src.analytics.projection.run_pulse", return_value=flat_df):
            _fill_wearable_window(client, patient_id)

        status = client.get(f"/patients/{patient_id}/status").json()
        caveats = status["latest_assessment"]["risk_caveats"]
        assert "risk_score is known to underestimate severity for this presentation" in caveats
        assert "ejection_fraction_pct was not measured" not in caveats

    def test_ecg_only_caveat_for_non_fluid_overload_scenario(self, client):
        """Since 716c13d (2026-09-02), risk_caveats is never None for a completed run -- the
        ECG-reference-template caveat (docs/methodology.md §4.2) is appended for every
        scenario_type, not just fluid_overload. A non-fluid_overload scenario gets ONLY that ECG
        caveat, with no fluid_overload-specific text prepended."""
        patient_id = _create_patient(client)
        client.post(f"/patients/{patient_id}/clinical-report", json={"ejection_fraction_pct": 60, "nt_probnp_pg_ml": 150})

        with patch("src.api.services._load_scenario_classifier_models", return_value=(_FakeModel("stable"), _FakeModel(0.05))), \
             patch("src.api.services.run_pulse", return_value=_fake_pulse_df()), \
             patch("src.analytics.projection.run_pulse", return_value=_fake_pulse_df()):
            _fill_wearable_window(client, patient_id)

        status = client.get(f"/patients/{patient_id}/status").json()
        caveats = status["latest_assessment"]["risk_caveats"]
        assert caveats is not None
        assert "fluid_overload" not in caveats
        assert "not an input to the scenario classifier or severity regressor" in caveats


# ---- GET endpoints ----

class TestStatus:
    def test_unknown_patient_404(self, client):
        assert client.get("/patients/does-not-exist/status").status_code == 404

    def test_collecting_state_before_any_readings(self, client):
        patient_id = _create_patient(client)
        r = client.get(f"/patients/{patient_id}/status")
        assert r.status_code == 200
        assert r.json()["simulation_status"] == "collecting"


class TestHistory:
    def test_unknown_patient_404(self, client):
        assert client.get("/patients/does-not-exist/history").status_code == 404

    def test_returns_assessments_in_chronological_order(self, client):
        patient_id = _create_patient(client)
        client.post(f"/patients/{patient_id}/clinical-report", json={"ejection_fraction_pct": 55, "nt_probnp_pg_ml": 300})
        with patch("src.api.services._load_scenario_classifier_models", return_value=(_FakeModel("stable"), _FakeModel(0.05))), \
             patch("src.api.services.run_pulse", return_value=_fake_pulse_df()), \
             patch("src.analytics.projection.run_pulse", return_value=_fake_pulse_df()):
            _fill_wearable_window(client, patient_id)

        r = client.get(f"/patients/{patient_id}/history")
        assert r.status_code == 200
        assert len(r.json()["assessments"]) == 1


class TestWearableHistory:
    def test_unknown_patient_404(self, client):
        assert client.get("/patients/does-not-exist/wearable-history").status_code == 404

    def test_returns_readings_in_chronological_order(self, client):
        patient_id = _create_patient(client)
        _fill_wearable_window(client, patient_id, n=3)

        r = client.get(f"/patients/{patient_id}/wearable-history")
        assert r.status_code == 200
        body = r.json()
        assert body["patient_id"] == patient_id
        dates = [reading["recorded_date"] for reading in body["readings"]]
        assert dates == sorted(dates)
        assert len(dates) == 3


class TestProjection:
    def test_unknown_patient_404(self, client):
        assert client.get("/patients/does-not-exist/projection").status_code == 404

    def test_not_available_before_assessment(self, client):
        patient_id = _create_patient(client)
        r = client.get(f"/patients/{patient_id}/projection")
        assert r.status_code == 200
        assert r.json()["available"] is False

    def test_available_after_pipeline_completes(self, client):
        patient_id = _create_patient(client)
        client.post(f"/patients/{patient_id}/clinical-report", json={"ejection_fraction_pct": 55, "nt_probnp_pg_ml": 300})
        with patch("src.api.services._load_scenario_classifier_models", return_value=(_FakeModel("stable"), _FakeModel(0.05))), \
             patch("src.api.services.run_pulse", return_value=_fake_pulse_df()), \
             patch("src.analytics.projection.run_pulse", return_value=_fake_pulse_df()):
            _fill_wearable_window(client, patient_id)

        r = client.get(f"/patients/{patient_id}/projection")
        assert r.status_code == 200
        assert r.json()["available"] is True
        assert set(r.json()["horizons"].keys()) == {"7", "14", "30"}


class TestReport:
    def test_unknown_patient_404(self, client):
        assert client.get("/patients/does-not-exist/report").status_code == 404

    def test_combines_status_and_projection(self, client):
        patient_id = _create_patient(client)
        r = client.get(f"/patients/{patient_id}/report")
        assert r.status_code == 200
        body = r.json()
        assert body["status"]["patient_id"] == patient_id
        assert body["projection"]["patient_id"] == patient_id
