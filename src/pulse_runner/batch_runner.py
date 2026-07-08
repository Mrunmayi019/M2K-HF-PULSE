"""Phase 4: batch-runs many synthetic patients through Pulse and assembles a labeled feature
dataset for Phase 5's risk scorer.

Composition: a stratified sample from the existing data/synthetic/patients.csv population (not a
fixed severity grid) -- that population already carries real, clinically-correlated per-patient
severity/EF/BNP as ground truth and already spans the full severity range within each scenario
type (verified: min~0/max~1 in every type except `stable`, which is capped low by design), so a
random per-scenario sample naturally covers it.

Must run inside the kitware/pulse Docker container (run_pulse() requires PulseScenarioDriver,
only present there) -- same requirement as scripts/validate_phase2.py.
"""
from __future__ import annotations

import concurrent.futures
import json
import pathlib

import pandas as pd

from src.patient_builder.patient_file import build_patient_file
from src.patient_builder.scenario_file import STABILIZATION_S, build_scenario_file
from src.pulse_runner.runner import PulseExecutionError, run_pulse
from src.simulation_features import analyze_simulation

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = pathlib.Path("/workspace/scenarios/batch")
PATIENTS_CSV = REPO_ROOT / "data" / "synthetic" / "patients.csv"
SIMULATION_RUNS_DIR = REPO_ROOT / "data" / "simulation_runs"

DEFAULT_N_PER_SCENARIO = 30
DEFAULT_DURATION_MIN = 10.0
# Conservative default: this is a laptop already paying arm64->amd64 Docker emulation overhead
# for each Pulse process (~2 min/run sequential, see docs/methodology.md §8). Raise this if the
# pilot run (see docs/methodology.md §7 / the plan's Verification section) shows CPU headroom.
DEFAULT_WORKERS = 4


def sample_patients(patients_df: pd.DataFrame, n_per_scenario: int = DEFAULT_N_PER_SCENARIO, seed: int = 42) -> pd.DataFrame:
    """Stratified sample: n_per_scenario patients per scenario_type, using each patient's own
    real severity/EF/BNP as the ground truth for the simulation run."""
    return (
        patients_df.groupby("scenario_type", group_keys=False)
        .sample(n=n_per_scenario, random_state=seed)
        .reset_index(drop=True)
    )


def _run_one(patient: dict, output_dir: pathlib.Path, duration_min: float) -> dict:
    """Builds patient/scenario JSON for one patient, runs Pulse, and extracts features.

    Returns a dict with status="ok" + extracted features on success, or status="failed" + error
    on a PulseExecutionError -- callers must not let one failure abort the whole batch (a crashed
    patient at a given severity is a real, expected outcome to record, not a bug to hide).
    """
    patient_id = patient["patient_id"]
    scenario_type = patient["scenario_type"]
    severity = float(patient["severity"])
    ejection_fraction_pct = float(patient["ejection_fraction_pct"])

    output_dir.mkdir(parents=True, exist_ok=True)
    patient_path = output_dir / f"patient_{patient_id}.json"
    scenario_path = output_dir / f"scenario_{patient_id}.json"

    patient_path.write_text(json.dumps(build_patient_file(patient), indent=2))
    scenario = build_scenario_file(
        patient_json_path=str(patient_path),
        scenario_type=scenario_type,
        severity=severity,
        ejection_fraction_pct=ejection_fraction_pct,
        duration_min=duration_min,
    )
    scenario_path.write_text(json.dumps(scenario, indent=2))

    base = {
        "patient_id": patient_id,
        "scenario_type": scenario_type,
        "severity": severity,
        "ejection_fraction_pct": ejection_fraction_pct,
    }

    expected_duration_s = STABILIZATION_S + duration_min * 60
    try:
        df = run_pulse(str(scenario_path), expected_duration_s=expected_duration_s, timeout_sec=180)
    except PulseExecutionError as e:
        return {**base, "status": "failed", "error": str(e), "scenario_path": str(scenario_path)}

    return {**base, "status": "ok", **analyze_simulation(df)}


def run_batch(
    patients_df: pd.DataFrame,
    output_dir: pathlib.Path = DEFAULT_OUTPUT_DIR,
    duration_min: float = DEFAULT_DURATION_MIN,
    workers: int = DEFAULT_WORKERS,
    checkpoint_path: pathlib.Path | None = None,
) -> pd.DataFrame:
    """Runs _run_one across all rows of patients_df in parallel. Returns one DataFrame with both
    successful and failed runs (see the "status" column) -- callers split them as needed.

    If `checkpoint_path` is given, each result is appended to that CSV as soon as it completes
    (not just collected in memory) -- a run of 150 patients takes on the order of an hour even
    parallelized, and without this an interruption partway through would lose every result
    computed so far, not just the ones in flight.
    """
    records = patients_df.to_dict("records")
    results = []

    if checkpoint_path is not None:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_path.unlink(missing_ok=True)

    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_run_one, patient, output_dir, duration_min): patient["patient_id"]
            for patient in records
        }
        done = 0
        for future in concurrent.futures.as_completed(futures):
            patient_id = futures[future]
            result = future.result()
            results.append(result)
            done += 1
            print(f"[{done}/{len(records)}] {patient_id} ({result['scenario_type']}): {result['status']}", flush=True)

            if checkpoint_path is not None:
                pd.DataFrame([result]).to_csv(
                    checkpoint_path, mode="a", header=not checkpoint_path.exists(), index=False
                )

    return pd.DataFrame(results)


if __name__ == "__main__":
    patients = pd.read_csv(PATIENTS_CSV)
    sample = sample_patients(patients)

    SIMULATION_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    results_df = run_batch(sample, checkpoint_path=SIMULATION_RUNS_DIR / "checkpoint.csv")

    ok = results_df[results_df["status"] == "ok"].drop(
        columns=["status", "error", "scenario_path"], errors="ignore"
    )
    failed = results_df[results_df["status"] == "failed"]

    ok.to_csv(SIMULATION_RUNS_DIR / "features_dataset.csv", index=False)
    if len(failed):
        failed.to_csv(SIMULATION_RUNS_DIR / "failed_runs.csv", index=False)

    print(f"\n{len(ok)}/{len(sample)} runs succeeded, {len(failed)} failed")
    print(f"Wrote {SIMULATION_RUNS_DIR / 'features_dataset.csv'}")
    if len(failed):
        print(f"Wrote {SIMULATION_RUNS_DIR / 'failed_runs.csv'}")
