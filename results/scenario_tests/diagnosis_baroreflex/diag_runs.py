"""Diagnosis of the low-HR/low-MAP state: runs inside the backend image, repo at /workspace (ro), files at /out."""
import json, pathlib, shutil, subprocess, sys, time
sys.path.insert(0, "/workspace")
from src.patient_builder import scenario_file
from src.patient_builder.patient_file import ef_to_cardiovascular_modifiers
from src.pulse_runner.runner import PULSE_BIN_DIR, PULSE_DRIVER
OUT = pathlib.Path("/out"); W = pathlib.Path("/tmp/w"); W.mkdir(exist_ok=True)
adv = lambda s: {"AdvanceTime": {"Time": {"ScalarTime": {"Value": s, "Unit": "s"}}}}
dr = {"DataRequest": scenario_file.DATA_REQUESTS}
cv = lambda ef, sev: scenario_file._cardiovascular_modification_action(ef_to_cardiovascular_modifiers(ef, sev), extra={})
ex = scenario_file._exercise_action

def state_file(src, name, map_baseline=None):
    d = json.loads((OUT / src).read_text())
    if map_baseline is not None:
        d["CurrentPatient"]["MeanArterialPressureBaseline"]["ScalarPressure"]["Value"] = map_baseline
    p = W / name; p.write_text(json.dumps(d)); return str(p)

def drive(state, actions, name):
    scn = {"Scenario": {"EngineStateFile": state, "DataRequestManager": dr, "AnyAction": actions}}
    p = W / f"{name}.json"; p.write_text(json.dumps(scn)); t = time.time()
    r = subprocess.run([PULSE_DRIVER, str(p)], cwd=PULSE_BIN_DIR, capture_output=True, text=True, timeout=3000)
    for suf in ("Results.csv", ".log"):
        s = W / f"{name}{suf}"
        if s.exists(): shutil.copy(s, OUT / s.name)
    print(name, "exit", r.returncode, f"{time.time()-t:.0f}s", flush=True)

init = json.loads((OUT / "P08s48_state14.json").read_text())["InitialPatient"]["MeanArterialPressureBaseline"]["ScalarPressure"]["Value"]
print("initial MAP baseline", init, flush=True)
EF, SEV13 = 65.0, 0.549083333333334
s = state_file("P08s48_state14.json", "stuck.json")
drive(s, [cv(EF, SEV13), adv(1200)], "A_stuck_asis")
drive(s, [cv(EF, SEV13), ex(0.0), adv(1200)], "B_stuck_exercise_off")
r = state_file("P08s48_state14.json", "restored.json", map_baseline=init)
drive(r, [cv(EF, SEV13), adv(1200)], "C_baseline_restored")
drive(r, [cv(EF, SEV13), ex(0.0), adv(1200)], "D_baseline_restored_exercise_off")
# exertion replay from the healthy day-8 state (day 9: cardiac_stress, severity 0.289 -> intensity 0.289)
drive(state_file("P08s48_state9.json", "pre.json"), [cv(EF, 0.289216666666667), ex(0.289), adv(1800)], "E_exertion_from_day8")
print("done", flush=True)
