"""Live check for PIPELINE_MODE=continuous (feature/wire-research-features, section A5), with the
real Pulse engine and the frozen results-v1 models, through the real API routes.

One patient: 21 baseline wearable days (the 21st triggers the initial run), then 4 more days -> 5
consecutive daily runs. Checks that every run saved a state and the next one loaded it (simulation
time +600 s per day, each state's time = previous + 600). Then POST /reset-state, one more day,
and checks the run was a fresh start (time back to 660 s) with all earlier history kept.

Runs the routes in-process with FastAPI's TestClient (background tasks run inline), against a
throwaway SQLite DB -- the same route and pipeline code uvicorn would run. Every other flag is
off. Must run inside the backend image (Pulse at /pulse/bin):

    docker run --rm -v "<repo>:/workspace" -w /workspace -e PIPELINE_MODE=continuous \\
        m2k-hf-pulse-release-pulse-backend:latest python -m scripts.verify_continuous_mode_live

Writes results/live_checks/continuous_mode_live.json.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import sys
import tempfile
import time
from unittest.mock import patch

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "results" / "live_checks" / "continuous_mode_live.json"
BASE_DATE = datetime.date(2026, 3, 1)
READING = {"resting_hr_bpm": 74, "spo2_pct": 96, "weight_kg": 84, "steps_per_day": 5200, "sleep_hours": 6.8, "hrv_rmssd_ms": 31}


def main():
    if os.environ.get("PIPELINE_MODE") != "continuous":
        sys.exit("set PIPELINE_MODE=continuous")
    for f in ("scenario_classifier.joblib", "severity_regressor.joblib"):
        live = hashlib.sha256((REPO_ROOT / "models" / f).read_bytes()).hexdigest()
        frozen = hashlib.sha256((REPO_ROOT / "artifacts" / "results-v1" / "models" / f).read_bytes()).hexdigest()
        if live != frozen:
            sys.exit(f"models/{f} does not match the frozen results-v1 model")

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.api import models
    from src.api.database import Base, get_db
    from src.api.main import app

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="cm_live_"))
    engine = create_engine(f"sqlite:///{tmp / 'live.db'}", connect_args={"check_same_thread": False})
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    log = {"days": [], "checks": {}}

    def states(pid):
        with Session() as db:
            return [
                {"id": s.id, "simulation_time_s": s.simulation_time_s,
                 "state_sha256": hashlib.sha256(s.state_json.encode()).hexdigest()[:16],
                 "state_bytes": len(s.state_json), "state_started_at": str(s.state_started_at)}
                for s in db.query(models.PulseState).filter_by(patient_id=pid).order_by(models.PulseState.id)
            ]

    def runs(pid):
        with Session() as db:
            return [(r.status, r.scenario_type, r.severity, r.error_message)
                    for r in db.query(models.SimulationRun).filter_by(patient_id=pid).order_by(models.SimulationRun.id)]

    with patch("src.api.routes.SessionLocal", Session), \
         patch("src.api.continuous_state_pipeline.SCENARIOS_DIR", tmp / "scenarios"), \
         TestClient(app) as client:
        pid = client.post("/patients", json={"age": 62, "sex": "Male", "height_cm": 176, "weight_kg": 84,
                                             "label": "live continuous check"}).json()["id"]
        client.post(f"/patients/{pid}/clinical-report", json={"ejection_fraction_pct": 45, "nt_probnp_pg_ml": 400})

        def day(i, **over):
            body = {"recorded_date": str(BASE_DATE + datetime.timedelta(days=i)), **READING, **over}
            t0 = time.monotonic()
            r = client.post(f"/patients/{pid}/wearable-sync", json=body).json()
            return r, round(time.monotonic() - t0, 1)

        for i in range(20):
            day(i)
        for n, i in enumerate(range(20, 25), start=1):
            r, wall = day(i, resting_hr_bpm=74 + 0.5 * n)
            st = states(pid)
            twin = client.get(f"/patients/{pid}/twin-state").json()
            entry = {"run_n": n, "sync_status": r["status"], "wall_s": wall, "states_saved": len(st),
                     "simulation_time_s": st[-1]["simulation_time_s"] if st else None,
                     "last_run": runs(pid)[-1][:3], "engine_lag_days": twin["engine_lag_days"]}
            log["days"].append(entry)
            print(json.dumps(entry), flush=True)

        before_reset = states(pid)
        reset = client.post(f"/patients/{pid}/reset-state").json()
        pending = client.get(f"/patients/{pid}/twin-state").json()
        r, wall = day(25, resting_hr_bpm=77)
        after_reset = states(pid)
        twin_after = client.get(f"/patients/{pid}/twin-state").json()
        history = client.get(f"/patients/{pid}/history").json()["assessments"]
        status = client.get(f"/patients/{pid}/status").json()
        log["reset"] = {"response": reset, "twin_state_pending": pending, "post_reset_wall_s": wall,
                        "twin_state_after": twin_after}
        log["states"] = after_reset
        log["runs"] = runs(pid)
        print(json.dumps({"after_reset": after_reset[-1], "wall_s": wall}), flush=True)

    times = [s["simulation_time_s"] for s in before_reset]
    completed = [r for r in log["runs"][:5] if r[0] == "complete"]
    c = log["checks"]
    c["five_runs_completed"] = len(completed) == 5
    c["five_states_saved"] = len(before_reset) == 5
    c["first_run_660s"] = times[:1] == [660.0]
    c["plus_600s_each_day"] = all(abs(b - a - 600.0) < 1e-6 for a, b in zip(times, times[1:]))
    c["each_state_distinct"] = len({s["state_sha256"] for s in before_reset}) == len(before_reset)
    c["reset_pending_before_next_run"] = pending["reset_pending"] is True
    c["fresh_start_after_reset"] = len(after_reset) == 6 and after_reset[-1]["simulation_time_s"] == 660.0
    c["new_state_started_at"] = after_reset[-1]["state_started_at"] != before_reset[-1]["state_started_at"]
    c["history_kept"] = len(history) == 6 and len(after_reset) == 6
    c["status_complete"] = status["simulation_status"] == "complete"
    log["verdict"] = "PASS" if all(c.values()) else "FAIL"
    print(json.dumps(c, indent=1))
    print("VERDICT:", log["verdict"])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(log, indent=2, default=str))
    app.dependency_overrides.clear()
    engine.dispose()
    sys.exit(0 if log["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
