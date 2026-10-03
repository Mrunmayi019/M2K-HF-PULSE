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

from src.analytics.deterioration_rate import SD_RATE_TO_SEVERITY_PER_DAY
from src.analytics.risk_score import compute_risk_score
from src.analytics.simulation_features import analyze_simulation
from src.patient_builder.patient_file import build_patient_file
from src.patient_builder.scenario_file import STABILIZATION_S, build_scenario_file
from src.pulse_runner.runner import run_pulse_with_preflight

DEFAULT_HORIZONS_DAYS = (7, 14, 30)
DEFAULT_OUTPUT_DIR = pathlib.Path("/workspace/scenarios/projection")


def project_severity(current_severity: float, composite_rate: float, horizon_days: int) -> float:
    """Linear extrapolation of severity forward `horizon_days`, clamped to [0, 1].

    FIXED 2026-09-10 (see docs/methodology.md Sec 8, "severity and risk_score are not on
    comparable scales" -- now marked resolved there). This function previously took a rate
    pre-converted via `SD_RATE_TO_RISK_SCORE_PER_DAY` (risk_score's own scale conversion) and
    applied it directly to `current_severity` (a different scale) -- confirmed as a real bug on
    the real 117-row Phase 4 dataset: risk_score's floor for acute_deterioration (0.491) sits
    above severity's own mean (0.385), so a rate calibrated for risk_score does not move severity
    at the rate it was actually calibrated for.

    Fixed the same way `deterioration_rate.days_to_next_stage()` already handles the equivalent
    risk_score case: this function now takes the raw, scale-agnostic `composite_rate`
    (population-SD-equivalents/day, from `compute_deterioration_rate()`) and does its OWN
    conversion internally via `SD_RATE_TO_SEVERITY_PER_DAY` -- a constant scoped specifically to
    severity, independent of `SD_RATE_TO_RISK_SCORE_PER_DAY`. This is a structural fix (a caller
    can no longer accidentally pass the wrong pre-converted rate, the same mistake that caused the
    original bug) -- it does NOT mean the numeric conversion itself is now validated:
    `SD_RATE_TO_SEVERITY_PER_DAY` is still an unvalidated placeholder (same status as its
    risk_score counterpart) pending real severity-trajectory calibration data, which this project
    does not have. Deliberately NOT fused with risk_score's own projection (see
    `docs/methodology.md` Sec 8's "blocked on data" note) -- the two are projected independently.
    """
    severity_rate_per_day = composite_rate * SD_RATE_TO_SEVERITY_PER_DAY
    projected = current_severity + severity_rate_per_day * horizon_days
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
    # run_pulse_with_preflight() (Sprint 2, docs/methodology.md Sec 8): warns before running if
    # (scenario_type, severity) is in the documented crash zone -- projected severities are just
    # as likely to land there as a patient's own, so this guardrail applies here too, not just
    # the initial assessment. Still runs by default (never silently skips).
    pulse_result = run_pulse_with_preflight(
        str(scenario_path), scenario_type, severity, expected_duration_s=expected_duration_s, timeout_sec=180
    )
    if not pulse_result["pulse_succeeded"]:
        return {"status": "failed", "error": pulse_result["error"]}

    features = analyze_simulation(pulse_result["df"])
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
    composite_rate: float,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS_DAYS,
    output_dir: pathlib.Path = DEFAULT_OUTPUT_DIR,
    duration_min: float = 10.0,
) -> dict:
    """Requires Docker (run_pulse() needs PulseScenarioDriver). For each horizon: projects
    severity, re-simulates via Pulse, extracts features, and scores risk. Returns
    {horizon_days: {projected_severity, **run_result}}.

    `composite_rate` is the raw, scale-agnostic population-SD-equivalents/day rate from
    `compute_deterioration_rate()` -- pass it through unconverted (same convention as
    `deterioration_rate.days_to_next_stage()`); `project_severity()` below applies its own
    severity-scoped conversion. Do not pre-convert this via `SD_RATE_TO_RISK_SCORE_PER_DAY` before
    calling this function -- that was the bug fixed 2026-09-10 (docs/methodology.md Sec 8).
    """
    results = {}
    for horizon_days in horizons:
        projected_severity = project_severity(current_severity, composite_rate, horizon_days)
        run_result = _run_at_severity(patient, scenario_type, projected_severity, output_dir, duration_min)
        results[horizon_days] = {"projected_severity": projected_severity, **run_result}
    return results
