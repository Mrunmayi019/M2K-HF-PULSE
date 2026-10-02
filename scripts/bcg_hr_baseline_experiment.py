"""HR-baseline personalization experiment: re-runs subjects 14 and 102 with their real xlsx
resting HR set as Pulse's HeartRateBaseline (new optional param on build_patient_file(), see
src/patient_builder/patient_file.py), instead of leaving it unset (Pulse's generic-default
behavior, used for the original runs in docs/bcg_validation_note.md).

Everything else (EF, BCG modifiers, scenario type, severity) is held identical to the original
runs so the comparison isolates the HR-baseline change specifically. Writes to separate
`_hr_baseline` output directories -- the original runs' artifacts are untouched, so both states
remain on disk for comparison.

Must run inside kitware/pulse:4.3.1.
"""
from __future__ import annotations

import json
import pathlib

from src.patient_builder.patient_file import bcg_to_cardiovascular_modifiers, build_patient_file
from src.patient_builder.scenario_file import build_scenario_file

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

SCENARIO_TYPE = "acute_deterioration"
SEVERITY = 0.35

CASES = {
    "subject14_hr_baseline": {
        "patient": {"patient_id": "bcg_subject14_hrb", "sex": "Male", "age": 53, "height_cm": 160, "weight_kg": 70},
        "ejection_fraction_pct": 34.7,
        "hr_baseline_bpm": 77,  # Subject_Info.xlsx, subject 014 -- within Pulse's 50-110 range, no clamping
        "rj_interval_ms": 233.0, "ij_amplitude": 1.172, "jk_amplitude": 1.496,
        "rj_reference_ms": 175.0, "amplitude_reference": (1.061 + 1.162) / 2.0,  # subject 102 anchor, as original run used
    },
    "subject102_hr_baseline": {
        "patient": {"patient_id": "bcg_subject102_hrb", "sex": "Male", "age": 45, "height_cm": 182, "weight_kg": 94},
        "ejection_fraction_pct": 35.1,
        "hr_baseline_bpm": 115,  # Subject_Info.xlsx, subject 102 -- ABOVE Pulse's 110 max, will be clamped to 110
        "rj_interval_ms": 175.0, "ij_amplitude": 1.061, "jk_amplitude": 1.162,
        "rj_reference_ms": 233.0, "amplitude_reference": (1.172 + 1.496) / 2.0,  # subject 14 anchor, as original run used
    },
}


def main():
    for label, cfg in CASES.items():
        out_dir = REPO_ROOT / "data" / "bcg_validation" / label
        out_dir.mkdir(parents=True, exist_ok=True)

        patient_json = build_patient_file(cfg["patient"], hr_baseline_bpm=cfg["hr_baseline_bpm"])
        patient_path = out_dir / "patient.json"
        patient_path.write_text(json.dumps(patient_json, indent=2))

        bcg_modifiers = bcg_to_cardiovascular_modifiers(
            cfg["rj_interval_ms"], cfg["ij_amplitude"], cfg["jk_amplitude"],
            rj_reference_ms=cfg["rj_reference_ms"], amplitude_reference=cfg["amplitude_reference"],
        )

        scenario_json = build_scenario_file(
            patient_json_path=f"/workspace/data/bcg_validation/{label}/patient.json",
            scenario_type=SCENARIO_TYPE,
            severity=SEVERITY,
            ejection_fraction_pct=cfg["ejection_fraction_pct"],
            duration_min=10.0,
            extra_modifiers=bcg_modifiers,
        )
        scenario_path = out_dir / "scenario.json"
        scenario_path.write_text(json.dumps(scenario_json, indent=2))

        actual_hr = patient_json["HeartRateBaseline"]["ScalarFrequency"]["Value"]
        print(f"=== {label} ===")
        print(f"requested hr_baseline_bpm={cfg['hr_baseline_bpm']} -> "
              f"patient.json HeartRateBaseline={actual_hr} "
              f"{'(clamped, Pulse max 110)' if actual_hr != cfg['hr_baseline_bpm'] else '(unclamped, within range)'}")
        print(f"Wrote {patient_path}")
        print(f"Wrote {scenario_path}")
        print()


if __name__ == "__main__":
    main()
