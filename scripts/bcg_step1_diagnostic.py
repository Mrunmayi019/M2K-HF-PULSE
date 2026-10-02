"""Diagnostic for the SV/CO arithmetic check on subject 14's run (see docs/bcg_validation_note.md
step-1 follow-up). Builds two MINIMAL healthy (EF=70, no ChronicVentricularSystolicDysfunction
condition, severity=0, "stable" scenario -> no Exercise action either) patients that differ ONLY
in height, to isolate whether Pulse's pure anthropometric SV baseline is sensitive to height in a
way that specifically disadvantages a 160cm patient -- independent of any EF condition or BCG
modifier, both of which are deliberately excluded here.

    A) height=160cm, weight=70kg (real subject 14 anthropometrics)
    B) height=175cm, weight=70kg (a "typical" male height per Pulse's own warning threshold,
       same weight -- isolates height's effect, not a simultaneous BMI change from weight)

Must run inside kitware/pulse:4.3.1.
"""
import json
import pathlib

from src.patient_builder.patient_file import build_patient_file
from src.patient_builder.scenario_file import STABILIZATION_S, build_scenario_file
from src.pulse_runner.runner import PulseExecutionError, run_pulse

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "bcg_validation" / "step1_diagnostic"

CASES = {
    "A_160cm": {"patient_id": "diag_160", "sex": "Male", "age": 53, "height_cm": 160, "weight_kg": 70},
    "B_175cm": {"patient_id": "diag_175", "sex": "Male", "age": 53, "height_cm": 175, "weight_kg": 70},
}
HEALTHY_EF_PCT = 70.0  # > 40 threshold -> apply_systolic_dysfunction_condition=False, no confound
DURATION_MIN = 1.0


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    expected_duration_s = STABILIZATION_S + DURATION_MIN * 60

    for label, patient in CASES.items():
        case_dir = OUT_DIR / label
        case_dir.mkdir(exist_ok=True)
        patient_path = case_dir / "patient.json"
        patient_path.write_text(json.dumps(build_patient_file(patient), indent=2))

        container_patient_path = f"/workspace/data/bcg_validation/step1_diagnostic/{label}/patient.json"
        scenario = build_scenario_file(
            patient_json_path=container_patient_path,
            scenario_type="stable",
            severity=0.0,
            ejection_fraction_pct=HEALTHY_EF_PCT,
            duration_min=DURATION_MIN,
        )
        scenario_path = case_dir / "scenario.json"
        scenario_path.write_text(json.dumps(scenario, indent=2))

        container_scenario_path = f"/workspace/data/bcg_validation/step1_diagnostic/{label}/scenario.json"
        print(f"\n=== {label} (height={patient['height_cm']}cm, weight={patient['weight_kg']}kg) ===")
        try:
            df = run_pulse(container_scenario_path, expected_duration_s=expected_duration_s, timeout_sec=300)
        except PulseExecutionError as e:
            print(f"FAILED: {e}")
            continue

        first = df.iloc[0]
        hr = first["HeartRate(1/min)"]
        co = first["CardiacOutput(mL/min)"]
        sv = first["HeartStrokeVolume(mL)"]
        print(f"baseline (post-stabilization, no EF condition, no scenario action): "
              f"HR={hr:.2f} bpm, CO={co:.2f} mL/min, SV={sv:.2f} mL")


if __name__ == "__main__":
    main()
