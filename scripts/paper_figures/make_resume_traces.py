"""Regenerate the Pulse traces behind the paper's state-resume figure (Fig. resume).

Runs three 240 s encounters for one patient (EF 56.4, severity 0.46, the same settings as
scripts/diagnostics/cli_verify_reissue.py and the original SDK-layer check in
docs/continuous_state_sync_status.md):

  resume_continuous    stabilize 60 s, apply the disease modifier, advance 180 s (reference)
  resume_no_reissue    same patient saved at 150 s, reloaded and advanced 90 s with no modifier
  resume_with_reissue  the same saved state resumed through the production path,
                       src.pulse_runner.cli_state_runner.resume_and_advance (modifier re-issued)

Each is written as <name>Results.csv, the format scripts/paper_figures/make_journal_figures.py
reads with --engine-dir. Needs the Pulse engine, so run it inside the backend image from the
repo root:

  docker compose run --rm --no-deps -v "$PWD:/workspace" pulse-backend \
      python scripts/paper_figures/make_resume_traces.py --out /workspace/results/paper_figures/engine_traces
"""
import argparse
import json
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, "/workspace")

from src.patient_builder import scenario_file  # noqa: E402
from src.patient_builder.patient_file import build_patient_file, ef_to_cardiovascular_modifiers  # noqa: E402
from src.pulse_runner.cli_state_runner import resume_and_advance  # noqa: E402
from src.pulse_runner.runner import PULSE_BIN_DIR, PULSE_DRIVER  # noqa: E402

EF = 56.4
SEVERITY = 0.46
STAB_S = 60.0
LEG_S = 90.0  # two 90 s legs: state saved at 150 s, run ends at 240 s

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
OUT = pathlib.Path(ap.parse_args().out)
OUT.mkdir(parents=True, exist_ok=True)
WORK = OUT / "_work"
WORK.mkdir(exist_ok=True)

patient_path = WORK / "patient.json"
patient_path.write_text(json.dumps(build_patient_file({
    "patient_id": "P_CLI_VERIFY", "sex": "Male", "age": 58, "height_cm": 175.0, "weight_kg": 82.0,
})))


def cvmod_action():
    return scenario_file._cardiovascular_modification_action(ef_to_cardiovascular_modifiers(EF, SEVERITY), extra={})


def advance(seconds):
    return {"AdvanceTime": {"Time": {"ScalarTime": {"Value": seconds, "Unit": "s"}}}}


def run_driver(name, scenario):
    path = WORK / f"{name}.json"
    path.write_text(json.dumps({"Scenario": scenario}, indent=2))
    res = subprocess.run([PULSE_DRIVER, str(path)], cwd=PULSE_BIN_DIR, capture_output=True, text=True, timeout=900)
    produced = WORK / f"{name}Results.csv"
    if not produced.exists():
        sys.exit(f"{name}: no results file (exit {res.returncode})\n{res.stderr[-2000:]}")
    return produced


requests = {"DataRequestManager": {"DataRequest": scenario_file.DATA_REQUESTS}}
patient = {"PatientConfiguration": {"PatientFile": str(patient_path)}}

# 1. Uninterrupted reference.
csv = run_driver("resume_continuous", {**patient, **requests,
                 "AnyAction": [advance(STAB_S), cvmod_action(), advance(2 * LEG_S)]})
shutil.copy(csv, OUT / "resume_continuousResults.csv")

# 2. Same run, saved at 150 s.
state = WORK / "state_150s.json"
run_driver("split_save", {**patient, **requests,
           "AnyAction": [advance(STAB_S), cvmod_action(), advance(LEG_S),
                         {"SerializeState": {"Mode": "Save", "Filename": str(state)}}]})

# 3. Reload without re-issuing the modifier.
csv = run_driver("resume_no_reissue", {"EngineStateFile": str(state), **requests, "AnyAction": [advance(LEG_S)]})
shutil.copy(csv, OUT / "resume_no_reissueResults.csv")

# 4. Reload through the production path, which re-issues the modifier.
_, snap, df = resume_and_advance(state_json=state.read_text(), ejection_fraction_pct=EF, severity=SEVERITY,
                                 duration_s=LEG_S, prior_offset_s=STAB_S + LEG_S, scenario_type=None)
df.to_csv(OUT / "resume_with_reissueResults.csv", index=False)

shutil.rmtree(WORK)
print("final snapshot, re-issued:", snap)
print("traces written to", OUT)
