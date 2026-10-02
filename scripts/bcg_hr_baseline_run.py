"""Runs the two HR-baseline-experiment scenarios (scripts/bcg_hr_baseline_experiment.py) through
Pulse. Must run inside kitware/pulse:4.3.1."""
import pathlib

from src.patient_builder.scenario_file import STABILIZATION_S
from src.pulse_runner.runner import PulseExecutionError, run_pulse

DURATION_MIN = 10.0
EXPECTED_DURATION_S = STABILIZATION_S + DURATION_MIN * 60
LABELS = ["subject14_hr_baseline", "subject102_hr_baseline"]


def main():
    for label in LABELS:
        scenario_path = f"/workspace/data/bcg_validation/{label}/scenario.json"
        log_path = pathlib.Path(scenario_path).with_suffix(".log")
        print(f"\n=== {label} ===")
        try:
            df = run_pulse(scenario_path, expected_duration_s=EXPECTED_DURATION_S, timeout_sec=420)
        except PulseExecutionError as e:
            print(f"FAILED: {e}")
            continue

        if log_path.exists():
            warn_lines = [
                line for line in log_path.read_text(errors="replace").splitlines()
                if any(tag in line.lower() for tag in ("warn", "error", "fatal", "irreversible"))
            ]
            print(f"warnings/errors ({len(warn_lines)}):")
            for line in warn_lines:
                print(f"  {line}")

        first, last = df.iloc[0], df.iloc[-1]
        print(f"t=0:   HR={first['HeartRate(1/min)']:.2f}  SV={first['HeartStrokeVolume(mL)']:.2f}  "
              f"CO={first['CardiacOutput(mL/min)']:.2f}  MAP={first['MeanArterialPressure(mmHg)']:.2f}")
        print(f"t=660: HR={last['HeartRate(1/min)']:.2f}  SV={last['HeartStrokeVolume(mL)']:.2f}  "
              f"CO={last['CardiacOutput(mL/min)']:.2f}  MAP={last['MeanArterialPressure(mmHg)']:.2f}")

        out_csv = pathlib.Path(f"/workspace/data/bcg_validation/{label}/full_results.csv")
        df.to_csv(out_csv, index=False)
        print(f"Wrote {out_csv}")


if __name__ == "__main__":
    main()
