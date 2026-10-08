"""BCG/EF ablation, step 1 of 3: build + audit every configuration's patient.json/scenario.json.

Runs on the HOST (needs openpyxl to read Subject_Info.xlsx, which lives outside the repo and is
not mounted into the Pulse container). Step 2 (scripts/bcg_ablation_run.py) runs the built
scenarios inside kitware/pulse:4.3.1; step 3 (scripts/bcg_ablation_report.py) makes the tables.
See docs/bcg_ablation_note.md for the full method and results.

Why this exists: in the original subject-14/102 runs (scripts/bcg_real_patient_validation.py,
scripts/bcg_subject102_validation.py) the EF-driven and BCG-derived multipliers fired at t=60s in
the SAME instant as the Exercise action, so Exercise hid their effect. Here each layer is added
one at a time, each as its own separate Pulse run, with no Exercise until the last step.

Configurations (same for both subjects):
  A        patient file only -- no condition, no action
  BCG_only A + a CardiovascularMechanicsModification carrying ONLY the BCG-derived
           Venous/SystemicComplianceMultiplier (no EF condition, no EF multipliers)
  B        A + ChronicVentricularSystolicDysfunction condition (EF <= 40)
  C        B + CardiovascularMechanicsModification with the EF-driven multipliers only
           (StrokeVolume/SystemicResistance/SystemicCompliance), no Exercise
  D        C + the BCG-derived overrides (Venous/SystemicComplianceMultiplier), no Exercise
  D_HR     D + the acute_deterioration scenario's own HeartRateMultiplier (1.14), no Exercise.
           NOT in the original request: added because the original full scenario (E) also
           contains this multiplier, so without D_HR the E-D difference would silently mix the
           Exercise effect with the HR-multiplier effect.
  E        the original full scenario, built exactly as the original validation scripts did
           (build_scenario_file(... "acute_deterioration", 0.35, EF, extra_modifiers=bcg)).
           Asserted below to be identical (apart from the PatientFile path) to the scenario.json
           the original runs used.

Nothing here tunes anything: multiplier values come unchanged from ef_to_cardiovascular_modifiers()
and bcg_to_cardiovascular_modifiers() with the same inputs the original runs used.
"""
from __future__ import annotations

import json
import pathlib
from collections import Counter

import pandas as pd

from scripts import bcg_real_patient_validation as s14
from scripts import bcg_subject102_validation as s102
from src.patient_builder.patient_file import (
    bcg_to_cardiovascular_modifiers,
    build_patient_file,
    ef_to_cardiovascular_modifiers,
)
from src.patient_builder.scenario_file import (
    DATA_REQUESTS,
    STABILIZATION_S,
    _cardiovascular_modification_action,
    _scalar_unsigned,
    _scenario_actions,
    build_scenario_file,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_ROOT = REPO_ROOT / "data" / "bcg_ablation"
CONTAINER_OUT_ROOT = "/workspace/data/bcg_ablation"
SUBJECT_INFO_XLSX = r"D:\5th sem notes\capstone\Dataset\Information\Subject_Info.xlsx"  # external raw dataset

DURATION_MIN = 10.0  # same as the original runs, so every config has the same 660s time axis
SCENARIO_TYPE = "acute_deterioration"  # original runs' manual assignment, reused unchanged
SEVERITY = 0.35

CONFIG_ORDER = ["A", "BCG_only", "B", "C", "D", "D_HR", "E"]

# BCG features and reference anchors, reused from the original validation scripts (not re-typed).
SUBJECTS = {
    14: {
        "patient_id": s14.PATIENT["patient_id"],
        "bcg": (s14.RJ_INTERVAL_MS, s14.IJ_AMPLITUDE, s14.JK_AMPLITUDE),
        "bcg_reference": {},  # defaults = subject 102's values, exactly as the original subject-14 run
        "original_scenario": REPO_ROOT / "data" / "bcg_validation" / "subject14" / "scenario.json",
        "hardcoded": (s14.PATIENT, s14.EJECTION_FRACTION_PCT),
    },
    102: {
        "patient_id": s102.PATIENT["patient_id"],
        "bcg": (s102.RJ_INTERVAL_MS, s102.IJ_AMPLITUDE, s102.JK_AMPLITUDE),
        "bcg_reference": {
            "rj_reference_ms": s102.SUBJECT14_RJ_MS,
            "amplitude_reference": s102.SUBJECT14_AMPLITUDE_REFERENCE,
        },
        "original_scenario": REPO_ROOT / "data" / "bcg_validation" / "subject102" / "scenario.json",
        "hardcoded": (s102.PATIENT, s102.EJECTION_FRACTION_PCT),
    },
}


def read_subject_info(subject_id: int) -> dict:
    df = pd.read_excel(SUBJECT_INFO_XLSX, sheet_name="HF")
    row = df[df["SubjectID"] == subject_id].iloc[0]
    return {
        "sex": str(row["Sex"]),
        "age": float(row["Age"]),
        "height_cm": float(row["Height(cm)"]),
        "weight_kg": float(row["Weight(kg)"]),
        "hr_bpm": float(row["HR"]),
        "sv_ml": float(row["SV(ml)"]),
        "ef_pct": round(float(row["EF(%)"]) * 100.0, 1),  # xlsx stores EF as a fraction (0.347)
    }


def _advance(value, unit) -> dict:
    return {"AdvanceTime": {"Time": {"ScalarTime": {"Value": value, "Unit": unit}}}}


def _scenario(patient_path: str, with_condition: bool, actions: list[dict]) -> dict:
    """Same shape build_scenario_file() produces: stabilize 60s, fire actions, advance 10 min."""
    patient_configuration = {"PatientFile": patient_path}
    if with_condition:
        patient_configuration["Conditions"] = {
            "AnyCondition": [{"PatientCondition": {"ChronicVentricularSystolicDysfunction": {}}}]
        }
    return {
        "PatientConfiguration": patient_configuration,
        "DataRequestManager": {"DataRequest": DATA_REQUESTS},
        "AnyAction": [_advance(STABILIZATION_S, "s"), *actions, _advance(DURATION_MIN, "min")],
    }


def build_configs(patient_path: str, ef_pct: float, bcg: dict) -> dict[str, dict]:
    ef_mods = ef_to_cardiovascular_modifiers(ef_pct, SEVERITY)
    assert ef_mods["apply_systolic_dysfunction_condition"], "EF > 40: config B's condition would not apply"

    bcg_only_action = {
        "PatientAction": {
            "CardiovascularMechanicsModification": {
                "Modifiers": {k: _scalar_unsigned(v) for k, v in bcg.items()},
                "Incremental": True,  # same flag every production CV action uses
            }
        }
    }
    # The original scenario's CV action + Exercise, minus Exercise.
    full_actions = _scenario_actions(SCENARIO_TYPE, SEVERITY, ef_mods, bcg)
    d_hr_actions = [a for a in full_actions if "Exercise" not in a["PatientAction"]]

    return {
        "A": _scenario(patient_path, False, []),
        "BCG_only": _scenario(patient_path, False, [bcg_only_action]),
        "B": _scenario(patient_path, True, []),
        "C": _scenario(patient_path, True, [_cardiovascular_modification_action(ef_mods, {})]),
        "D": _scenario(patient_path, True, [_cardiovascular_modification_action(ef_mods, bcg)]),
        "D_HR": _scenario(patient_path, True, d_hr_actions),
        "E": build_scenario_file(
            patient_json_path=patient_path,
            scenario_type=SCENARIO_TYPE,
            severity=SEVERITY,
            ejection_fraction_pct=ef_pct,
            duration_min=DURATION_MIN,
            extra_modifiers=bcg,
        ),
    }


def audit(scenario: dict) -> dict:
    """What was actually sent to Pulse, read back from the scenario JSON itself."""
    conditions = [
        name
        for c in scenario["PatientConfiguration"].get("Conditions", {}).get("AnyCondition", [])
        for name in c["PatientCondition"]
    ]
    actions, modifiers, advance = [], {}, []
    modifier_key_counts = Counter()
    for a in scenario["AnyAction"]:
        if "AdvanceTime" in a:
            t = a["AdvanceTime"]["Time"]["ScalarTime"]
            advance.append(f"{t['Value']}{t['Unit']}")
            continue
        for name, body in a["PatientAction"].items():
            actions.append(name)
            if name == "CardiovascularMechanicsModification":
                for k, v in body["Modifiers"].items():
                    modifier_key_counts[k] += 1
                    modifiers[k] = v["ScalarUnsigned"]["Value"]
            elif name == "Exercise":
                modifiers["Exercise.Intensity"] = body["Intensity"]["Scalar0To1"]["Value"]
    duplicates = [k for k, n in modifier_key_counts.items() if n > 1]
    action_dupes = [k for k, n in Counter(actions).items() if n > 1]
    condition_dupes = [k for k, n in Counter(conditions).items() if n > 1]
    return {
        "conditions": conditions,
        "actions": actions,
        "modifiers": modifiers,
        "advance_time": advance,
        "duplicates": duplicates + action_dupes + condition_dupes,
    }


def _strip_patient_path(scenario: dict) -> dict:
    s = json.loads(json.dumps(scenario))
    s["PatientConfiguration"].pop("PatientFile")
    return s


def main() -> None:
    manifest = {"duration_s": STABILIZATION_S + DURATION_MIN * 60, "configs": CONFIG_ORDER, "subjects": {}}

    for subject_id, spec in SUBJECTS.items():
        info = read_subject_info(subject_id)
        hard_patient, hard_ef = spec["hardcoded"]
        # Guard: the xlsx must agree with what the original runs used, or E won't be comparable.
        assert (info["sex"], info["age"], info["height_cm"], info["weight_kg"], info["ef_pct"]) == (
            hard_patient["sex"], hard_patient["age"], hard_patient["height_cm"],
            hard_patient["weight_kg"], hard_ef,
        ), f"subject {subject_id}: xlsx {info} disagrees with original-run constants"

        patient = {"patient_id": spec["patient_id"], **{k: info[k] for k in ("sex", "age", "height_cm", "weight_kg")}}
        bcg = bcg_to_cardiovascular_modifiers(*spec["bcg"], **spec["bcg_reference"])
        subject_dir = OUT_ROOT / f"subject{subject_id}"

        print(f"\n################ Subject {subject_id} ################")
        print(f"Subject_Info.xlsx: {info}")
        print(f"EF-driven modifiers (ef_to_cardiovascular_modifiers({info['ef_pct']}, {SEVERITY})): "
              f"{ef_to_cardiovascular_modifiers(info['ef_pct'], SEVERITY)}")
        print(f"BCG modifiers (bcg_to_cardiovascular_modifiers{spec['bcg']}, ref={spec['bcg_reference'] or 'default=subject 102'}): {bcg}")

        audits = {}
        for label, scenario in build_configs("PLACEHOLDER", info["ef_pct"], bcg).items():
            config_dir = subject_dir / label
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "patient.json").write_text(json.dumps(build_patient_file(patient), indent=2))
            container_patient = f"{CONTAINER_OUT_ROOT}/subject{subject_id}/{label}/patient.json"
            scenario["PatientConfiguration"]["PatientFile"] = container_patient
            (config_dir / "scenario.json").write_text(json.dumps(scenario, indent=2))

            a = audit(scenario)
            audits[label] = a
            assert not a["duplicates"], f"subject {subject_id} {label}: duplicated {a['duplicates']}"
            print(f"\n--- {label} ---")
            print(f"  conditions : {a['conditions'] or 'none'}")
            print(f"  actions    : {a['actions'] or 'none'}")
            print(f"  modifiers  : {a['modifiers'] or 'none'}")
            print(f"  AdvanceTime: {a['advance_time']}   duplicates: {a['duplicates'] or 'none'}")

        original = json.loads(spec["original_scenario"].read_text())
        built_e = json.loads((subject_dir / "E" / "scenario.json").read_text())
        e_matches = _strip_patient_path(original) == _strip_patient_path(built_e)
        print(f"\nConfig E identical to original run's scenario.json (ignoring PatientFile path): {e_matches}")
        assert e_matches, "config E differs from the original full scenario"

        manifest["subjects"][str(subject_id)] = {
            "subject_info": info,
            "real_co_ml_min": info["sv_ml"] * info["hr_bpm"],
            "ef_modifiers": ef_to_cardiovascular_modifiers(info["ef_pct"], SEVERITY),
            "bcg_modifiers": bcg,
            "config_audit": audits,
            "E_matches_original": e_matches,
        }

    (OUT_ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nWrote {OUT_ROOT / 'manifest.json'}")


if __name__ == "__main__":
    main()
