"""Runs a Pulse scenario and returns the results as a DataFrame, with the crash detection
CLAUDE.md flags as missing from the prototype's src/run.py: "must check the log/return code for
failure, not just whether a CSV exists -- a CSV can be present and still represent a
crashed/dead-patient run."

Must be run inside the kitware/pulse Docker container (PulseScenarioDriver only exists there).
"""
from __future__ import annotations

import pathlib
import subprocess
import warnings

import pandas as pd

PULSE_BIN_DIR = "/pulse/bin"
PULSE_DRIVER = f"{PULSE_BIN_DIR}/PulseScenarioDriver"

# Case-insensitive substrings that indicate a crashed/irreversible simulation even when the
# process exits 0 and a CSV was written (Pulse logs these as warnings/errors but doesn't always
# abort the process -- see CLAUDE.md "Known Gotchas").
FATAL_LOG_MARKERS = ("irreversible", "fatal", "[error]")

# How close the CSV's final timestamp must be to the requested total duration to count as a
# complete run, in seconds. A run that stops well short of this likely means the patient died or
# the engine bailed out partway through.
COMPLETENESS_TOLERANCE_S = 2.0


class PulseExecutionError(Exception):
    pass


def _expected_paths(scenario_path: str) -> tuple[pathlib.Path, pathlib.Path]:
    base = str(pathlib.Path(scenario_path).with_suffix(""))
    return pathlib.Path(f"{base}.log"), pathlib.Path(f"{base}Results.csv")


def _scan_log_for_fatal_markers(log_path: pathlib.Path) -> list[str]:
    if not log_path.exists():
        return [f"expected log file not found: {log_path}"]
    hits = []
    for line in log_path.read_text(errors="replace").splitlines():
        if any(marker in line.lower() for marker in FATAL_LOG_MARKERS):
            hits.append(line.strip())
    return hits


def _check_csv_completeness(results_path: pathlib.Path, expected_final_time_s: float) -> pd.DataFrame:
    if not results_path.exists():
        raise PulseExecutionError(f"expected results CSV not found: {results_path}")

    df = pd.read_csv(results_path)
    time_col = next((c for c in df.columns if c.strip().lower().startswith("time")), None)
    if time_col is None:
        raise PulseExecutionError(f"no Time column found in {results_path}; columns={list(df.columns)}")

    if df.empty:
        raise PulseExecutionError(f"results CSV is empty: {results_path}")

    final_time_s = float(df[time_col].iloc[-1])
    if final_time_s < expected_final_time_s - COMPLETENESS_TOLERANCE_S:
        raise PulseExecutionError(
            f"simulation ended early: reached {final_time_s:.2f}s, expected ~{expected_final_time_s:.2f}s "
            f"(likely a crashed/dead-patient run -- check {results_path.with_suffix('.log')})"
        )
    return df


def run_pulse(scenario_path: str, expected_duration_s: float, timeout_sec: int = 120) -> pd.DataFrame:
    """Runs PulseScenarioDriver on scenario_path and returns the parsed results DataFrame.

    `expected_duration_s` is the total simulated time the scenario requests (sum of all
    AdvanceTime actions) -- used for the completeness check, since a crashed run can still leave
    behind a syntactically valid but truncated CSV.

    Raises PulseExecutionError on nonzero exit, timeout, fatal log markers, or a truncated run.
    """
    log_path, results_path = _expected_paths(scenario_path)

    try:
        result = subprocess.run(
            [PULSE_DRIVER, scenario_path],
            cwd=PULSE_BIN_DIR,
            timeout=timeout_sec,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as e:
        raise PulseExecutionError(f"PulseScenarioDriver timed out after {timeout_sec}s on {scenario_path}") from e

    if result.returncode != 0:
        raise PulseExecutionError(
            f"PulseScenarioDriver exited {result.returncode} on {scenario_path}\nstderr: {result.stderr[-2000:]}"
        )

    fatal_hits = _scan_log_for_fatal_markers(log_path)
    if fatal_hits:
        raise PulseExecutionError(
            f"fatal marker(s) found in {log_path} despite exit code 0:\n" + "\n".join(fatal_hits[:10])
        )

    return _check_csv_completeness(results_path, expected_duration_s)


# ---------------------------------------------------------------------------------------------
# Crash-zone pre-flight guardrail, added 2026-09-10 (Sprint 2, docs/methodology.md Sec 8).
# Reuses the exact documented range from the BCG validation work
# (scripts/synthetic_deterioration_pulse_check.py's KNOWN_CRASH_RANGE) rather than
# reimplementing it -- promoted here so production code (src/api/services.py,
# src/analytics/projection.py) can share the same check instead of each guessing independently.
#
# Empirical basis: docs/methodology.md Sec 5/7 (Phase 4 batch validation, 150 synthetic patients):
# acute_deterioration crashes/times out ~40% of the time (12/30) above severity ~0.6, with no
# clean upper recovery observed through 0.85. Independently re-confirmed in
# docs/synthetic_deterioration_stress_test.md: 4 of 8 representative real-patient-anchored points
# failed, exactly the ones at/above this range (severity 0.635-0.878).
#
# cardiac_stress has its OWN, different documented threshold (~0.45+, no characterized upper
# bound, docs/methodology.md Sec 5/7) -- NOT covered by this constant. Extend
# is_known_unstable_configuration() below if that scenario type needs the same guardrail; not
# done here since this sprint's evidence base is specifically acute_deterioration.
ACUTE_DETERIORATION_CRASH_RANGE = (0.6, 0.85)


def is_known_unstable_configuration(scenario_type: str, severity: float) -> bool:
    """True if this (scenario_type, severity) combination falls in a documented Pulse
    engine-instability zone -- i.e. a run here is a known-unreliable data point EVEN IF it
    happens to succeed (the 4/8 failure rate in the crash zone means a "lucky" pass isn't
    evidence the configuration is actually stable). Only acute_deterioration is characterized
    here; every other scenario type returns False (not "confirmed stable" -- simply not audited
    for this specific guardrail yet).
    """
    if scenario_type == "acute_deterioration":
        return ACUTE_DETERIORATION_CRASH_RANGE[0] <= severity <= ACUTE_DETERIORATION_CRASH_RANGE[1]
    return False


def run_pulse_with_preflight(
    scenario_path: str,
    scenario_type: str,
    severity: float,
    expected_duration_s: float,
    timeout_sec: int = 120,
    skip_if_unstable: bool = False,
) -> dict:
    """Wraps run_pulse() with the crash-zone pre-flight guardrail. run_pulse() itself is
    deliberately unchanged (it's used by many existing, already-tested call sites) -- this is an
    additive wrapper, not a modification.

    Never silently skips a run the caller expected: by default (`skip_if_unstable=False`) this
    WARNS (via the `warnings` module, category `RuntimeWarning`) and then runs anyway, exactly as
    it would without this wrapper -- flagging, not refusing. Pass `skip_if_unstable=True`
    explicitly to instead skip the run entirely when the configuration is flagged (the caller
    must opt in; it is never the default).

    Critically, `flagged_unstable` (and the derived `simulation_status`, see
    `score_reporting.determine_simulation_status()`) is set based on the PRE-FLIGHT check alone,
    independent of whether the run actually succeeds -- a successful run inside the documented
    crash zone is still not a reliable data point (see module comment above), so a "lucky" pass
    must not be reported as equivalent to a run outside the zone.

    Returns {"df": DataFrame|None, "pulse_attempted": bool, "pulse_succeeded": bool,
    "flagged_unstable": bool, "error": str|None}.
    """
    flagged = is_known_unstable_configuration(scenario_type, severity)
    if flagged:
        warnings.warn(
            f"Entering known-unstable Pulse configuration: scenario_type={scenario_type!r}, "
            f"severity={severity:.3f} is inside the documented acute_deterioration crash zone "
            f"{ACUTE_DETERIORATION_CRASH_RANGE} (docs/methodology.md Sec 5/7; independently "
            f"re-confirmed at 4/8 failures in docs/synthetic_deterioration_stress_test.md). A "
            f"successful run here is still not a reliable data point.",
            RuntimeWarning,
            stacklevel=2,
        )
        if skip_if_unstable:
            return {
                "df": None,
                "pulse_attempted": False,
                "pulse_succeeded": False,
                "flagged_unstable": True,
                "error": "skipped: known-unstable configuration (skip_if_unstable=True)",
            }

    try:
        df = run_pulse(scenario_path, expected_duration_s, timeout_sec)
        return {"df": df, "pulse_attempted": True, "pulse_succeeded": True, "flagged_unstable": flagged, "error": None}
    except PulseExecutionError as e:
        return {"df": None, "pulse_attempted": True, "pulse_succeeded": False, "flagged_unstable": flagged, "error": str(e)}
