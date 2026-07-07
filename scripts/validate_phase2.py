"""Phase 2 validation driver: runs one real Pulse simulation per locked scenario type and prints
a before/after summary for manual physiological sanity-checking.

Must run INSIDE the Pulse Docker container (see CLAUDE.md for the docker run command), from
/workspace as the working directory:

    python3 -m scripts.validate_phase2
"""
import json
import pathlib

import pandas as pd

from src.data_synthesis.generate_patients import generate_patients, SCENARIO_EF_PROFILE
from src.patient_builder.patient_file import build_patient_file
from src.patient_builder.scenario_file import DATA_REQUESTS, STABILIZATION_S, build_scenario_file
from src.pulse_runner.runner import PulseExecutionError, run_pulse

SCENARIOS_DIR = pathlib.Path("/workspace/scenarios")
DURATION_MIN = 10.0


def main():
    SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    patients = generate_patients(n=200, seed=99)

    results = {}
    for scenario_type in SCENARIO_EF_PROFILE.keys():
        patient = patients[patients["scenario_type"] == scenario_type].iloc[0]
        print(f"\n=== {scenario_type} (patient {patient['patient_id']}, EF={patient['ejection_fraction_pct']}, severity={patient['severity']}) ===")

        patient_path = SCENARIOS_DIR / f"patient_{scenario_type}.json"
        scenario_path = SCENARIOS_DIR / f"scenario_{scenario_type}.json"

        patient_path.write_text(json.dumps(build_patient_file(patient), indent=2))
        scenario = build_scenario_file(
            patient_json_path=str(patient_path),
            scenario_type=scenario_type,
            severity=float(patient["severity"]),
            ejection_fraction_pct=float(patient["ejection_fraction_pct"]),
            duration_min=DURATION_MIN,
        )
        scenario_path.write_text(json.dumps(scenario, indent=2))

        expected_duration_s = STABILIZATION_S + DURATION_MIN * 60
        try:
            df = run_pulse(str(scenario_path), expected_duration_s=expected_duration_s, timeout_sec=180)
        except PulseExecutionError as e:
            print(f"FAILED: {e}")
            results[scenario_type] = {"status": "failed", "error": str(e)}
            continue

        first, last = df.iloc[0], df.iloc[-1]
        summary = {c: {"start": first[c], "end": last[c]} for c in df.columns if c.strip().lower() != "time(s)"}
        print(pd.DataFrame(summary).T.to_string())
        results[scenario_type] = {"status": "ok", "summary": summary}

    print("\n\n=== OVERALL ===")
    for scenario_type, r in results.items():
        print(f"{scenario_type}: {r['status']}")


if __name__ == "__main__":
    main()
