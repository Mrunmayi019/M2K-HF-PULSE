"""Runs the already-built subject-102 BCG-validation scenario through Pulse. Must run INSIDE the
kitware/pulse:4.3.1 container. See scripts/bcg_subject102_validation.py for how patient.json /
scenario.json were built. Mirrors scripts/bcg_real_patient_run.py (subject 14)."""
import pathlib

import pandas as pd

from src.patient_builder.scenario_file import STABILIZATION_S
from src.pulse_runner.runner import PulseExecutionError, run_pulse

SCENARIO_PATH = "/workspace/data/bcg_validation/subject102/scenario.json"
DURATION_MIN = 10.0
EXPECTED_DURATION_S = STABILIZATION_S + DURATION_MIN * 60


def main():
    log_path = pathlib.Path(SCENARIO_PATH).with_suffix(".log")

    try:
        # 420s timeout: subject 14's equivalent run needed 106s wall-clock for a full 660s
        # simulation under this container -- same margin applied here given the heavier body
        # (94kg vs 70kg) could plausibly take somewhat longer.
        df = run_pulse(SCENARIO_PATH, expected_duration_s=EXPECTED_DURATION_S, timeout_sec=420)
        status = "SUCCESS"
        error = None
    except PulseExecutionError as e:
        status = "FAILED"
        error = str(e)
        df = None

    print(f"=== STATUS: {status} ===")
    if error:
        print(f"error: {error}")

    if log_path.exists():
        log_text = log_path.read_text(errors="replace")
        warn_lines = [
            line for line in log_text.splitlines()
            if any(tag in line.lower() for tag in ("warn", "error", "fatal", "irreversible"))
        ]
        print(f"\n=== Lines containing warn/error/fatal/irreversible ({len(warn_lines)}) ===")
        for line in warn_lines:
            print(line)
        final_lines = [l for l in log_text.splitlines() if "SimTime" in l or "It took" in l]
        print("\n=== Final timing lines ===")
        for line in final_lines:
            print(line)
    else:
        print(f"\n(no log file found at {log_path})")

    if df is not None:
        print(f"\n=== Results CSV: {len(df)} rows, columns: {list(df.columns)} ===")
        first, last = df.iloc[0], df.iloc[-1]
        time_col = next(c for c in df.columns if c.strip().lower().startswith("time"))
        print(f"first row ({time_col}={first[time_col]}):")
        print(first.to_string())
        print(f"\nlast row ({time_col}={last[time_col]}):")
        print(last.to_string())

        out_csv = pathlib.Path("/workspace/data/bcg_validation/subject102/full_results.csv")
        df.to_csv(out_csv, index=False)
        print(f"\nWrote full results to {out_csv}")


if __name__ == "__main__":
    main()
