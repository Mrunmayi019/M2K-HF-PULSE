"""Identical orchestration to run_batch.py, but against the held-out confirmation seeds (45, 46,
47) instead of cohort.yaml's meta.seeds (42, 43, 44) -- added so the held-out confirmation run
(results/scenario_tests/alert_fix_plan.md / posthoc_plan.md) doesn't require editing the frozen
cohort.yaml. Calls the exact same, unmodified run_patient_seed.py; no harness/cohort/scorer
changes. New file, not an edit to run_batch.py.

Usage (inside the backend image):
    PYTHONPATH=/workspace python3 -m src.evaluation.scenario_tests.run_batch_heldout
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import time

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
COHORT_PATH = REPO_ROOT / "config" / "scenario_tests" / "cohort.yaml"
LOG_DIR = REPO_ROOT / "results" / "scenario_tests" / "logs"
MAX_PARALLEL = 6
HELDOUT_SEEDS = (45, 46, 47)


def main():
    cohort = yaml.safe_load(COHORT_PATH.read_text())
    patient_ids = list(cohort["patients"].keys())
    jobs = [(pid, seed) for pid in patient_ids for seed in HELDOUT_SEEDS]
    print(f"Held-out batch: {len(patient_ids)} patients x {len(HELDOUT_SEEDS)} seeds = "
          f"{len(jobs)} jobs, max {MAX_PARALLEL} concurrent", flush=True)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    pending = list(jobs)
    running = {}
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
    print(f"\nHeld-out batch complete: {n_ok}/{len(results)} jobs exited cleanly", flush=True)
    for patient_id, seed, ret, elapsed in results:
        if ret != 0:
            print(f"  FAILED (process exit {ret}): {patient_id} seed={seed} -- see "
                  f"{LOG_DIR / f'{patient_id}_seed{seed}.log'}", flush=True)
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
