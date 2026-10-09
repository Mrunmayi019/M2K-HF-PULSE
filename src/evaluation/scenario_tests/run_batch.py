"""Orchestrates the full scenario-test batch: 10 patients x 3 seeds = 30 patient-seed runs, up to
6 concurrent, ONE PROCESS PER PATIENT-SEED (hard rule: no threads, no forking inside a process).

Each patient-seed runs as a genuinely separate `python3 -m ...` subprocess (subprocess.Popen,
never multiprocessing's fork start method, never a thread pool) -- the same process-isolation
principle docs/continuous_state_sync_status.md Sec 2.7 already established is required around
Pulse + loaded sklearn models in this project.

Usage (inside the backend image):
    PYTHONPATH=/workspace python3 -m src.evaluation.scenario_tests.run_batch
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import time

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
COHORT_PATH = REPO_ROOT / "config" / "scenario_tests" / "cohort.yaml"
LOG_DIR = REPO_ROOT / "results" / "scenario_tests" / "logs"
# See run_patient_seed.py: SCENARIO_TEST_OUTPUT_DIR redirects a flag-on rerun (inherited by every
# subprocess). Unset leaves everything where it was.
if os.environ.get("SCENARIO_TEST_OUTPUT_DIR"):
    LOG_DIR = pathlib.Path(os.environ["SCENARIO_TEST_OUTPUT_DIR"]) / "logs"
# Experiment 2: SCENARIO_TEST_COHORT=config/scenario_tests/cohort_exp2.yaml (inherited by every
# subprocess, so run_patient_seed.py reads the same file and seeds 48-53 come from its meta).
if os.environ.get("SCENARIO_TEST_COHORT"):
    COHORT_PATH = pathlib.Path(os.environ["SCENARIO_TEST_COHORT"])
MAX_PARALLEL = 6


def main():
    cohort = yaml.safe_load(COHORT_PATH.read_text())
    patient_ids = list(cohort["patients"].keys())
    seeds = cohort["meta"]["seeds"]
    jobs = [(pid, seed) for pid in patient_ids for seed in seeds]
    print(f"Batch: {len(patient_ids)} patients x {len(seeds)} seeds = {len(jobs)} jobs, "
          f"max {MAX_PARALLEL} concurrent", flush=True)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    pending = list(jobs)
    running = {}  # Popen -> (patient_id, seed, log_file_handle, start_time)
    results = []

    while pending or running:
        while pending and len(running) < MAX_PARALLEL:
            patient_id, seed = pending.pop(0)
            log_path = LOG_DIR / f"{patient_id}_seed{seed}.log"
            log_f = open(log_path, "w")
            proc = subprocess.Popen(
                [sys.executable, "-u", "-m", "src.evaluation.scenario_tests.run_patient_seed", patient_id, str(seed)],
                stdout=log_f, stderr=subprocess.STDOUT, cwd=str(REPO_ROOT),
            )
            running[proc] = (patient_id, seed, log_f, time.monotonic())
            print(f"Launched {patient_id} seed={seed} (pid={proc.pid}), "
                  f"{len(running)}/{MAX_PARALLEL} running, {len(pending)} queued", flush=True)

        time.sleep(2)
        for proc in list(running.keys()):
            ret = proc.poll()
            if ret is not None:
                patient_id, seed, log_f, start_time = running.pop(proc)
                log_f.close()
                elapsed = time.monotonic() - start_time
                status = "OK" if ret == 0 else f"EXIT {ret}"
                print(f"Finished {patient_id} seed={seed}: {status} in {elapsed:.0f}s "
                      f"({len(running)}/{MAX_PARALLEL} running, {len(pending)} queued)", flush=True)
                results.append((patient_id, seed, ret, elapsed))

    n_ok = sum(1 for _, _, ret, _ in results if ret == 0)
    print(f"\nBatch complete: {n_ok}/{len(results)} jobs exited cleanly", flush=True)
    for patient_id, seed, ret, elapsed in results:
        if ret != 0:
            print(f"  FAILED (process exit {ret}): {patient_id} seed={seed} -- see "
                  f"{LOG_DIR / f'{patient_id}_seed{seed}.log'}", flush=True)
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
