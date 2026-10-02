"""Calibration pilot, Arm C ("direct-set"), as pre-registered in
docs/calibration_pilot/pilot_success_criteria.md, Amendment 2.

Per patient (own body via the unchanged build_patient_file(), BMI clamp included, age 60):
  - HeartRateBaseline = HR_vitals (build_patient_file's hr_baseline_bpm).
  - Systolic/Diastolic baseline = real NIBPs/NIBPd moved to the nearest accepted pair
    (nearest_accepted_bp below), added to the patient JSON afterwards as in calibration_pilot_bp_check.
  - ChronicVentricularSystolicDysfunction ON iff echo EF <= 40 (production's HFREF_EF_THRESHOLD_PCT).
  - StrokeVolumeMultiplier tuned to echo EF +/- 2 points in <= 4 runs (Amendment 2 a): run 1 from
    the knob scan's (SV, EF) points, then bisection of the bracket. All other modifiers 1.0.
Timing and settle check are the knob scan's (60 s -> modification -> 180 s, last 60 s).

Modes: build-free -- tuning is sequential (each run's SV depends on the previous run's EF), so
`run` builds and runs inside the container; `analyze` (host) writes arm_c_results.csv.
  container: MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd)":/workspace -w /workspace \
               kitware/pulse:4.3.1 bash -c "pip3 install -q pandas && python3 -m scripts.calibration_pilot_arm_c run"
  host:      ./venv/Scripts/python.exe -m scripts.calibration_pilot_arm_c analyze
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import pandas as pd

from scripts.calibration_pilot_arm_a import COL_DBP, COL_SBP, COL_TIME, pct_err, run_one
from scripts.calibration_pilot_sensitivity_scan import (
    ADVANCE_MIN, CONDITION, EXPECTED_DURATION_S, PATIENTS_CSV, UNIT_MODIFIERS, WINDOW_S, _metrics_row,
)
from src.patient_builder.patient_file import HFREF_EF_THRESHOLD_PCT, build_patient_file
from src.patient_builder.scenario_file import _cardiovascular_modification_action, build_scenario_file

OUT_ROOT = pathlib.Path("data/calibration_pilot/arm_c")
CONTAINER_OUT_ROOT = "/workspace/data/calibration_pilot/arm_c"
RUN_STATUS = OUT_ROOT / "run_status.json"
RESULTS_CSV = pathlib.Path("data/calibration_pilot/arm_c_results.csv")
ARM_A_RESULTS = pathlib.Path("data/calibration_pilot/arm_a_results.csv")

EF_TOL_POINTS = 2.0
MAX_RUNS = 4
SV_RANGE = (0.6, 1.4)
# Knob scan points (sensitivity_scan.csv, patient 120's body), fixed in Amendment 2 (a).
SCAN_POINTS = {
    True: ((1.0, 25.2), (1.2, 38.6), (1.4, 49.6)),
    False: ((0.6, 42.8), (0.8, 49.8), (1.0, 54.5), (1.2, 64.9)),
}
SBP_RANGE, DBP_RANGE, MAX_DBP_FRACTION = (90.0, 120.0), (60.0, 80.0), 0.75


def nearest_accepted_bp(sbp: float, dbp: float) -> tuple[float, float]:
    """Closest (SBP, DBP) in mmHg, Euclidean, within Pulse 4.3.1's accepted region: the box
    90-120 x 60-80 intersected with DBP <= 0.75*SBP. If the box projection already satisfies the
    ratio it is the answer; otherwise the answer lies on the DBP = 0.75*SBP edge, inside the box."""
    s = min(max(sbp, SBP_RANGE[0]), SBP_RANGE[1])
    d = min(max(dbp, DBP_RANGE[0]), DBP_RANGE[1])
    if d <= MAX_DBP_FRACTION * s:
        return s, d
    # Project onto the line d = 0.75 s, restricted to where it stays inside the box.
    k = MAX_DBP_FRACTION
    s_lo = max(SBP_RANGE[0], DBP_RANGE[0] / k)
    s_hi = min(SBP_RANGE[1], DBP_RANGE[1] / k)
    s_proj = (sbp + k * dbp) / (1 + k * k)
    s_proj = min(max(s_proj, s_lo), s_hi)
    return s_proj, k * s_proj


def first_guess(condition: bool, target_ef: float) -> float:
    pts = SCAN_POINTS[condition]
    sv = float(np.interp(target_ef, [e for _, e in pts], [s for s, _ in pts]))
    return round(min(max(sv, SV_RANGE[0]), SV_RANGE[1]), 4)


def patient_settings(p: dict) -> dict:
    sbp, dbp = nearest_accepted_bp(p["real_sbp_mmhg"], p["real_dbp_mmhg"])
    return {
        "hr_baseline_bpm": float(p["real_hr_bpm"]),
        "bp_original": (float(p["real_sbp_mmhg"]), float(p["real_dbp_mmhg"])),
        "bp_used": (round(sbp, 3), round(dbp, 3)),
        "condition": bool(p["real_ef_pct"] <= HFREF_EF_THRESHOLD_PCT),
        "target_ef": float(p["real_ef_pct"]),
    }


def build_run(p: dict, settings: dict, run_no: int, sv: float) -> pathlib.Path:
    idx = int(p["gu_index_1based"])
    d = OUT_ROOT / f"gu{idx}" / f"run{run_no}"
    d.mkdir(parents=True, exist_ok=True)
    patient = {"patient_id": f"gu{idx}_armC_run{run_no}", "sex": p["sex"], "age": p["age"],
               "height_cm": p["height_cm"], "weight_kg": p["weight_kg"]}
    pf = build_patient_file(patient, hr_baseline_bpm=settings["hr_baseline_bpm"])
    sbp, dbp = settings["bp_used"]
    pf["SystolicArterialPressureBaseline"] = {"ScalarPressure": {"Value": sbp, "Unit": "mmHg"}}
    pf["DiastolicArterialPressureBaseline"] = {"ScalarPressure": {"Value": dbp, "Unit": "mmHg"}}
    scenario = build_scenario_file(f"{CONTAINER_OUT_ROOT}/gu{idx}/run{run_no}/patient.json", "stable", 0.0,
                                   p["real_ef_pct"], duration_min=ADVANCE_MIN)
    # build_scenario_file already adds the condition iff EF <= 40 (same threshold); set explicitly
    # so the condition is exactly settings["condition"], not an implicit side effect.
    if settings["condition"]:
        scenario["PatientConfiguration"]["Conditions"] = {"AnyCondition": [CONDITION]}
    else:
        scenario["PatientConfiguration"].pop("Conditions", None)
    scenario["AnyAction"].insert(1, _cardiovascular_modification_action(
        UNIT_MODIFIERS, {"StrokeVolumeMultiplier": round(sv, 4)}))
    (d / "patient.json").write_text(json.dumps(pf, indent=2))
    (d / "scenario.json").write_text(json.dumps(scenario, indent=2))
    return d


def run() -> None:
    patients = pd.read_csv(PATIENTS_CSV).to_dict("records")
    status = json.loads(RUN_STATUS.read_text()) if RUN_STATUS.exists() else {}
    for p in patients:
        idx = int(p["gu_index_1based"])
        key = f"gu{idx}"
        if key in status and status[key].get("done"):
            continue
        settings = patient_settings(p)
        entry = {"settings": settings, "runs": [], "done": False}
        lo, hi = SV_RANGE
        sv = first_guess(settings["condition"], settings["target_ef"])
        for run_no in range(1, MAX_RUNS + 1):
            d = build_run(p, settings, run_no, sv)
            print(f"[{key} run{run_no}] SV={sv:.4f} ...", flush=True)
            result = run_one(d.resolve() / "scenario.json", EXPECTED_DURATION_S)
            rec = {"run_no": run_no, "sv": sv, **result}
            if not result["crashed"]:
                m = _metrics_row(d / "scenarioResults.csv")
                rec.update({"ef_pct": float(m["ef_pct"]), "settled": bool(m["settled"])})  # numpy -> JSON-safe
                print(f"[{key} run{run_no}] EF={m['ef_pct']:.2f} (target {settings['target_ef']:g}) "
                      f"settled={m['settled']} in {result['wall_clock_s']}s", flush=True)
            else:
                print(f"[{key} run{run_no}] CRASHED in {result['wall_clock_s']}s: {result['error'][:800]}", flush=True)
            entry["runs"].append(rec)
            status[key] = entry
            RUN_STATUS.write_text(json.dumps(status, indent=2))
            if result["crashed"]:
                if "initialize" in (result["error"] or "").lower() or any(
                        "initialize" in line.lower() for line in result["fatal_marker_lines"]):
                    print(f"[{key}] engine could not be started with these settings -- stopping this patient", flush=True)
                    break
            else:
                gap = rec["ef_pct"] - settings["target_ef"]
                if abs(gap) <= EF_TOL_POINTS:
                    break
                if gap < 0:
                    lo = sv
                else:
                    hi = sv
            sv = round((lo + hi) / 2, 4)
        ok = [r for r in entry["runs"] if not r["crashed"]]
        entry["final_run_no"] = (min(ok, key=lambda r: abs(r["ef_pct"] - settings["target_ef"]))["run_no"]
                                 if ok else None)
        entry["done"] = True
        RUN_STATUS.write_text(json.dumps(status, indent=2))


def analyze() -> None:
    patients = pd.read_csv(PATIENTS_CSV).set_index("gu_index_1based")
    status = json.loads(RUN_STATUS.read_text())
    rows = []
    for key, entry in status.items():
        idx = int(key.removeprefix("gu"))
        p = patients.loc[idx]
        st = entry["settings"]
        real_sv_td = p["real_co_l_min"] * 1000.0 / p["real_hr_bpm"]
        real_sv_fick = p["real_co_fick_l_min"] * 1000.0 / p["real_hr_bpm"]
        for r in entry["runs"]:
            row = {
                "set": p["set"], "gu_index_1based": idx, "run_no": r["run_no"],
                "final": r["run_no"] == entry.get("final_run_no"),
                "condition": st["condition"], "hr_baseline_bpm": st["hr_baseline_bpm"],
                "bp_original_sys": st["bp_original"][0], "bp_original_dia": st["bp_original"][1],
                "bp_used_sys": st["bp_used"][0], "bp_used_dia": st["bp_used"][1],
                "bp_moved": tuple(st["bp_original"]) != tuple(st["bp_used"]),
                "stroke_volume_multiplier": r["sv"], "target_ef_pct": st["target_ef"],
                "crashed": r["crashed"], "fatal_marker_lines": " | ".join(r["fatal_marker_lines"]),
                "error": (r["error"] or "")[:500], "wall_clock_s": r["wall_clock_s"],
                "real_ef_pct": p["real_ef_pct"], "real_hr_bpm": p["real_hr_bpm"],
                "real_map_mmhg": p["real_map_mmhg"], "real_co_l_min": p["real_co_l_min"],
                "real_co_fick_l_min": p["real_co_fick_l_min"],
                "real_sv_td_ml": round(real_sv_td, 2), "real_sv_fick_ml": round(real_sv_fick, 2),
            }
            if not r["crashed"]:
                path = OUT_ROOT / key / f"run{r['run_no']}" / "scenarioResults.csv"
                m = _metrics_row(path)
                df = pd.read_csv(path)
                end = df[COL_TIME].iloc[-1]
                w = df[df[COL_TIME] >= end - WINDOW_S]
                sbp, dbp = w[COL_SBP].mean(), w[COL_DBP].mean()
                map_f = (2 * dbp + sbp) / 3
                row.update({
                    "twin_ef_pct": m["ef_pct"], "twin_edv_ml": m["edv_ml"], "twin_esv_ml": m["esv_ml"],
                    "twin_sv_ml": m["sv_ml"], "twin_map_mmhg": m["map_mmhg"],
                    "twin_sbp_mmhg": round(sbp, 2), "twin_dbp_mmhg": round(dbp, 2),
                    "twin_map_formula_mmhg": round(map_f, 2), "twin_co_l_min": m["co_l_min"],
                    "twin_hr_bpm": m["hr_bpm"], "settled": m["settled"], "max_drift_pct": m["max_drift_pct"],
                    "ef_gap_points": round(m["ef_pct"] - st["target_ef"], 2),
                    "ef_within_tol": abs(m["ef_pct"] - st["target_ef"]) <= EF_TOL_POINTS,
                    "err_ef_pct": pct_err(m["ef_pct"], p["real_ef_pct"]),
                    "err_hr_pct": pct_err(m["hr_bpm"], p["real_hr_bpm"]),
                    "err_map_formula_pct": pct_err(map_f, p["real_map_mmhg"]),
                    "err_sv_td_pct": pct_err(m["sv_ml"], real_sv_td),
                    "err_sv_fick_pct": pct_err(m["sv_ml"], real_sv_fick),
                    "err_co_pct": pct_err(m["co_l_min"], p["real_co_l_min"]),
                    "err_co_fick_pct": pct_err(m["co_l_min"], p["real_co_fick_l_min"]),
                })
                row["mean_abs_err_pct"] = round(np.mean([abs(row[c]) for c in (
                    "err_ef_pct", "err_hr_pct", "err_map_formula_pct", "err_sv_td_pct", "err_co_pct")]), 1)
            rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS_CSV, index=False)
    pd.set_option("display.width", 250)
    print(out[["gu_index_1based", "run_no", "final", "condition", "stroke_volume_multiplier", "target_ef_pct",
               "crashed", "twin_ef_pct", "ef_gap_points", "settled", "twin_hr_bpm", "twin_map_formula_mmhg",
               "twin_co_l_min", "err_co_pct"]].round(2).to_string(index=False))
    print(f"\ncrashed runs: {int(out['crashed'].sum())} of {len(out)}")


if __name__ == "__main__":
    {"run": run, "analyze": analyze}[sys.argv[1]]()
