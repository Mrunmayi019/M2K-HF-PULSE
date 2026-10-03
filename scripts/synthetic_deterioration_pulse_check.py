"""Pulse directional-consistency check for the synthetic deterioration stress test
(scripts/synthetic_deterioration_stress_test.py). Takes a representative subset of days from each
subject's classifier severity trajectory (day 6, 11, 16, 20) and runs each through Pulse with that
day's severity, everything else held fixed (same EF, same BCG-derived compliance multipliers
already established for that subject in docs/bcg_validation_note.md).

Checks whether simulated CO/HR move in the SAME DIRECTION as the rising synthetic severity signal
driving them -- this is a check of internal consistency between the ML severity signal and the
Pulse simulation layer, NOT a real-world validation (see docs/synthetic_deterioration_stress_test.md
for the required scope statement).

Scoping decision: uses scenario_type="acute_deterioration" for every point (the correct FINAL
classification for both subjects), even for subject 14's day 6 (which the classifier actually
mislabeled "fluid_overload" at that early window -- see the stress-test note). This isolates
whether Pulse's hemodynamics track the severity signal itself, not whether switching scenario
type at a misclassified window produces a discontinuity -- a different question, out of scope here.

Must run inside kitware/pulse:4.3.1.
"""
from __future__ import annotations

import json
import pathlib

from src.patient_builder.patient_file import bcg_to_cardiovascular_modifiers, build_patient_file
from src.patient_builder.scenario_file import MAX_EXERCISE_INTENSITY, build_scenario_file
from src.pulse_runner.runner import PulseExecutionError, run_pulse
from src.patient_builder.scenario_file import STABILIZATION_S

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "synthetic_deterioration_stress_test" / "pulse"
DURATION_MIN = 10.0
EXPECTED_DURATION_S = STABILIZATION_S + DURATION_MIN * 60

# Representative days + this exact stress test's own classifier severity output at that day
# (from the fixed-seed run in synthetic_deterioration_stress_test.py -- copied here, not
# re-derived, so this script has no dependency on re-running that one first).
SUBJECTS = {
    "subject14": {
        "patient": {"patient_id": "bcg_subject14_trend_pulse", "sex": "Male", "age": 53, "height_cm": 160, "weight_kg": 70},
        "ejection_fraction_pct": 34.7,
        "bcg_modifiers_kwargs": dict(
            rj_interval_ms=233.0, ij_amplitude=1.172, jk_amplitude=1.496,
            rj_reference_ms=175.0, amplitude_reference=(1.061 + 1.162) / 2.0,
        ),
        "days": {6: 0.3695, 11: 0.5027, 16: 0.6346, 20: 0.8661},
    },
    "subject102": {
        "patient": {"patient_id": "bcg_subject102_trend_pulse", "sex": "Male", "age": 45, "height_cm": 182, "weight_kg": 94},
        "ejection_fraction_pct": 35.1,
        "bcg_modifiers_kwargs": dict(
            rj_interval_ms=175.0, ij_amplitude=1.061, jk_amplitude=1.162,
            rj_reference_ms=233.0, amplitude_reference=(1.172 + 1.496) / 2.0,
        ),
        "days": {6: 0.2547, 11: 0.5004, 16: 0.6756, 20: 0.8783},
    },
}

# This project's own documented acute_deterioration crash range (docs/methodology.md Sec 5/7:
# "crashes/timeouts above severity ~0.6-0.85"). Flagged per-point below, not silently run into.
KNOWN_CRASH_RANGE = (0.6, 0.85)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=== Crash-boundary check, all points, before any run ===")
    for label, cfg in SUBJECTS.items():
        for day, severity in cfg["days"].items():
            exercise_intensity = max(0.1, min(severity * 0.6, MAX_EXERCISE_INTENSITY))
            in_crash_range = KNOWN_CRASH_RANGE[0] <= severity <= KNOWN_CRASH_RANGE[1]
            flag = "  <-- inside documented crash range, may fail -- expected if so, not a new bug" if in_crash_range else ""
            print(f"{label} day {day}: severity={severity:.4f}, Exercise intensity={exercise_intensity:.3f}{flag}")

    print("\n=== Building patient/scenario files ===")
    build_plan = []
    for label, cfg in SUBJECTS.items():
        bcg_modifiers = bcg_to_cardiovascular_modifiers(**cfg["bcg_modifiers_kwargs"])
        patient_json = build_patient_file(cfg["patient"])
        for day, severity in cfg["days"].items():
            case_dir = OUT_DIR / f"{label}_day{day}"
            case_dir.mkdir(parents=True, exist_ok=True)
            patient_path = case_dir / "patient.json"
            patient_path.write_text(json.dumps(patient_json, indent=2))

            scenario_json = build_scenario_file(
                patient_json_path=f"/workspace/data/synthetic_deterioration_stress_test/pulse/{label}_day{day}/patient.json",
                scenario_type="acute_deterioration",
                severity=severity,
                ejection_fraction_pct=cfg["ejection_fraction_pct"],
                duration_min=DURATION_MIN,
                extra_modifiers=bcg_modifiers,
            )
            scenario_path = case_dir / "scenario.json"
            scenario_path.write_text(json.dumps(scenario_json, indent=2))
            build_plan.append((label, day, severity, scenario_path))
            print(f"Wrote {scenario_path} (severity={severity:.4f})")

    print("\n=== Running through Pulse ===")
    results = []
    for label, day, severity, scenario_path in build_plan:
        container_path = f"/workspace/data/synthetic_deterioration_stress_test/pulse/{label}_day{day}/scenario.json"
        print(f"\n--- {label} day {day} (severity={severity:.4f}) ---")
        try:
            df = run_pulse(container_path, expected_duration_s=EXPECTED_DURATION_S, timeout_sec=420)
        except PulseExecutionError as e:
            print(f"FAILED: {e}")
            results.append({"subject": label, "day": day, "severity": severity, "status": "failed"})
            continue

        last = df.iloc[-1]
        result = {
            "subject": label, "day": day, "severity": severity, "status": "success",
            "hr_end": last["HeartRate(1/min)"], "sv_end": last["HeartStrokeVolume(mL)"],
            "co_end": last["CardiacOutput(mL/min)"], "map_end": last["MeanArterialPressure(mmHg)"],
        }
        results.append(result)
        print(f"HR={result['hr_end']:.2f}  SV={result['sv_end']:.2f}  CO={result['co_end']:.2f}  MAP={result['map_end']:.2f}")

    print("\n\n=== Summary: severity vs. simulated endpoint hemodynamics ===")
    for label in SUBJECTS:
        print(f"\n{label}:")
        rows = [r for r in results if r["subject"] == label]
        for r in rows:
            if r["status"] == "success":
                print(f"  day {r['day']:2d}  severity={r['severity']:.4f}  ->  "
                      f"HR={r['hr_end']:.2f}  SV={r['sv_end']:.2f}  CO={r['co_end']:.2f}  MAP={r['map_end']:.2f}")
            else:
                print(f"  day {r['day']:2d}  severity={r['severity']:.4f}  ->  FAILED")

    results_path = OUT_DIR / "summary.json"
    results_path.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {results_path}")


if __name__ == "__main__":
    main()
