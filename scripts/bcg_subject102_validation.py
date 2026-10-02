"""Single real-patient validation: subject 102 of the Zhan et al. 2025 Multi-Pathology BCG Dataset
(figshare 10.6084/m9.figshare.28416896), run through the same pipeline as subject 14
(scripts/bcg_real_patient_validation.py) -- see docs/bcg_validation_note.md for the combined
writeup and subject-14 run this compares against.

Clinical baseline, Subject_Info.xlsx "HF" sheet, subject 102:
    Sex=Male, Age=45, Height=182cm, Weight=94kg, EF=35.1%, HR=115 (xlsx).
    NOTE: subject 102's own XJ-clip R-R-derived HR (52.8 bpm) showed an unexplained 2.15x
    discrepancy against this xlsx HR, confirmed real (not a sample-rate bug) but never explained
    by the source paper -- see docs/bcg_validation_note.md's subject-selection history. Per
    explicit instruction, this run uses the xlsx resting HR (115) as ground truth for comparison,
    NOT the session-derived 52.8 bpm, since the session HR itself is the unreliable one here.

BCG features, from subject 102's own XJ-view signal.csv + peak annotations (14 clean R-J-paired
beats out of 17 R-peaks -- 3 excluded as missing-J pairing artifacts, see the original extraction
in-conversation record; corroborated as a BCG-side detection issue, not a rhythm issue, since the
underlying ECG R-R series is itself clean/regular, ruling out arrhythmia):
    R-J interval: mean 175.0 ms (n=14)
    IJ amplitude: mean 1.061 (n=14, dataset's own relative signal units)
    JK amplitude: mean 1.162 (n=14, same units)

Reference-point anchor for bcg_to_cardiovascular_modifiers(): subject 14's own measured values
(R-J=233.0ms, composite IJ/JK amplitude=1.334), the reverse of subject 14's own run (which used
subject 102's values as its reference). Same n=2 framing either way -- whichever subject is NOT
the active patient anchors the scale.
"""
from __future__ import annotations

import json
import pathlib

from src.patient_builder.patient_file import bcg_to_cardiovascular_modifiers, build_patient_file
from src.patient_builder.scenario_file import MAX_EXERCISE_INTENSITY, build_scenario_file

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "bcg_validation" / "subject102"
PATIENT_PATH_IN_CONTAINER = "/workspace/data/bcg_validation/subject102/patient.json"

PATIENT = {
    "patient_id": "bcg_subject102",
    "sex": "Male",
    "age": 45,
    "height_cm": 182,
    "weight_kg": 94,
}
EJECTION_FRACTION_PCT = 35.1

# Same manual-assignment reasoning as subject 14 (methodology.md's EF-profile taxonomy: EF<=40%
# HFrEF profile -> acute_deterioration), and the same moderate severity for a like-for-like
# comparison -- no wearable-trend evidence exists for either patient to justify a different value.
SCENARIO_TYPE = "acute_deterioration"
SEVERITY = 0.35

RJ_INTERVAL_MS = 175.0
IJ_AMPLITUDE = 1.061
JK_AMPLITUDE = 1.162

# Subject 14's own measured values, used as this run's reference point (see module docstring).
SUBJECT14_RJ_MS = 233.0
SUBJECT14_IJ_AMPLITUDE = 1.172
SUBJECT14_JK_AMPLITUDE = 1.496
SUBJECT14_AMPLITUDE_REFERENCE = (SUBJECT14_IJ_AMPLITUDE + SUBJECT14_JK_AMPLITUDE) / 2.0


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    patient_json = build_patient_file(PATIENT)
    patient_path = OUT_DIR / "patient.json"
    patient_path.write_text(json.dumps(patient_json, indent=2))

    bcg_modifiers = bcg_to_cardiovascular_modifiers(
        RJ_INTERVAL_MS,
        IJ_AMPLITUDE,
        JK_AMPLITUDE,
        rj_reference_ms=SUBJECT14_RJ_MS,
        amplitude_reference=SUBJECT14_AMPLITUDE_REFERENCE,
    )

    scenario_json = build_scenario_file(
        patient_json_path=PATIENT_PATH_IN_CONTAINER,
        scenario_type=SCENARIO_TYPE,
        severity=SEVERITY,
        ejection_fraction_pct=EJECTION_FRACTION_PCT,
        duration_min=10.0,
        extra_modifiers=bcg_modifiers,
    )
    scenario_path = OUT_DIR / "scenario.json"
    scenario_path.write_text(json.dumps(scenario_json, indent=2))

    exercise_intensity = max(0.1, min(SEVERITY * 0.6, MAX_EXERCISE_INTENSITY))
    cv_action = next(
        a["PatientAction"]["CardiovascularMechanicsModification"]["Modifiers"]
        for a in scenario_json["AnyAction"]
        if "PatientAction" in a and "CardiovascularMechanicsModification" in a["PatientAction"]
    )

    print("=== Patient file ===")
    print(json.dumps(patient_json, indent=2))
    print()
    print("=== BCG modifiers (bcg_to_cardiovascular_modifiers output, subject-14-anchored) ===")
    print(json.dumps(bcg_modifiers, indent=2))
    print()
    print("=== Crash-boundary check ===")
    print(f"scenario_type = {SCENARIO_TYPE}, severity = {SEVERITY}")
    print(f"Exercise action intensity = severity*0.6 = {exercise_intensity:.3f}  "
          f"(same as subject 14's run -- comfortably under 0.45 general caution line and "
          f"acute_deterioration's own 0.6-0.85 observed crash range)")
    print("Final CardiovascularMechanicsModification.Modifiers:")
    for k, v in cv_action.items():
        print(f"  {k}: {v}")
    print()
    print(f"Wrote: {patient_path}")
    print(f"Wrote: {scenario_path}")


if __name__ == "__main__":
    main()
