"""Calibration pilot, Step 2: extract the 3 pilot patients from Gu et al.'s TriSeg digital-twin
dataset into data/calibration_pilot/pilot_patients.csv.

Source: https://github.com/beards-lab/TriSeg-Digital-Twins (MIT license), cloned into
data/raw/gu_triseg/ (gitignored via data/raw/). Only AllPatients.mat is read. Gu et al.,
npj Digital Medicine 2025.

Field decisions, each verified rather than assumed:
  - Sex: targetVals_HF.m:33-37 uses the male Nadler blood-volume equation for `Sex == 1` and
    asserts `Sex == 2` on the female branch -> 1 = Male, 2 = Female. Mapped to the strings
    build_patient_file() expects ("Male"/"Female").
  - Age: targetVals_HF.m:31 computes `years(Windowdate - Birthday)`, but Birthday (like every
    date field) is a MATLAB datetime object, which scipy.io.loadmat returns as an opaque MCOS
    handle with no readable value. Per the pilot plan, a fixed AGE_ASSUMPTION_YR is used for all
    3 patients instead and flagged in the CSV's age_source column.
  - First snapshot only: `patients[i].snapshots` is a single struct for some patients and an
    array of structs for others (squeeze_me=True collapses length-1 arrays); index 0 is taken
    either way.
  - Real MAP = DBP + (SBP - DBP) / 3, from the non-invasive NIBPs_vitals / NIBPd_vitals cuffs.
  - BMI clamp: build_patient_file() caps BMI at PULSE_MAX_BMI. The original and the
    Pulse-adjusted weight are both recorded so the clamp is visible, not silent.

Usage: ./venv/Scripts/python.exe -m scripts.calibration_pilot_extract_gu
"""
from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd
import scipy.io as sio

from src.patient_builder.patient_file import pulse_eligible_age, pulse_eligible_weight_kg

GU_MAT_PATH = pathlib.Path("data/raw/gu_triseg/AllPatients.mat")
OUT_PATH = pathlib.Path("data/calibration_pilot/pilot_patients.csv")
SOURCE = "Gu et al. 2025 npj Digit Med; beards-lab/TriSeg-Digital-Twins AllPatients.mat (MIT), first snapshot"

AGE_ASSUMPTION_YR = 60.0
GU_SEX_CODES = {1: "Male", 2: "Female"}  # targetVals_HF.m:33-37

# 1-based patient indices and the values the pilot plan expects -- checked, not trusted. The plan's
# values are rounded (e.g. 136's CO_td is 4.53 in the .mat, 4.5 in the plan), so the check allows
# PLAN_ROUNDING_TOL; the CSV always carries the dataset's own unrounded value.
PLAN_ROUNDING_TOL = 0.05
EXPECTED = {
    295: dict(sex=2, height_cm=168, weight_kg=86.5, lvef_tte=25, nibps=127.5, nibpd=67.5, co_td=3.4, hr_vitals=78.0, pcw=26),
    136: dict(sex=1, height_cm=183, weight_kg=73.2, lvef_tte=40, nibps=101.0, nibpd=63.0, co_td=4.5, hr_vitals=54.5, pcw=14),
    120: dict(sex=2, height_cm=163, weight_kg=68.9, lvef_tte=58, nibps=130.5, nibpd=90.0, co_td=3.7, hr_vitals=91.5, pcw=7),
}


def first_snapshot(patient):
    snaps = patient.snapshots
    return snaps[0] if isinstance(snaps, np.ndarray) else snaps


def main() -> None:
    mat = sio.loadmat(GU_MAT_PATH, squeeze_me=True, struct_as_record=False)
    patients = mat["patients"]

    rows = []
    for idx, expected in EXPECTED.items():
        s = first_snapshot(patients[idx - 1])
        birthday_readable = not type(s.Birthday).__name__.startswith("MatlabOpaque")
        if birthday_readable:
            raise RuntimeError(f"patient {idx}: Birthday unexpectedly readable ({s.Birthday!r}) -- revisit age handling")

        found = dict(
            sex=int(s.Sex), height_cm=float(s.Height), weight_kg=float(s.Weight), lvef_tte=float(s.LVEF_tte),
            nibps=float(s.NIBPs_vitals), nibpd=float(s.NIBPd_vitals), co_td=float(s.CO_td),
            hr_vitals=float(s.HR_vitals), pcw=float(s.PCW),
        )
        mismatches = {k: (v, found[k]) for k, v in expected.items() if abs(found[k] - v) > PLAN_ROUNDING_TOL}
        if mismatches:
            raise RuntimeError(f"patient {idx}: values differ from the pilot plan (expected, found): {mismatches}")

        pulse_weight = pulse_eligible_weight_kg(found["height_cm"], found["weight_kg"])
        rows.append({
            "gu_index_1based": idx,
            "gu_patId": int(s.patId),
            "gu_sex_code": found["sex"],
            "sex": GU_SEX_CODES[found["sex"]],
            "age": AGE_ASSUMPTION_YR,
            "age_source": "ASSUMED fixed 60 (Birthday is an MCOS datetime, unreadable via scipy)",
            "pulse_age": pulse_eligible_age(AGE_ASSUMPTION_YR),
            "height_cm": found["height_cm"],
            "weight_kg": found["weight_kg"],
            "bmi": round(found["weight_kg"] / (found["height_cm"] / 100) ** 2, 2),
            "pulse_weight_kg": round(pulse_weight, 2),
            "weight_clamped_for_pulse": not np.isclose(pulse_weight, found["weight_kg"]),
            "real_ef_pct": found["lvef_tte"],
            "real_sbp_mmhg": found["nibps"],
            "real_dbp_mmhg": found["nibpd"],
            "real_map_mmhg": round(found["nibpd"] + (found["nibps"] - found["nibpd"]) / 3, 2),
            "real_co_l_min": found["co_td"],
            "real_hr_bpm": found["hr_vitals"],
            "real_pcw_mmhg": found["pcw"],
            "source": SOURCE,
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT_PATH, index=False)
    for idx, expected in EXPECTED.items():
        row = next(r for r in rows if r["gu_index_1based"] == idx)
        s = first_snapshot(patients[idx - 1])
        for k, v in expected.items():
            actual = {"sex": s.Sex, "height_cm": s.Height, "weight_kg": s.Weight, "lvef_tte": s.LVEF_tte, "nibps": s.NIBPs_vitals,
                      "nibpd": s.NIBPd_vitals, "co_td": s.CO_td, "hr_vitals": s.HR_vitals, "pcw": s.PCW}[k]
            if float(actual) != float(v):
                print(f"NOTE patient {idx}: {k} plan={v} dataset={actual} (within rounding tolerance; dataset value used)")
    print(f"All 3 patients match the pilot plan's values within {PLAN_ROUNDING_TOL}. Wrote {OUT_PATH}")
    print(df.drop(columns=["source", "age_source"]).to_string(index=False))


if __name__ == "__main__":
    main()
