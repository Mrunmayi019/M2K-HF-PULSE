"""Re-derives acute_score/baseline_deficit_score for row 1's three projection horizons --
these aren't persisted to the DB (only risk_score/risk_bucket/status are), so this re-runs
project_physiology()'s own _run_at_severity() at the exact severities already stored in row 1's
projection_json, same patient. Not new test data -- same deterministic computation, just
inspecting intermediate values that were already computed once and discarded.
"""
import sys
sys.path.insert(0, "/workspace")

from src.analytics.projection import _run_at_severity

patient = {
    "patient_id": "7693f167-c7ae-4f4f-bd59-18e8bb119a7a",
    "sex": "Female", "age": 68, "height_cm": 162.0, "weight_kg": 78.0,
    "ejection_fraction_pct": 32.0,
}

# Exact projected_severity values already stored in row 1's projection_json
horizons = {7: 0.9462041161616167, 14: 0.9841782323232328, 30: 1.0}

for horizon, severity in horizons.items():
    result = _run_at_severity(
        patient=patient, scenario_type="fluid_overload", severity=severity,
        output_dir=__import__("pathlib").Path("/workspace/scenarios/check_projection_components"),
        duration_min=10.0,
    )
    print(f"horizon={horizon} severity={severity:.6f} status={result.get('status')} "
          f"acute_score={result.get('acute_score')} "
          f"baseline_deficit_score={result.get('baseline_deficit_score')} "
          f"risk_score={result.get('risk_score')} map_start={result.get('map_start')} "
          f"hr_rise={result.get('hr_rise')} map_drop={result.get('map_drop')} "
          f"co_drop_pct={result.get('co_drop_pct')}")
