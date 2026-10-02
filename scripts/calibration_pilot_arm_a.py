"""Calibration pilot, Step 4: Arm A baselines for the 3 Gu et al. patients (6 Pulse runs).

Arms (defined before any run in docs/calibration_pilot/pilot_success_criteria.md):
  - A_prod    (primary): build_patient_file() + build_scenario_file("stable", severity=0, real EF,
               duration_min=2) exactly as production builds them. Under "stable",
               _scenario_actions() returns no actions, so of ef_to_cardiovascular_modifiers()'s
               output only the ChronicVentricularSystolicDysfunction condition (EF <= 40) reaches
               Pulse -- its multipliers are computed and then discarded.
  - A_formula (secondary): the identical scenario plus one CardiovascularMechanicsModification
               carrying the formula's multipliers, inserted right after the 60s builder
               stabilization (the same position every non-stable scenario type fires it). Built
               here only, via scenario_file's own _cardiovascular_modification_action() so the
               action JSON matches production's shape; no existing file is modified.

Timeline (both arms): 60s builder AdvanceTime -> [A_formula: modification] -> 120s rest = 180s.
Metrics come from the final 60s (t >= 120s).

Three modes, because Pulse only exists inside the container but the analysis uses the host venv:
  1. host:      ./venv/Scripts/python.exe -m scripts.calibration_pilot_arm_a build
  2. container: MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd)":/workspace -w /workspace \
                  kitware/pulse:4.3.1 bash -c "pip3 install -q pandas && python3 -m scripts.calibration_pilot_arm_a run"
  3. host:      ./venv/Scripts/python.exe -m scripts.calibration_pilot_arm_a analyze

Crash handling: runs go through the existing run_pulse() unchanged (nonzero exit, fatal log
markers, or a truncated CSV all raise). Every run is recorded with crashed=true/false and the
exact log lines that matched runner.FATAL_LOG_MARKERS -- a crashed run is never analyzed as a
success.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np
import pandas as pd

from src.patient_builder.patient_file import build_patient_file, ef_to_cardiovascular_modifiers
from src.patient_builder.scenario_file import _cardiovascular_modification_action, build_scenario_file

OUT_ROOT = pathlib.Path("data/calibration_pilot")
CONTAINER_OUT_ROOT = "/workspace/data/calibration_pilot"
PATIENTS_CSV = OUT_ROOT / "pilot_patients.csv"
RUN_STATUS = OUT_ROOT / "arm_a_run_status.json"
RESULTS_CSV = OUT_ROOT / "arm_a_results.csv"

ARMS = ("A_prod", "A_formula")
SCENARIO_TYPE = "stable"
SEVERITY = 0.0
DURATION_MIN = 2.0
EXPECTED_DURATION_S = 60 + DURATION_MIN * 60  # builder's STABILIZATION_S + rest
ANALYSIS_WINDOW_S = 60.0
TIMEOUT_SEC = 420  # sequential runs only; HANDOFF.md documents CPU-contention timeouts at 180s

COL_TIME = "Time(s)"
COL_HR = "HeartRate(1/min)"
COL_MAP = "MeanArterialPressure(mmHg)"
COL_CO = "CardiacOutput(mL/min)"
COL_LV_VOLUME = "LeftHeart-Volume(mL)"


def run_dir(arm: str, idx: int) -> pathlib.Path:
    return OUT_ROOT / "runs" / arm / f"gu{idx}"


def build() -> None:
    patients = pd.read_csv(PATIENTS_CSV)
    knobs = {}
    for p in patients.to_dict("records"):
        idx = int(p["gu_index_1based"])
        patient = {"patient_id": f"gu{idx}", "sex": p["sex"], "age": p["age"],
                   "height_cm": p["height_cm"], "weight_kg": p["weight_kg"]}
        modifiers = ef_to_cardiovascular_modifiers(p["real_ef_pct"], SEVERITY)
        knobs[idx] = modifiers
        for arm in ARMS:
            d = run_dir(arm, idx)
            d.mkdir(parents=True, exist_ok=True)
            container_patient = f"{CONTAINER_OUT_ROOT}/runs/{arm}/gu{idx}/patient.json"
            scenario = build_scenario_file(container_patient, SCENARIO_TYPE, SEVERITY, p["real_ef_pct"],
                                           duration_min=DURATION_MIN)
            if arm == "A_formula":
                # Insert after the first AdvanceTime (the 60s builder stabilization).
                scenario["AnyAction"].insert(1, _cardiovascular_modification_action(modifiers, {}))
            (d / "patient.json").write_text(json.dumps(build_patient_file(patient), indent=2))
            (d / "scenario.json").write_text(json.dumps(scenario, indent=2))
    (OUT_ROOT / "arm_a_knobs.json").write_text(json.dumps(knobs, indent=2))
    print(json.dumps(knobs, indent=2))


def run() -> None:
    from src.pulse_runner.runner import PulseExecutionError, _scan_log_for_fatal_markers, run_pulse

    patients = pd.read_csv(PATIENTS_CSV)
    status = json.loads(RUN_STATUS.read_text()) if RUN_STATUS.exists() else {}
    for arm in ARMS:
        for idx in patients["gu_index_1based"]:
            scenario_path = run_dir(arm, int(idx)).resolve() / "scenario.json"
            print(f"[{arm} / gu{idx}] running ...", flush=True)
            start = time.monotonic()
            try:
                run_pulse(str(scenario_path), expected_duration_s=EXPECTED_DURATION_S, timeout_sec=TIMEOUT_SEC)
                crashed, error = False, None
            except PulseExecutionError as e:
                crashed, error = True, str(e)
            log_path = scenario_path.with_suffix(".log")
            marker_lines = _scan_log_for_fatal_markers(log_path)
            status.setdefault(arm, {})[f"gu{idx}"] = {
                "crashed": crashed,
                "error": error,
                "fatal_marker_lines": marker_lines,
                "wall_clock_s": round(time.monotonic() - start, 1),
            }
            RUN_STATUS.write_text(json.dumps(status, indent=2))  # after every run
            print(f"[{arm} / gu{idx}] crashed={crashed} in {status[arm][f'gu{idx}']['wall_clock_s']}s", flush=True)
            if error:
                print(f"    {error[:1500]}", flush=True)


def per_beat_ef(t: np.ndarray, v: np.ndarray, hr_bpm: float) -> np.ndarray:
    """EF for each complete beat in the window: a beat runs from one end-diastolic volume peak to
    the next; EF = (EDV - ESV) / EDV with EDV at the beat's opening peak and ESV the minimum before
    the closing peak. Peaks are local maxima at least 60% of one cardiac period apart, so the
    partial beats at either window edge are dropped rather than estimated."""
    dt = float(np.median(np.diff(t)))
    min_gap = max(1, int(0.6 * (60.0 / hr_bpm) / dt))
    candidates = np.where((v[1:-1] >= v[:-2]) & (v[1:-1] > v[2:]))[0] + 1
    peaks = []
    for i in candidates:
        if peaks and i - peaks[-1] < min_gap:
            if v[i] > v[peaks[-1]]:
                peaks[-1] = i
            continue
        peaks.append(i)
    efs = [(v[a] - v[a:b].min()) / v[a] for a, b in zip(peaks[:-1], peaks[1:])]
    return np.array(efs) * 100.0


def pct_err(twin: float, real: float) -> float:
    return round(100.0 * (twin - real) / real, 1)


def analyze() -> None:
    patients = pd.read_csv(PATIENTS_CSV)
    status = json.loads(RUN_STATUS.read_text())
    knobs = json.loads((OUT_ROOT / "arm_a_knobs.json").read_text())
    rows = []
    for arm in ARMS:
        for p in patients.to_dict("records"):
            idx = int(p["gu_index_1based"])
            s = status[arm][f"gu{idx}"]
            k = knobs[str(idx)]
            row = {
                "arm": arm, "gu_index_1based": idx, "crashed": s["crashed"],
                "fatal_marker_lines": " | ".join(s["fatal_marker_lines"]),
                "real_ef_pct": p["real_ef_pct"], "real_map_mmhg": p["real_map_mmhg"],
                "real_co_l_min": p["real_co_l_min"], "real_hr_bpm": p["real_hr_bpm"],
                "knob_systolic_dysfunction_condition": k["apply_systolic_dysfunction_condition"],
                "knob_stroke_volume_multiplier": k["stroke_volume_multiplier"],
                "knob_systemic_resistance_multiplier": k["systemic_resistance_multiplier"],
                "knob_systemic_compliance_multiplier": k["systemic_compliance_multiplier"],
                "multipliers_reached_pulse": arm == "A_formula",
            }
            if not s["crashed"]:
                df = pd.read_csv(run_dir(arm, idx) / "scenarioResults.csv")
                end = df[COL_TIME].iloc[-1]
                w = df[df[COL_TIME] >= end - ANALYSIS_WINDOW_S]
                hr = w[COL_HR].mean()
                efs = per_beat_ef(w[COL_TIME].to_numpy(), w[COL_LV_VOLUME].to_numpy(), hr)
                twin = {"ef_pct": efs.mean(), "map_mmhg": w[COL_MAP].mean(),
                        "co_l_min": w[COL_CO].mean() / 1000.0, "hr_bpm": hr}
                row.update({
                    "window_start_s": round(end - ANALYSIS_WINDOW_S, 2), "window_end_s": round(end, 2),
                    "twin_ef_pct": round(twin["ef_pct"], 2), "twin_ef_sd_pct": round(efs.std(ddof=1), 3),
                    "twin_ef_n_beats": len(efs),
                    "twin_map_mmhg": round(twin["map_mmhg"], 2),
                    "twin_co_l_min": round(twin["co_l_min"], 3), "twin_hr_bpm": round(twin["hr_bpm"], 2),
                    "err_ef_pct": pct_err(twin["ef_pct"], p["real_ef_pct"]),
                    "err_map_pct": pct_err(twin["map_mmhg"], p["real_map_mmhg"]),
                    "err_co_pct": pct_err(twin["co_l_min"], p["real_co_l_min"]),
                    "err_hr_pct": pct_err(twin["hr_bpm"], p["real_hr_bpm"]),
                })
            rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS_CSV, index=False)
    print(out.drop(columns=["fatal_marker_lines"]).to_string(index=False))


if __name__ == "__main__":
    {"build": build, "run": run, "analyze": analyze}[sys.argv[1]]()
