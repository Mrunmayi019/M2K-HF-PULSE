"""Standalone verification script (not committed to the repo; scratch-dir-outside-repo precedent
from docs/pulse_state_serialization_investigation.md not followed here only because it needs to
run inside the container mount -- delete after use, matching that doc's convention).

Re-verifies the CardiovascularMechanicsModification-reissue-on-resume fix at the CLI/
PulseScenarioDriver layer (src/pulse_runner/cli_state_runner.py), with the same rigor as the
original SDK-layer investigation in docs/continuous_state_sync_status.md Sec 2.4/2.5:
  1. Determinism control: run the continuous (uninterrupted) scenario twice, confirm identical.
  2. Drift check: split + resume WITHOUT reissuing CVMod -- expect drift vs. continuous.
  3. Fix check: split + resume WITH reissue (via the real production cli_state_runner functions)
     -- expect a bit-for-bit (or extremely close) match vs. continuous.

Patient/EF/severity mirror the original SDK-layer test exactly (P0000-equivalent, EF=56.4,
severity=0.46) for direct comparability.
"""
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, "/workspace")

from src.patient_builder import scenario_file
from src.patient_builder.patient_file import build_patient_file, ef_to_cardiovascular_modifiers
from src.pulse_runner.cli_state_runner import run_initial, resume_and_advance
from src.pulse_runner.runner import PULSE_BIN_DIR, PULSE_DRIVER

WORK = pathlib.Path("/workspace/scenarios/cli_verify_work")
WORK.mkdir(parents=True, exist_ok=True)

EF = 56.4
SEVERITY = 0.46
STAB_S = 60.0
LEG_S = 90.0  # each of the two 90s legs -> split point at 150s, final at 240s

patient_path = WORK / "patient.json"
patient_path.write_text(json.dumps(build_patient_file({
    "patient_id": "P_CLI_VERIFY", "sex": "Male", "age": 58, "height_cm": 175.0, "weight_kg": 82.0,
})))


def run_driver(scenario: dict, name: str) -> tuple[int, str]:
    path = WORK / f"{name}.json"
    path.write_text(json.dumps(scenario, indent=2))
    result = subprocess.run([PULSE_DRIVER, str(path)], cwd=PULSE_BIN_DIR,
                             capture_output=True, text=True, timeout=300)
    return result.returncode, (result.stdout + result.stderr)


def read_final_row(name: str) -> dict:
    import pandas as pd
    df = pd.read_csv(WORK / f"{name}Results.csv")
    row = df.iloc[-1]
    time_col = next(c for c in df.columns if c.strip().lower().startswith("time"))
    hr_col = next(c for c in df.columns if "heartrate" in c.lower())
    map_col = next(c for c in df.columns if "meanarterialpressure" in c.lower())
    co_col = next(c for c in df.columns if "cardiacoutput" in c.lower())
    sv_col = next(c for c in df.columns if "heartstrokevolume" in c.lower())
    return {"t": row[time_col], "hr": row[hr_col], "map": row[map_col],
            "co": row[co_col], "sv": row[sv_col]}


def cvmod_action():
    modifiers = ef_to_cardiovascular_modifiers(EF, SEVERITY)
    return scenario_file._cardiovascular_modification_action(modifiers, extra={})


def build_continuous_scenario() -> dict:
    return {
        "Scenario": {
            "PatientConfiguration": {"PatientFile": str(patient_path)},
            "DataRequestManager": {"DataRequest": scenario_file.DATA_REQUESTS},
            "AnyAction": [
                {"AdvanceTime": {"Time": {"ScalarTime": {"Value": STAB_S, "Unit": "s"}}}},
                cvmod_action(),
                {"AdvanceTime": {"Time": {"ScalarTime": {"Value": LEG_S * 2, "Unit": "s"}}}},
            ],
        }
    }


def build_split_save_scenario(state_out: pathlib.Path) -> dict:
    return {
        "Scenario": {
            "PatientConfiguration": {"PatientFile": str(patient_path)},
            "DataRequestManager": {"DataRequest": scenario_file.DATA_REQUESTS},
            "AnyAction": [
                {"AdvanceTime": {"Time": {"ScalarTime": {"Value": STAB_S, "Unit": "s"}}}},
                cvmod_action(),
                {"AdvanceTime": {"Time": {"ScalarTime": {"Value": LEG_S, "Unit": "s"}}}},
                {"SerializeState": {"Mode": "Save", "Filename": str(state_out)}},
            ],
        }
    }


def build_resume_no_reissue_scenario(state_in: pathlib.Path) -> dict:
    return {
        "Scenario": {
            "EngineStateFile": str(state_in),
            "DataRequestManager": {"DataRequest": scenario_file.DATA_REQUESTS},
            "AnyAction": [
                {"AdvanceTime": {"Time": {"ScalarTime": {"Value": LEG_S, "Unit": "s"}}}},
            ],
        }
    }


results = {}

print("=== 1. Determinism control: continuous run x2 ===", flush=True)
rc, err = run_driver(build_continuous_scenario(), "continuous_a")
print("continuous_a exit:", rc, err[-500:] if rc else "")
rc, err = run_driver(build_continuous_scenario(), "continuous_b")
print("continuous_b exit:", rc, err[-500:] if rc else "")
a = read_final_row("continuous_a")
b = read_final_row("continuous_b")
print("continuous_a final:", a)
print("continuous_b final:", b)
results["determinism_exact_match"] = (a == b)

print("\n=== 2. Split + save at t=150s ===", flush=True)
state_path = WORK / "state_saved.json"
rc, err = run_driver(build_split_save_scenario(state_path), "split_save")
print("split_save exit:", rc, err[-1000:] if rc else "")
print("state file exists:", state_path.exists(), "size:", state_path.stat().st_size if state_path.exists() else None)

print("\n=== 3. Resume WITHOUT reissue (expect drift vs continuous) ===", flush=True)
rc, err = run_driver(build_resume_no_reissue_scenario(state_path), "resume_no_reissue")
print("resume_no_reissue exit:", rc, err[-1000:] if rc else "")
no_reissue_final = read_final_row("resume_no_reissue")
print("no_reissue final:", no_reissue_final)
drift_hr_pct = abs(no_reissue_final["hr"] - a["hr"]) / a["hr"] * 100
drift_co_pct = abs(no_reissue_final["co"] - a["co"]) / a["co"] * 100
print(f"drift: HR {drift_hr_pct:.3f}%  CO {drift_co_pct:.3f}%")
results["no_reissue_drift_present"] = (drift_hr_pct > 0.5 or drift_co_pct > 0.5)

print("\n=== 4. Resume WITH reissue via PRODUCTION cli_state_runner (expect exact match) ===", flush=True)
try:
    new_state_json, snap = resume_and_advance(
        state_json=state_path.read_text(),
        ejection_fraction_pct=EF,
        severity=SEVERITY,
        duration_s=LEG_S,
        prior_offset_s=STAB_S + LEG_S,
        scenario_type=None,
    )
    print("resume_and_advance snapshot:", snap)
    hr_diff_pct = abs(snap["heart_rate"] - a["hr"]) / a["hr"] * 100
    co_diff_pct = abs(snap["cardiac_output"] - a["co"]) / a["co"] * 100
    map_diff_pct = abs(snap["map"] - a["map"]) / a["map"] * 100
    sv_diff_pct = abs(snap["stroke_volume"] - a["sv"]) / a["sv"] * 100
    print(f"vs continuous: HR {hr_diff_pct:.6f}%  MAP {map_diff_pct:.6f}%  "
          f"CO {co_diff_pct:.6f}%  SV {sv_diff_pct:.6f}%")
    results["reissue_matches_continuous"] = all(
        d < 0.01 for d in (hr_diff_pct, co_diff_pct, map_diff_pct, sv_diff_pct)
    )
    results["reissue_call_succeeded"] = True
except Exception as e:
    print("resume_and_advance FAILED:", type(e).__name__, e)
    results["reissue_call_succeeded"] = False
    results["reissue_matches_continuous"] = False

print("\n=== VERDICT ===")
for k, v in results.items():
    print(f"  [{'PASS' if v else 'FAIL'}] {k}")
print("\nOVERALL:", "PASS" if all(results.values()) else "FAIL")
