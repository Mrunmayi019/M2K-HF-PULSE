"""Calibration pilot, Part 4: one-knob-at-a-time Pulse sensitivity scan (13 new runs).

Every run uses Gu patient 120's demographics (Female, 163 cm, 68.9 kg, age assumed 60; no weight
clamp needed) at rest, with no scenario actions -- built by the unchanged build_patient_file() and
build_scenario_file("stable", severity=0, ...), so the only differences between runs are the ones
listed in RUNS below:
  - `condition`: ChronicVentricularSystolicDysfunction added to the patient's Conditions, in the
    same JSON shape build_scenario_file() uses when EF <= 40.
  - `knob` / `value`: one CardiovascularMechanicsModification, all other multipliers at 1.0, built
    with scenario_file's own _cardiovascular_modification_action() (production's JSON shape,
    Incremental=true), fired right after the 60 s builder stabilization.
  - `hr_baseline_bpm`: passed to build_patient_file(), which clamps it to [50, 110] -- the range
    Pulse 4.3.1 accepts (SetupPatient.cpp). 55 and 90 are both inside it, so neither is clamped.

The condition-OFF, no-modifier baseline is NOT rerun: it is the existing A_prod gu120 run from
calibration_pilot_arm_a (same patient/scenario files, but a 180 s run rather than 240 s -- its
windows are therefore t=120-180 and t=60-120, see BASELINE_ID).

Timeline (new runs): 60 s stabilization -> [modification] -> advance 180 s = 240 s. Metrics from the
last 60 s (t=180-240); the 60 s before that (t=120-180) is computed too, and a run is flagged
"not settled" if any output differs by more than SETTLE_TOL between the two windows.

Modes (same split as calibration_pilot_arm_a: Pulse only exists in the container):
  1. host:      ./venv/Scripts/python.exe -m scripts.calibration_pilot_sensitivity_scan build
  2. container: MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd)":/workspace -w /workspace \
                  kitware/pulse:4.3.1 bash -c "pip3 install -q pandas && python3 -m scripts.calibration_pilot_sensitivity_scan run"
  3. host:      ./venv/Scripts/python.exe -m scripts.calibration_pilot_sensitivity_scan analyze
"""
from __future__ import annotations

import json
import pathlib
import sys

import pandas as pd

from scripts.calibration_pilot_arm_a import COL_TIME, run_dir as arm_a_run_dir, run_one, window_metrics
from src.patient_builder.patient_file import build_patient_file
from src.patient_builder.scenario_file import _cardiovascular_modification_action, build_scenario_file

OUT_ROOT = pathlib.Path("data/calibration_pilot/sensitivity")
CONTAINER_OUT_ROOT = "/workspace/data/calibration_pilot/sensitivity"
PATIENTS_CSV = pathlib.Path("data/calibration_pilot/pilot_patients.csv")
RUN_STATUS = OUT_ROOT / "run_status.json"
SCAN_CSV = pathlib.Path("data/calibration_pilot/sensitivity_scan.csv")

PATIENT_IDX = 120
STABILIZATION_S = 60.0
ADVANCE_MIN = 3.0
EXPECTED_DURATION_S = STABILIZATION_S + ADVANCE_MIN * 60
WINDOW_S = 60.0
SETTLE_TOL = 0.02
OUTPUTS = ("ef_pct", "edv_ml", "esv_ml", "sv_ml", "map_mmhg", "co_l_min", "hr_bpm")

BASELINE_ID = "off_baseline"  # reused A_prod gu120 run
ON_BASELINE_ID = "on_baseline"
CONDITION = {"PatientCondition": {"ChronicVentricularSystolicDysfunction": {}}}
UNIT_MODIFIERS = {"stroke_volume_multiplier": 1.0, "systemic_resistance_multiplier": 1.0,
                  "systemic_compliance_multiplier": 1.0}

# (run_id, condition, knob, value, hr_baseline_bpm). Each varied setting's reference run for the
# % change columns: condition-OFF runs -> off_baseline; condition-ON knob runs -> on_baseline;
# on_baseline itself -> off_baseline.
RUNS = [
    (ON_BASELINE_ID, True, None, None, None),
    ("off_sv_0.6", False, "StrokeVolumeMultiplier", 0.6, None),
    ("off_sv_0.8", False, "StrokeVolumeMultiplier", 0.8, None),
    ("off_sv_1.2", False, "StrokeVolumeMultiplier", 1.2, None),
    ("off_sr_0.7", False, "SystemicResistanceMultiplier", 0.7, None),
    ("off_sr_1.3", False, "SystemicResistanceMultiplier", 1.3, None),
    ("off_sc_0.7", False, "SystemicComplianceMultiplier", 0.7, None),
    ("off_sc_1.3", False, "SystemicComplianceMultiplier", 1.3, None),
    ("off_vc_0.6", False, "VenousComplianceMultiplier", 0.6, None),
    ("off_vc_1.4", False, "VenousComplianceMultiplier", 1.4, None),
    ("off_hr_55", False, None, None, 55.0),
    ("off_hr_90", False, None, None, 90.0),
    ("on_sv_1.2", True, "StrokeVolumeMultiplier", 1.2, None),
    ("on_sv_1.4", True, "StrokeVolumeMultiplier", 1.4, None),
]


def reference_for(run_id: str, condition: bool) -> str:
    if run_id == ON_BASELINE_ID or not condition:
        return BASELINE_ID
    return ON_BASELINE_ID


def build() -> None:
    p = pd.read_csv(PATIENTS_CSV).set_index("gu_index_1based").loc[PATIENT_IDX]
    for run_id, condition, knob, value, hr in RUNS:
        d = OUT_ROOT / run_id
        d.mkdir(parents=True, exist_ok=True)
        patient = {"patient_id": f"gu{PATIENT_IDX}_{run_id}", "sex": p["sex"], "age": p["age"],
                   "height_cm": p["height_cm"], "weight_kg": p["weight_kg"]}
        container_patient = f"{CONTAINER_OUT_ROOT}/{run_id}/patient.json"
        scenario = build_scenario_file(container_patient, "stable", 0.0, p["real_ef_pct"], duration_min=ADVANCE_MIN)
        if condition:
            scenario["PatientConfiguration"]["Conditions"] = {"AnyCondition": [CONDITION]}
        if knob is not None:
            scenario["AnyAction"].insert(1, _cardiovascular_modification_action(UNIT_MODIFIERS, {knob: value}))
        (d / "patient.json").write_text(json.dumps(build_patient_file(patient, hr_baseline_bpm=hr), indent=2))
        (d / "scenario.json").write_text(json.dumps(scenario, indent=2))
    print(f"Built {len(RUNS)} scans under {OUT_ROOT}")


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


def _metrics_row(results_csv: pathlib.Path) -> dict:
    df = pd.read_csv(results_csv)
    end = df[COL_TIME].iloc[-1]
    last = window_metrics(df, end - WINDOW_S, end)
    prev = window_metrics(df, end - 2 * WINDOW_S, end - WINDOW_S)
    drift = {k: abs(last[k] - prev[k]) / abs(prev[k]) for k in OUTPUTS}
    worst = max(drift, key=drift.get)
    return {
        "window_last_s": f"{end - WINDOW_S:g}-{end:g}", "window_prev_s": f"{end - 2 * WINDOW_S:g}-{end - WINDOW_S:g}",
        **{k: round(last[k], 3) for k in OUTPUTS},
        "ef_sd_pct": round(last["ef_sd_pct"], 3), "n_beats": last["n_beats"],
        **{f"prev_{k}": round(prev[k], 3) for k in OUTPUTS},
        "max_drift_pct": round(100 * drift[worst], 2), "max_drift_output": worst,
        "settled": drift[worst] <= SETTLE_TOL,
    }


def analyze() -> None:
    status = json.loads(RUN_STATUS.read_text())
    arm_a_status = json.loads(pathlib.Path("data/calibration_pilot/arm_a_run_status.json").read_text())
    base_status = arm_a_status["A_prod"][f"gu{PATIENT_IDX}"]

    rows = [{
        "run_id": BASELINE_ID, "source": f"reused A_prod gu{PATIENT_IDX} run (180 s, no modifiers)",
        "condition": False, "knob": None, "value": None, "hr_baseline_bpm": None, "reference": None,
        "crashed": base_status["crashed"], "fatal_marker_lines": " | ".join(base_status["fatal_marker_lines"]),
        **_metrics_row(arm_a_run_dir("A_prod", PATIENT_IDX) / "scenarioResults.csv"),
    }]
    for run_id, condition, knob, value, hr in RUNS:
        s = status[run_id]
        row = {"run_id": run_id, "source": "new scan run (240 s)", "condition": condition, "knob": knob,
               "value": value, "hr_baseline_bpm": hr, "reference": reference_for(run_id, condition),
               "crashed": s["crashed"], "fatal_marker_lines": " | ".join(s["fatal_marker_lines"])}
        if not s["crashed"]:
            row.update(_metrics_row(OUT_ROOT / run_id / "scenarioResults.csv"))
        rows.append(row)

    out = pd.DataFrame(rows)
    by_id = out.set_index("run_id")
    for k in OUTPUTS:
        out[f"pct_change_{k}"] = [
            round(100 * (r[k] - by_id.loc[r["reference"], k]) / by_id.loc[r["reference"], k], 1)
            if pd.notna(r["reference"]) and not r["crashed"] and not by_id.loc[r["reference"], "crashed"] else None
            for _, r in out.iterrows()
        ]
    out.to_csv(SCAN_CSV, index=False)
    print(out[["run_id", "condition", "knob", "value", "hr_baseline_bpm", "crashed", "settled", "max_drift_pct",
               *OUTPUTS]].to_string(index=False))
    print(f"\ncrashed runs: {int(out['crashed'].sum())}")


if __name__ == "__main__":
    {"build": build, "run": run, "analyze": analyze}[sys.argv[1]]()
