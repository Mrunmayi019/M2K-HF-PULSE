"""BCG/EF ablation, step 2 of 3: run every built scenario through Pulse.

Must run INSIDE kitware/pulse:4.3.1 (see HANDOFF.md §2.5 for the docker invocation). Runs each
config sequentially (never concurrently -- HANDOFF.md documents CPU-contention timeouts) through the
existing run_pulse(), which already fails a run on nonzero exit, fatal/irreversible log markers, or
a truncated CSV. Nothing is retried or hidden: every run's status, error and engine warning lines
are written to data/bcg_ablation/run_status.json.

Usage (inside the container):  python3 -m scripts.bcg_ablation_run [subject ...] [--only CONFIG ...]
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

from src.pulse_runner.runner import PulseExecutionError, run_pulse

OUT_ROOT = pathlib.Path("/workspace/data/bcg_ablation")
TIMEOUT_SEC = 420  # >= 300 as required; the original 660s runs needed ~106-109s wall-clock
WARN_TAGS = ("warn", "error", "fatal", "irreversible")


def run_one(scenario_path: pathlib.Path, expected_duration_s: float) -> dict:
    log_path = scenario_path.with_suffix(".log")
    start = time.monotonic()
    try:
        df = run_pulse(str(scenario_path), expected_duration_s=expected_duration_s, timeout_sec=TIMEOUT_SEC)
        status, error = "SUCCESS", None
        df.to_csv(scenario_path.parent / "full_results.csv", index=False)
    except PulseExecutionError as e:
        status, error = "FAILED", str(e)
    wall_s = round(time.monotonic() - start, 1)

    warnings = []
    if log_path.exists():
        warnings = [
            line.strip() for line in log_path.read_text(errors="replace").splitlines()
            if any(tag in line.lower() for tag in WARN_TAGS)
        ]
    return {"status": status, "error": error, "wall_clock_s": wall_s, "warning_lines": warnings}


def main() -> None:
    args = sys.argv[1:]
    only = args[args.index("--only") + 1:] if "--only" in args else None
    subjects_arg = args[: args.index("--only")] if "--only" in args else args

    manifest = json.loads((OUT_ROOT / "manifest.json").read_text())
    status_path = OUT_ROOT / "run_status.json"
    all_status = json.loads(status_path.read_text()) if status_path.exists() else {}

    for subject_id in subjects_arg or list(manifest["subjects"]):
        for label in manifest["configs"]:
            if only and label not in only:
                continue
            scenario_path = OUT_ROOT / f"subject{subject_id}" / label / "scenario.json"
            print(f"[subject {subject_id} / {label}] running ...", flush=True)
            result = run_one(scenario_path, manifest["duration_s"])
            all_status.setdefault(str(subject_id), {})[label] = result
            status_path.write_text(json.dumps(all_status, indent=2))  # write after every run
            print(f"[subject {subject_id} / {label}] {result['status']} in {result['wall_clock_s']}s, "
                  f"{len(result['warning_lines'])} warning line(s)", flush=True)
            if result["error"]:
                print(f"    error: {result['error'][:1500]}", flush=True)
            for w in result["warning_lines"]:
                print(f"    {w}", flush=True)


if __name__ == "__main__":
    main()
