"""Single real-patient validation: subject 14 of the Zhan et al. 2025 Multi-Pathology BCG Dataset
(figshare 10.6084/m9.figshare.28416896), run through the existing Pulse pipeline in place of a
synthetic patient.

Why this patient, and why manual scenario/severity assignment: see the validation note
(docs/bcg_validation_note.md, written after this run) for the full subject-selection history
(subject 102 was set aside over a 2.15x unexplained HR discrepancy against its own clinical
sheet -- confirmed real, not a sample-rate bug, see that note's investigation log) and for why no
wearable-trend window exists for a single-session dataset (so ML Model 1's scenario classifier,
which needs a 21-day trend window, cannot run here -- scenario_type/severity are assigned manually
from the real EF/diagnosis instead, and classifier validation is explicitly out of scope for this
single-patient check).

Clinical baseline, Subject_Info.xlsx "HF" sheet, subject 014:
    Sex=Male, Age=53, Height=160cm, Weight=70kg, EF=34.7%, HR=77 (xlsx; cross-checked against this
    subject's own XJ-clip R-R at 81.0 bpm, 1.05x -- clean, unlike subject 102).

BCG features, from this subject's own XJ-view signal.csv + peak annotations (20 clean sinus beats,
0 PVCs in this specific clip -- corroborated by the dataset's own file tag: subject 14's ALL-sheet
Data_file field is "EJ(PVCs), XJ, ZJ(PVCs)", i.e. only EJ/ZJ carry the PVC tag, not XJ):
    R-J interval: mean 233.0 ms (n=20)
    IJ amplitude: mean 1.172 (n=20, dataset's own relative signal units)
    JK amplitude: mean 1.496 (n=20, same units)
"""
from __future__ import annotations

import json
import pathlib

from src.patient_builder.patient_file import bcg_to_cardiovascular_modifiers, build_patient_file
from src.patient_builder.scenario_file import MAX_EXERCISE_INTENSITY, build_scenario_file

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "bcg_validation" / "subject14"
# PulseScenarioDriver only runs inside the kitware/pulse container, where this repo root is
# mounted at /workspace (see docs/CLAUDE.md's docker run command / memory note on project run
# state) -- the PatientFile path embedded in scenario.json must resolve INSIDE that container, not
# to this host's Windows path, even though this script itself builds the JSON on the host.
PATIENT_PATH_IN_CONTAINER = "/workspace/data/bcg_validation/subject14/patient.json"

PATIENT = {
    "patient_id": "bcg_subject14",
    "sex": "Male",
    "age": 53,
    "height_cm": 160,
    "weight_kg": 70,
}
EJECTION_FRACTION_PCT = 34.7

# Manual scenario/severity assignment (Phase 4 classifier is out of scope here -- no 21-day
# wearable-trend window exists for a single-session dataset patient). Per docs/methodology.md's
# own scenario taxonomy (Section 5/7's Phase 2 table), acute_deterioration is the "HFrEF-profile,
# low EF, failing compensation" scenario type -- matches this patient's structural profile
# (EF 34.7% <= the 40% HFrEF threshold, ChronicVentricularSystolicDysfunction condition applies).
# Severity is set at a moderate 0.35, not an extreme value: this is a real clinical snapshot with
# no trend evidence of an ACTIVE acute event (no wearable data exists at all), so the assignment
# reflects the patient's chronic structural HFrEF profile, not an assumed crisis -- deliberately
# conservative given the total absence of trajectory data to justify anything higher.
SCENARIO_TYPE = "acute_deterioration"
SEVERITY = 0.35

RJ_INTERVAL_MS = 233.0
IJ_AMPLITUDE = 1.172
JK_AMPLITUDE = 1.496


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    patient_json = build_patient_file(PATIENT)
    patient_path = OUT_DIR / "patient.json"
    patient_path.write_text(json.dumps(patient_json, indent=2))

    bcg_modifiers = bcg_to_cardiovascular_modifiers(RJ_INTERVAL_MS, IJ_AMPLITUDE, JK_AMPLITUDE)

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

    # ---- Crash-boundary check, printed before any Pulse invocation ----
    exercise_intensity = max(0.1, min(SEVERITY * 0.6, MAX_EXERCISE_INTENSITY))
    cv_action = next(
        a["PatientAction"]["CardiovascularMechanicsModification"]["Modifiers"]
        for a in scenario_json["AnyAction"]
        if "PatientAction" in a and "CardiovascularMechanicsModification" in a["PatientAction"]
    )

    print("=== Patient file ===")
    print(json.dumps(patient_json, indent=2))
    print()
    print("=== BCG modifiers (bcg_to_cardiovascular_modifiers output) ===")
    print(json.dumps(bcg_modifiers, indent=2))
    print()
    print("=== Scenario file ===")
    print(json.dumps(scenario_json, indent=2))
    print()
    print("=== Crash-boundary check ===")
    print(f"scenario_type = {SCENARIO_TYPE}, severity = {SEVERITY}")
    print(f"Exercise action intensity = severity*0.6 = {exercise_intensity:.3f}  "
          f"(documented crash risk starts ~0.45 for cardiac_stress; "
          f"acute_deterioration's own observed crash range is higher, ~0.6-0.85 -- "
          f"either way this is comfortably under both)")
    print(f"Final CardiovascularMechanicsModification.Modifiers (base EF-driven fields + "
          f"scenario extra, with BCG modifiers overriding VenousComplianceMultiplier/"
          f"SystemicComplianceMultiplier):")
    for k, v in cv_action.items():
        print(f"  {k}: {v}")
    print()
    print(f"Wrote: {patient_path}")
    print(f"Wrote: {scenario_path}")


if __name__ == "__main__":
    main()
