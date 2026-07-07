"""Runs a Pulse scenario and returns the results as a DataFrame, with the crash detection
CLAUDE.md flags as missing from the prototype's src/run.py: "must check the log/return code for
failure, not just whether a CSV exists -- a CSV can be present and still represent a
crashed/dead-patient run."

Must be run inside the kitware/pulse Docker container (PulseScenarioDriver only exists there).
"""
from __future__ import annotations

import pathlib
import subprocess

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
