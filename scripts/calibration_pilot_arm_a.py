"""Calibration pilot, Step 4: Arm A baselines for the Gu et al. pilot patients.

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

Three modes, because Pulse only exists inside the container but the analysis uses the host venv.
build/run take optional `--set original|consistent` and `--arms A_prod [A_formula]` filters, so
adding patients doesn't rebuild or rerun runs that already exist:
  1. host:      ./venv/Scripts/python.exe -m scripts.calibration_pilot_arm_a build [filters]
  2. container: MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd)":/workspace -w /workspace \
                  kitware/pulse:4.3.1 bash -c "pip3 install -q pandas && python3 -m scripts.calibration_pilot_arm_a run [filters]"
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


def _cli_filters() -> tuple[tuple[str, ...], str | None]:
    args = sys.argv[2:]
    arms = ARMS
    if "--arms" in args:
        i = args.index("--arms") + 1
        arms = tuple(a for a in args[i:] if not a.startswith("--"))
    set_name = args[args.index("--set") + 1] if "--set" in args else None
    return arms, set_name


def _selected_patients(set_name: str | None) -> pd.DataFrame:
    patients = pd.read_csv(PATIENTS_CSV)
    if set_name is not None:
        patients = patients[patients["set"] == set_name]
    return patients


def build() -> None:
    arms, set_name = _cli_filters()
    knobs_path = OUT_ROOT / "arm_a_knobs.json"
    knobs = json.loads(knobs_path.read_text()) if knobs_path.exists() else {}
    for p in _selected_patients(set_name).to_dict("records"):
        idx = int(p["gu_index_1based"])
        patient = {"patient_id": f"gu{idx}", "sex": p["sex"], "age": p["age"],
                   "height_cm": p["height_cm"], "weight_kg": p["weight_kg"]}
        modifiers = ef_to_cardiovascular_modifiers(p["real_ef_pct"], SEVERITY)
        knobs[str(idx)] = modifiers
        for arm in arms:
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
    knobs_path.write_text(json.dumps(knobs, indent=2))
    print(json.dumps(knobs, indent=2))


def run_one(scenario_path: pathlib.Path, expected_duration_s: float) -> dict:
    """One run through the unchanged run_pulse(): crash flag plus the exact log lines that matched
    runner.FATAL_LOG_MARKERS (empty when none did)."""
    from src.pulse_runner.runner import PulseExecutionError, _scan_log_for_fatal_markers, run_pulse

    start = time.monotonic()
    try:
        run_pulse(str(scenario_path), expected_duration_s=expected_duration_s, timeout_sec=TIMEOUT_SEC)
        crashed, error = False, None
    except PulseExecutionError as e:
        crashed, error = True, str(e)
    return {
        "crashed": crashed,
        "error": error,
        "fatal_marker_lines": _scan_log_for_fatal_markers(scenario_path.with_suffix(".log")),
        "wall_clock_s": round(time.monotonic() - start, 1),
    }


def run() -> None:
    arms, set_name = _cli_filters()
    patients = _selected_patients(set_name)
    status = json.loads(RUN_STATUS.read_text()) if RUN_STATUS.exists() else {}
    for arm in arms:
        for idx in patients["gu_index_1based"]:
            scenario_path = run_dir(arm, int(idx)).resolve() / "scenario.json"
            print(f"[{arm} / gu{idx}] running ...", flush=True)
            result = run_one(scenario_path, EXPECTED_DURATION_S)
            status.setdefault(arm, {})[f"gu{idx}"] = result
            RUN_STATUS.write_text(json.dumps(status, indent=2))  # after every run
            print(f"[{arm} / gu{idx}] crashed={result['crashed']} in {result['wall_clock_s']}s", flush=True)
            if result["error"]:
                print(f"    {result['error'][:1500]}", flush=True)


def per_beat_volumes(t: np.ndarray, v: np.ndarray, hr_bpm: float) -> tuple[np.ndarray, np.ndarray]:
    """(EDV, ESV) for each complete beat in the window: a beat runs from one end-diastolic volume
    peak to the next, with EDV at the beat's opening peak and ESV the minimum before the closing
    peak. Peaks are local maxima at least 60% of one cardiac period apart, so the partial beats at
    either window edge are dropped rather than estimated."""
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
    edv = np.array([v[a] for a in peaks[:-1]])
    esv = np.array([v[a:b].min() for a, b in zip(peaks[:-1], peaks[1:])])
    return edv, esv


def window_metrics(df: pd.DataFrame, start_s: float, end_s: float) -> dict:
    """Twin metrics over [start_s, end_s]: EF/EDV/ESV per complete beat (mean, plus EF SD), and
    MAP/CO/HR as time means. SV = CO / HR (Amendment 1 b)."""
    w = df[(df[COL_TIME] >= start_s) & (df[COL_TIME] <= end_s)]
    hr = w[COL_HR].mean()
    edv, esv = per_beat_volumes(w[COL_TIME].to_numpy(), w[COL_LV_VOLUME].to_numpy(), hr)
    efs = (edv - esv) / edv * 100.0
    co = w[COL_CO].mean() / 1000.0
    return {
        "ef_pct": efs.mean(), "ef_sd_pct": efs.std(ddof=1), "n_beats": len(efs),
        "edv_ml": edv.mean(), "esv_ml": esv.mean(), "sv_ml": co * 1000.0 / hr,
        "map_mmhg": w[COL_MAP].mean(), "co_l_min": co, "hr_bpm": hr,
    }


def pct_err(twin: float, real: float) -> float:
    return round(100.0 * (twin - real) / real, 1)


def analyze() -> None:
    patients = pd.read_csv(PATIENTS_CSV).set_index("gu_index_1based")
    status = json.loads(RUN_STATUS.read_text())
    knobs = json.loads((OUT_ROOT / "arm_a_knobs.json").read_text())
    rows = []
    for arm in ARMS:
        for key, s in status.get(arm, {}).items():
            idx = int(key.removeprefix("gu"))
            p = patients.loc[idx]
            k = knobs[str(idx)]
            real_sv_td = p["real_co_l_min"] * 1000.0 / p["real_hr_bpm"]
            real_sv_fick = p["real_co_fick_l_min"] * 1000.0 / p["real_hr_bpm"]
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
                "set": p["set"], "real_mri_ef_pct": p["real_mri_ef_pct"],
                "real_co_fick_l_min": p["real_co_fick_l_min"],
                "real_sv_td_ml": round(real_sv_td, 2), "real_sv_fick_ml": round(real_sv_fick, 2),
            }
            if not s["crashed"]:
                df = pd.read_csv(run_dir(arm, idx) / "scenarioResults.csv")
                end = df[COL_TIME].iloc[-1]
                m = window_metrics(df, end - ANALYSIS_WINDOW_S, end)
                row.update({
                    "window_start_s": round(end - ANALYSIS_WINDOW_S, 2), "window_end_s": round(end, 2),
                    "twin_ef_pct": round(m["ef_pct"], 2), "twin_ef_sd_pct": round(m["ef_sd_pct"], 3),
                    "twin_ef_n_beats": m["n_beats"],
                    "twin_map_mmhg": round(m["map_mmhg"], 2),
                    "twin_co_l_min": round(m["co_l_min"], 3), "twin_hr_bpm": round(m["hr_bpm"], 2),
                    "err_ef_pct": pct_err(m["ef_pct"], p["real_ef_pct"]),
                    "err_map_pct": pct_err(m["map_mmhg"], p["real_map_mmhg"]),
                    "err_co_pct": pct_err(m["co_l_min"], p["real_co_l_min"]),
                    "err_hr_pct": pct_err(m["hr_bpm"], p["real_hr_bpm"]),
                    "twin_edv_ml": round(m["edv_ml"], 2), "twin_esv_ml": round(m["esv_ml"], 2),
                    "twin_sv_ml": round(m["sv_ml"], 2),
                    "err_co_fick_pct": pct_err(m["co_l_min"], p["real_co_fick_l_min"]),
                    "err_sv_td_pct": pct_err(m["sv_ml"], real_sv_td),
                    "err_sv_fick_pct": pct_err(m["sv_ml"], real_sv_fick),
                })
            rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS_CSV, index=False)
    print(out.drop(columns=["fatal_marker_lines"]).to_string(index=False))


if __name__ == "__main__":
    {"build": build, "run": run, "analyze": analyze}[sys.argv[1]]()
