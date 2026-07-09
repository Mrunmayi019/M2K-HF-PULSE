"""Phase 8 (roadmap task 8.1): full-pipeline batch validation.

Runs a stratified sample of synthetic patients through the *live API* exactly the way a real
deployment would see them -- POST /patients -> POST /clinical-report -> 21x POST /wearable-sync
(replaying that patient's real synthetic wearable trend) -- which triggers the same background
pipeline production traffic would trigger: ML Model 1 (scenario classification) -> patient_builder
-> run_pulse() -> simulation_features -> risk_score + staging -> deterioration_rate ->
project_physiology(). This is a different validation from scripts/validate_phase2.py (one
hand-picked patient per scenario, calls run_pulse() directly) and src/pulse_runner/batch_runner.py
(the low-level simulation-feature dataset, also calls run_pulse() directly): this script is the
only one that drives the actual FastAPI routes/services/schemas end to end, batched, the way
Phase 6/7's manual single-patient verification (docs/methodology.md §7) did once by hand.

Two modes:
  --mock   Patches run_pulse (both src.api.services and src.analytics.projection call sites) with
           a scenario/severity-aware synthetic Pulse response, mirroring tests/test_api.py's
           _fake_pulse_df() convention. No Docker needed -- validates the orchestration,
           checkpointing, and reporting logic in this script itself, not physiological accuracy.
  (default) Hits the real PulseScenarioDriver. Must run inside the kitware/pulse Docker container
           (same requirement as batch_runner.py) and requires models/scenario_classifier.joblib +
           models/severity_regressor.joblib to already exist (regenerate with
           `python3 -m src.scenario_classifier.train` if missing).

Usage (run from repo root):
    python3 -m scripts.validate_phase8 --n-per-scenario 5 --workers 4
    python3 -m scripts.validate_phase8 --mock --n-per-scenario 2   # fast, no Docker, self-test

Writes data/validation_runs/<timestamp>/results.csv (checkpointed per patient) and summary.md
(aggregate sanity report) once the batch completes.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import pathlib
import tempfile
import time
from unittest.mock import patch

import pandas as pd

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
PATIENTS_CSV = REPO_ROOT / "data" / "synthetic" / "patients.csv"
WEARABLE_CSV = REPO_ROOT / "data" / "synthetic" / "wearable_trends.csv"
VALIDATION_RUNS_DIR = REPO_ROOT / "data" / "validation_runs"

DEFAULT_N_PER_SCENARIO = 5  # 5 scenarios x 5 = 25 patients, within the roadmap's 20-30 target
DEFAULT_WORKERS = 4  # same default as batch_runner.py, same reasoning (arm64->amd64 emulation)
WEARABLE_WINDOW_DAYS = 21

# Loosely grounded in docs/methodology.md §7's Phase 2 single-patient reference table (severity
# ~0.5). Used ONLY in --mock mode to produce scenario-differentiated fake Pulse output so the
# downstream risk-bucket/NYHA logic is exercised meaningfully -- not a claim of physiological
# accuracy, just enough signal for this script's own orchestration to be self-testable without
# Docker. (hr_start, hr_end_at_severity_1, map_start, map_end_at_severity_1, co_start,
# co_end_at_severity_1, sv_start, sv_end_at_severity_1) -- all values at severity=1.0, linearly
# scaled toward severity=0 (== start value, i.e. no change).
_MOCK_REFERENCE = {
    "stable": (71, 72, 95, 94, 5200, 5300, 70, 70),
    "deconditioning": (71, 78, 95, 93, 5200, 5000, 70, 68),
    "fluid_overload": (72, 73, 78, 77, 4900, 5600, 67, 67),
    "cardiac_stress": (71, 170, 95, 60, 5900, 10200, 65, 82),
    "acute_deterioration": (72, 140, 78, 48, 4500, 9200, 63, 67),
}


def sample_patients(patients_df: pd.DataFrame, n_per_scenario: int, seed: int) -> pd.DataFrame:
    """Same stratified-sampling convention as src/pulse_runner/batch_runner.py's sample_patients()
    -- reused rather than reimplemented, but kept local here to avoid importing a module whose
    top-level default paths assume /workspace (Docker-only)."""
    return (
        patients_df.groupby("scenario_type", group_keys=False)
        .sample(n=n_per_scenario, random_state=seed)
        .reset_index(drop=True)
    )


def _mock_pulse_response(scenario_type: str, severity: float) -> pd.DataFrame:
    hr0, hr1, map0, map1, co0, co1, sv0, sv1 = _MOCK_REFERENCE[scenario_type]
    s = max(0.0, min(1.0, float(severity)))
    interp = lambda start, end_at_1: start + (end_at_1 - start) * s  # noqa: E731
    return pd.DataFrame(
        {
            "Time(s)": [0, 600],
            "HeartRate(1/min)": [hr0, interp(hr0, hr1)],
            "MeanArterialPressure(mmHg)": [map0, interp(map0, map1)],
            "CardiacOutput(mL/min)": [co0, interp(co0, co1)],
            "HeartStrokeVolume(mL)": [sv0, interp(sv0, sv1)],
            "OxygenSaturation": [0.0, 0.0],  # matches the real pipeline's known-unreliable column
        }
    )


def _wearable_rows_for(patient_id: str, wearable_df: pd.DataFrame) -> list[dict]:
    rows = (
        wearable_df[wearable_df["patient_id"] == patient_id]
        .sort_values("day")
        .head(WEARABLE_WINDOW_DAYS)
        .to_dict("records")
    )
    if len(rows) < WEARABLE_WINDOW_DAYS:
        raise ValueError(
            f"{patient_id}: only {len(rows)} wearable rows in wearable_trends.csv, "
            f"need {WEARABLE_WINDOW_DAYS}"
        )
    return rows


def _run_one_patient(patient: dict, wearable_rows: list[dict], mock: bool, work_dir_str: str) -> dict:
    """Fully self-contained so it can be dispatched to a ProcessPoolExecutor worker: builds its own
    isolated FastAPI TestClient + temp SQLite DB (mirroring tests/test_api.py's `client` fixture)
    so parallel patients never share state, then drives the real API exactly as a client would.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.api.database import Base, get_db
    from src.api.main import app

    patient_id = patient["patient_id"]
    true_scenario_type = patient["scenario_type"]
    true_severity = float(patient["severity"])

    work_dir = pathlib.Path(work_dir_str) / patient_id
    work_dir.mkdir(parents=True, exist_ok=True)
    db_path = work_dir / "validation.db"
    scenarios_dir = work_dir / "scenarios"

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    base = {
        "patient_id": patient_id,
        "true_scenario_type": true_scenario_type,
        "true_severity": true_severity,
    }
    started = time.monotonic()

    try:
        patch_targets = [
            patch("src.api.routes.SessionLocal", SessionLocal),
            patch("src.api.services.SCENARIOS_DIR", scenarios_dir),
            # main.py's lifespan startup calls database.init_db(), which runs
            # Base.metadata.create_all() against the *shared default* data/db/m2k_hf_pulse.db
            # file, not this worker's isolated engine -- harmless run one-at-a-time (pytest), but
            # a real race under ProcessPoolExecutor parallelism (concurrent CREATE TABLE on the
            # same physical sqlite file). This worker's own create_all() below already builds the
            # schema it actually needs, so the app's startup hook is just redundant here.
            patch("src.api.database.init_db", lambda: None),
        ]
        if mock:
            fake_df = _mock_pulse_response(true_scenario_type, true_severity)
            patch_targets.append(patch("src.api.services.run_pulse", return_value=fake_df))
            patch_targets.append(patch("src.analytics.projection.run_pulse", return_value=fake_df))

        for p in patch_targets:
            p.start()
        try:
            from fastapi.testclient import TestClient

            with TestClient(app) as client:
                r = client.post(
                    "/patients",
                    json={
                        "age": int(round(patient["age"])),
                        "sex": patient["sex"],
                        "height_cm": patient["height_cm"],
                        "weight_kg": patient["weight_kg"],
                    },
                )
                r.raise_for_status()
                api_patient_id = r.json()["id"]

                client.post(
                    f"/patients/{api_patient_id}/clinical-report",
                    json={
                        "ejection_fraction_pct": patient["ejection_fraction_pct"],
                        "nt_probnp_pg_ml": patient["nt_probnp_pg_ml"],
                    },
                ).raise_for_status()

                start_date = datetime.date(2026, 1, 1)
                for i, row in enumerate(wearable_rows):
                    resp = client.post(
                        f"/patients/{api_patient_id}/wearable-sync",
                        json={
                            "recorded_date": str(start_date + datetime.timedelta(days=i)),
                            "resting_hr_bpm": row["resting_hr_bpm"],
                            "spo2_pct": row["spo2_pct"],
                            "weight_kg": row["weight_kg"],
                            "steps_per_day": row["steps_per_day"],
                            "sleep_hours": row["sleep_hours"],
                            "hrv_rmssd_ms": row["hrv_rmssd_ms"],
                        },
                    )
                    resp.raise_for_status()

                status = client.get(f"/patients/{api_patient_id}/status").json()
        finally:
            for p in patch_targets:
                p.stop()
    except Exception as e:  # never let one patient's HTTP/setup error abort the whole batch
        return {
            **base,
            "predicted_scenario_type": None,
            "predicted_severity": None,
            "scenario_match": None,
            "severity_abs_error": None,
            "risk_score": None,
            "risk_bucket": None,
            "nyha_class": None,
            "deterioration_direction": None,
            "simulation_status": "harness_error",
            "error_message": f"{type(e).__name__}: {e}",
            "wall_clock_s": round(time.monotonic() - started, 1),
        }
    finally:
        app.dependency_overrides.clear()

    assessment = status.get("latest_assessment") or {}
    predicted_scenario_type = assessment.get("scenario_type")
    predicted_severity = assessment.get("severity")

    return {
        **base,
        "predicted_scenario_type": predicted_scenario_type,
        "predicted_severity": predicted_severity,
        "scenario_match": (
            predicted_scenario_type == true_scenario_type if predicted_scenario_type else None
        ),
        "severity_abs_error": (
            abs(predicted_severity - true_severity) if predicted_severity is not None else None
        ),
        "risk_score": assessment.get("risk_score"),
        "risk_bucket": assessment.get("risk_bucket"),
        "nyha_class": assessment.get("nyha_class"),
        "deterioration_direction": assessment.get("deterioration_direction"),
        "simulation_status": status["simulation_status"],
        "error_message": status.get("error_message"),
        "wall_clock_s": round(time.monotonic() - started, 1),
    }


def run_validation(
    patients_df: pd.DataFrame,
    wearable_df: pd.DataFrame,
    run_dir: pathlib.Path,
    workers: int,
    mock: bool,
) -> pd.DataFrame:
    checkpoint_path = run_dir / "results.csv"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.unlink(missing_ok=True)
    work_dir = run_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    records = patients_df.to_dict("records")
    results = []

    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _run_one_patient, patient, _wearable_rows_for(patient["patient_id"], wearable_df),
                mock, str(work_dir),
            ): patient["patient_id"]
            for patient in records
        }
        done = 0
        for future in concurrent.futures.as_completed(futures):
            patient_id = futures[future]
            result = future.result()
            results.append(result)
            done += 1
            print(
                f"[{done}/{len(records)}] {patient_id} "
                f"({result['true_scenario_type']}): {result['simulation_status']}",
                flush=True,
            )
            pd.DataFrame([result]).to_csv(
                checkpoint_path, mode="a", header=not checkpoint_path.exists(), index=False
            )

    return pd.DataFrame(results)


def write_summary(results_df: pd.DataFrame, run_dir: pathlib.Path, mock: bool) -> None:
    n = len(results_df)
    completed = results_df[results_df["simulation_status"] == "complete"]
    failed = results_df[results_df["simulation_status"] != "complete"]

    lines = [
        "# Phase 8 batch validation summary",
        "",
        f"Mode: {'--mock (Docker-free self-test, synthetic Pulse responses)' if mock else 'real Pulse (Docker)'}",
        f"Patients: {n}",
        f"Completed: {len(completed)}/{n} ({100 * len(completed) / n:.0f}%)" if n else "Completed: 0/0",
        "",
        "## Failures by scenario type",
        "",
    ]
    if len(failed):
        lines.append(failed["true_scenario_type"].value_counts().to_string())
        lines.append("")
        lines.append(
            "Expected pattern (docs/methodology.md §5, §8): failures should concentrate in "
            "`cardiac_stress`/`acute_deterioration` at higher severities, since those are the only "
            "two scenarios with an Exercise action that can destabilize Pulse. A different pattern "
            "here is worth investigating before trusting the rest of this report."
        )
    else:
        lines.append("None.")
    lines.append("")

    if len(completed):
        agreement = completed["scenario_match"].mean()
        mae = completed["severity_abs_error"].mean()
        lines += [
            "## Scenario classification agreement (ML Model 1, live in the pipeline)",
            "",
            f"Agreement rate: {agreement:.1%} ({int(completed['scenario_match'].sum())}/{len(completed)})",
            f"Severity MAE: {mae:.3f} (offline test-set MAE was 0.048 per methodology.md §5 -- "
            "expect this to be somewhat higher since these severities also pass through a full "
            "Pulse re-simulation and risk-scoring step, not just the classifier in isolation)",
            "",
            "## Risk bucket distribution by true scenario type",
            "",
            pd.crosstab(completed["true_scenario_type"], completed["risk_bucket"]).to_string(),
            "",
            "Expected pattern (methodology.md §6.1): `stable`/`deconditioning` should be "
            "~100% LOW; `fluid_overload` should be ~100% LOW regardless of severity (documented "
            "blind spot, not a bug); `cardiac_stress`/`acute_deterioration` should skew "
            "MODERATE/HIGH.",
            "",
        ]

    lines += [
        "## Timing",
        "",
        f"Total wall clock across all patients: {results_df['wall_clock_s'].sum():.0f}s",
        f"Mean per patient: {results_df['wall_clock_s'].mean():.1f}s",
    ]

    (run_dir / "summary.md").write_text("\n".join(str(l) for l in lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-per-scenario", type=int, default=DEFAULT_N_PER_SCENARIO)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--mock", action="store_true", help="Docker-free self-test mode")
    parser.add_argument("--out-dir", type=str, default=None)
    args = parser.parse_args()

    patients_df = pd.read_csv(PATIENTS_CSV)
    wearable_df = pd.read_csv(WEARABLE_CSV)
    sample = sample_patients(patients_df, args.n_per_scenario, args.seed)

    if args.out_dir:
        run_dir = pathlib.Path(args.out_dir)
    else:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = VALIDATION_RUNS_DIR / timestamp

    print(f"Running {len(sample)} patients ({args.n_per_scenario} per scenario) -> {run_dir}")
    if not args.mock:
        print("Real Pulse mode -- must be running inside the kitware/pulse Docker container.")

    results_df = run_validation(sample, wearable_df, run_dir, args.workers, args.mock)
    write_summary(results_df, run_dir, args.mock)

    n_complete = (results_df["simulation_status"] == "complete").sum()
    print(f"\n{n_complete}/{len(results_df)} patients completed successfully")
    print(f"Wrote {run_dir / 'results.csv'}")
    print(f"Wrote {run_dir / 'summary.md'}")


if __name__ == "__main__":
    main()
