import json, pathlib, shutil, subprocess, sys, time
sys.path.insert(0, "/workspace")
from src.patient_builder import scenario_file
from src.patient_builder.patient_file import ef_to_cardiovascular_modifiers
from src.pulse_runner.runner import PULSE_BIN_DIR, PULSE_DRIVER
OUT = pathlib.Path("/out"); W = pathlib.Path("/tmp/w"); W.mkdir(exist_ok=True)
d = json.loads((OUT / "P08s48_state14.json").read_text())
acts = d["ActiveActions"]["AnyAction"]
print("active actions before:", [list(a.get("PatientAction", a).keys()) for a in acts], flush=True)
d["ActiveActions"]["AnyAction"] = [a for a in acts if "Exercise" not in a.get("PatientAction", {})]
print("after:", [list(a.get("PatientAction", a).keys()) for a in d["ActiveActions"]["AnyAction"]], flush=True)
st = W / "noex.json"; st.write_text(json.dumps(d))
cv = scenario_file._cardiovascular_modification_action(ef_to_cardiovascular_modifiers(65.0, 0.549083333333334), extra={})
scn = {"Scenario": {"EngineStateFile": str(st), "DataRequestManager": {"DataRequest": scenario_file.DATA_REQUESTS},
       "AnyAction": [cv, {"AdvanceTime": {"Time": {"ScalarTime": {"Value": 1200, "Unit": "s"}}}}]}}
p = W / "F_exercise_deleted_from_state.json"; p.write_text(json.dumps(scn))
r = subprocess.run([PULSE_DRIVER, str(p)], cwd=PULSE_BIN_DIR, capture_output=True, text=True, timeout=3000)
for suf in ("Results.csv", ".log"):
    s = W / f"F_exercise_deleted_from_state{suf}"
    if s.exists(): shutil.copy(s, OUT / s.name)
print("F exit", r.returncode, flush=True)
