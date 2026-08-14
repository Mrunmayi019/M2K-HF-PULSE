"""Phase 5: forward projection via incremental severity re-simulation.

`project_severity()` is pure math (no Docker needed). `project_physiology()` actually re-runs
Pulse at each projected severity -- same category as Phase 4's batch runner, and reuses its exact
per-patient build/run/extract steps (src/patient_builder/, src/pulse_runner/runner.py,
src/analytics/simulation_features.py) rather than reimplementing them, only replacing the fixed
"patient's own severity" with a projected one per horizon.
"""
from __future__ import annotations

import json
import pathlib

from src.analytics.risk_score import compute_risk_score
from src.analytics.simulation_features import analyze_simulation
from src.patient_builder.patient_file import build_patient_file
from src.patient_builder.scenario_file import STABILIZATION_S, build_scenario_file
from src.pulse_runner.runner import PulseExecutionError, run_pulse

DEFAULT_HORIZONS_DAYS = (7, 14, 30)
DEFAULT_OUTPUT_DIR = pathlib.Path("/workspace/scenarios/projection")


def project_severity(current_severity: float, deterioration_rate_per_day: float, horizon_days: int) -> float:
    """Linear extrapolation of severity forward `horizon_days`, clamped to [0, 1].

    `deterioration_rate_per_day` is in risk_score-equivalent units/day (see
    src/analytics/deterioration_rate.py's `SD_RATE_TO_RISK_SCORE_PER_DAY` for how a wearable-trend
    composite rate is converted to this same scale) -- severity and risk_score share the same 0-1
    range by construction (see data_synthesis/generate_patients.py's severity assignment), so a
    risk_score-equivalent daily rate is used directly to project severity forward too.
    """
    projected = current_severity + deterioration_rate_per_day * horizon_days
    return max(0.0, min(projected, 1.0))


def _run_at_severity(
    patient: dict, scenario_type: str, severity: float, output_dir: pathlib.Path, duration_min: float
) -> dict:
    """One build+run+extract+score cycle at a given severity -- the same steps
    src/pulse_runner/batch_runner.py's `_run_one` performs, parameterized by a projected severity
    instead of the patient's stored one."""
    patient_id = patient["patient_id"]
    ejection_fraction_pct = float(patient["ejection_fraction_pct"])

    output_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{patient_id}_sev{severity:.3f}"
    patient_path = output_dir / f"patient_{tag}.json"
    scenario_path = output_dir / f"scenario_{tag}.json"

    patient_path.write_text(json.dumps(build_patient_file(patient), indent=2))
    scenario = build_scenario_file(
        patient_json_path=str(patient_path),
        scenario_type=scenario_type,
        severity=severity,
        ejection_fraction_pct=ejection_fraction_pct,
        duration_min=duration_min,
    )
    scenario_path.write_text(json.dumps(scenario, indent=2))

    expected_duration_s = STABILIZATION_S + duration_min * 60
    try:
        df = run_pulse(str(scenario_path), expected_duration_s=expected_duration_s, timeout_sec=180)
    except PulseExecutionError as e:
        return {"status": "failed", "error": str(e)}

    features = analyze_simulation(df)
    risk = compute_risk_score(
        hr_rise=features["hr_rise"],
        map_drop=features["map_drop"],
        co_drop_pct=features["co_drop_pct"],
        compensation_flag=features["compensation_flag"],
        instability_flag=features["instability_flag"],
        map_start=features["map_start"],
    )
    return {"status": "ok", **features, **risk}


def project_physiology(
    patient: dict,
    scenario_type: str,
    current_severity: float,
    deterioration_rate_per_day: float,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS_DAYS,
    output_dir: pathlib.Path = DEFAULT_OUTPUT_DIR,
    duration_min: float = 10.0,
) -> dict:
    """Requires Docker (run_pulse() needs PulseScenarioDriver). For each horizon: projects
    severity, re-simulates via Pulse, extracts features, and scores risk. Returns
    {horizon_days: {projected_severity, **run_result}}.
    """
    results = {}
    for horizon_days in horizons:
        projected_severity = project_severity(current_severity, deterioration_rate_per_day, horizon_days)
        run_result = _run_at_severity(patient, scenario_type, projected_severity, output_dir, duration_min)
        results[horizon_days] = {"projected_severity": projected_severity, **run_result}
    return results
