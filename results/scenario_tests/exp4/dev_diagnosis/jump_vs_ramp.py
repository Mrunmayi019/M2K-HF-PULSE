"""Dev diagnosis (not Experiment 4 data): does starting a fresh P06-like twin directly at severity
0.78 collapse it, and does a ramp avoid that? Usage: python jump_vs_ramp.py A|B|C"""
import json, sys, tempfile, pathlib
from src.patient_builder.patient_file import build_patient_file
from src.pulse_runner.cli_state_runner import run_initial, resume_and_advance
from src.analytics.simulation_features import analyze_simulation
EF, DUR = 63.0, 600.0
mode = sys.argv[1]
plan = {"A": [0.78] + [0.75] * 6,
        "B": [0.06, 0.20, 0.40, 0.60, 0.78] + [0.75] * 6,
        "C": [0.06] * 7}[mode]
tmp = pathlib.Path(tempfile.mkdtemp())
p = tmp / "patient.json"
p.write_text(json.dumps(build_patient_file({"sex": "Male", "age": 60, "height_cm": 180.0, "weight_kg": 100.0})))
state, snap, df = run_initial(patient_json_path=str(p), ejection_fraction_pct=EF, severity=plan[0], stabilization_s=60, duration_s=DUR)
def show(i, sev, df):
    f = analyze_simulation(df)
    print(f"{mode} step {i} sev={sev:.2f} HR {f['hr_start']:.1f}->{f['hr_end']:.1f} MAP {f['map_start']:.1f}->{f['map_end']:.1f}", flush=True)
show(0, plan[0], df)
for i, sev in enumerate(plan[1:], 1):
    state, snap, df = resume_and_advance(state_json=state, ejection_fraction_pct=EF, severity=sev, duration_s=DUR,
                                         prior_offset_s=snap["simulation_time_s"], scenario_type="deconditioning")
    show(i, sev, df)
print(mode, "DONE", flush=True)
