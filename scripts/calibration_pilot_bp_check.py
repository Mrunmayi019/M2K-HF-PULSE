"""Calibration pilot: blood-pressure lever check (11 runs).

Same body, timing and settle check as calibration_pilot_sensitivity_scan: Gu patient 120's
demographics, resting, 60 s stabilization -> [modification] -> advance 180 s, metrics from the last
60 s, flagged not settled if any output differs > 2% from the 60 s before.

Patient files come from the unchanged build_patient_file(); the blood-pressure baselines it does
not set are added here afterwards, as Patient.proto's SystolicArterialPressureBaseline /
DiastolicArterialPressureBaseline (ScalarPressure, mmHg). Pulse 4.3.1 (SetupPatient.cpp) accepts
systolic 90-120 and diastolic 60-80 mmHg with diastolic <= 0.75 x systolic, and refuses to start
outside them -- so the lowest accepted pair is 90/60 and the highest 120/80 (both 0.667).

Pulse's MeanArterialPressure output is a time average of aortic pressure, not (2*DBP + SBP)/3;
the real MAP in pilot_patients.csv uses the formula. Both are written: `map_mmhg` (Pulse) and
`map_formula_mmhg` (twin's own SBP/DBP through the same formula as the real value).

Modes: build (host) / run (container) / analyze (host), as in the other pilot scripts.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pandas as pd

from scripts.calibration_pilot_arm_a import COL_TIME, run_one
from scripts.calibration_pilot_sensitivity_scan import (
    ADVANCE_MIN, CONDITION, EXPECTED_DURATION_S, OUTPUTS, PATIENT_IDX, PATIENTS_CSV, UNIT_MODIFIERS, WINDOW_S,
    _metrics_row,
)
from src.patient_builder.patient_file import build_patient_file
from src.patient_builder.scenario_file import _cardiovascular_modification_action, build_scenario_file

OUT_ROOT = pathlib.Path("data/calibration_pilot/bp_check")
CONTAINER_OUT_ROOT = "/workspace/data/calibration_pilot/bp_check"
RUN_STATUS = OUT_ROOT / "run_status.json"
BP_CSV = pathlib.Path("data/calibration_pilot/bp_check.csv")

COL_SBP = "SystolicArterialPressure(mmHg)"
COL_DBP = "DiastolicArterialPressure(mmHg)"

BP_LOW = (90.0, 60.0)
BP_HIGH = (120.0, 80.0)

# (run_id, group, condition, bp (sys, dia) or None, hr_baseline_bpm, {knob: value})
RUNS = [
    ("A_off_bp_low", "A", False, BP_LOW, None, {}),
    ("A_off_bp_high", "A", False, BP_HIGH, None, {}),
    ("B_on_bp_low", "B", True, BP_LOW, None, {}),
    ("B_on_bp_high", "B", True, BP_HIGH, None, {}),
    ("C_off_ar_1.3", "C", False, None, None, {"ArterialResistanceMultiplier": 1.3}),
    ("C_off_vr_1.3", "C", False, None, None, {"VenousResistanceMultiplier": 1.3}),
    ("C_off_hrm_1.2", "C", False, None, None, {"HeartRateMultiplier": 1.2}),
    ("D_on_sr_1.3", "D", True, None, None, {"SystemicResistanceMultiplier": 1.3}),
    ("D_on_ar_1.3", "D", True, None, None, {"ArterialResistanceMultiplier": 1.3}),
    ("E_off_hr90_bphigh_sv0.8", "E", False, BP_HIGH, 90.0, {"StrokeVolumeMultiplier": 0.8}),
    ("E_on_hr90_bphigh_sv1.2", "E", True, BP_HIGH, 90.0, {"StrokeVolumeMultiplier": 1.2}),
]


def _pressure(v: float) -> dict:
    return {"ScalarPressure": {"Value": v, "Unit": "mmHg"}}


def build() -> None:
    p = pd.read_csv(PATIENTS_CSV).set_index("gu_index_1based").loc[PATIENT_IDX]
    for run_id, _, condition, bp, hr, knobs in RUNS:
        d = OUT_ROOT / run_id
        d.mkdir(parents=True, exist_ok=True)
        patient = {"patient_id": f"gu{PATIENT_IDX}_{run_id}", "sex": p["sex"], "age": p["age"],
                   "height_cm": p["height_cm"], "weight_kg": p["weight_kg"]}
        pf = build_patient_file(patient, hr_baseline_bpm=hr)
        if bp is not None:
            pf["SystolicArterialPressureBaseline"] = _pressure(bp[0])
            pf["DiastolicArterialPressureBaseline"] = _pressure(bp[1])
        scenario = build_scenario_file(f"{CONTAINER_OUT_ROOT}/{run_id}/patient.json", "stable", 0.0,
                                       p["real_ef_pct"], duration_min=ADVANCE_MIN)
        if condition:
            scenario["PatientConfiguration"]["Conditions"] = {"AnyCondition": [CONDITION]}
        if knobs:
            scenario["AnyAction"].insert(1, _cardiovascular_modification_action(UNIT_MODIFIERS, knobs))
        (d / "patient.json").write_text(json.dumps(pf, indent=2))
        (d / "scenario.json").write_text(json.dumps(scenario, indent=2))
    print(f"Built {len(RUNS)} runs under {OUT_ROOT}")


def run() -> None:
    status = json.loads(RUN_STATUS.read_text()) if RUN_STATUS.exists() else {}
    for run_id, *_ in RUNS:
        scenario_path = (OUT_ROOT / run_id).resolve() / "scenario.json"
        print(f"[{run_id}] running ...", flush=True)
        result = run_one(scenario_path, EXPECTED_DURATION_S)
        status[run_id] = result
        RUN_STATUS.write_text(json.dumps(status, indent=2))  # after every run
        print(f"[{run_id}] crashed={result['crashed']} in {result['wall_clock_s']}s", flush=True)
        if result["error"]:
            print(f"    {result['error'][:1500]}", flush=True)


def analyze() -> None:
    status = json.loads(RUN_STATUS.read_text())
    rows = []
    for run_id, group, condition, bp, hr, knobs in RUNS:
        s = status[run_id]
        row = {
            "run_id": run_id, "group": group, "condition": condition,
            "bp_baseline_sys": bp[0] if bp else None, "bp_baseline_dia": bp[1] if bp else None,
            "bp_baseline_map_formula": round((2 * bp[1] + bp[0]) / 3, 2) if bp else None,
            "hr_baseline_bpm": hr, "knobs": json.dumps(knobs) if knobs else None,
            "crashed": s["crashed"], "fatal_marker_lines": " | ".join(s["fatal_marker_lines"]),
            "error": (s["error"] or "")[:500],
        }
        if not s["crashed"]:
            results_csv = OUT_ROOT / run_id / "scenarioResults.csv"
            row.update(_metrics_row(results_csv))
            df = pd.read_csv(results_csv)
            end = df[COL_TIME].iloc[-1]
            w = df[df[COL_TIME] >= end - WINDOW_S]
            sbp, dbp = w[COL_SBP].mean(), w[COL_DBP].mean()
            row.update({"sbp_mmhg": round(sbp, 2), "dbp_mmhg": round(dbp, 2),
                        "map_formula_mmhg": round((2 * dbp + sbp) / 3, 2)})
        rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(BP_CSV, index=False)
    cols = ["run_id", "crashed", "settled", "max_drift_pct", *OUTPUTS, "sbp_mmhg", "dbp_mmhg", "map_formula_mmhg"]
    print(out[[c for c in cols if c in out.columns]].to_string(index=False))
    print(f"\ncrashed runs: {int(out['crashed'].sum())}")


if __name__ == "__main__":
    {"build": build, "run": run, "analyze": analyze}[sys.argv[1]]()
