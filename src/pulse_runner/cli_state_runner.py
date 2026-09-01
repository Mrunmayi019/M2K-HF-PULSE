"""Continuous-state-sync feature (feature/continuous-state-sync branch): runs
PulseScenarioDriver against the save/resume scenarios built by
src/pulse_runner/cli_state_scenario.py, with resume-aware crash detection.

Supersedes src/pulse_runner/sdk_runner.py (see that module's docstring, and
cli_state_scenario.py's docstring, for why the SDK path was abandoned: a 100%-reproducible native
segfault in PulseEngine.initialize_engine() itself, unrelated to scikit-learn/joblib).

Deliberately reuses src/pulse_runner/runner.py's private helpers (_expected_paths,
_scan_log_for_fatal_markers, _check_csv_completeness) and constants (PULSE_BIN_DIR, PULSE_DRIVER,
COMPLETENESS_TOLERANCE_S) rather than re-deriving the same log/CSV parsing logic -- that module
backs the existing, working, from-scratch pipeline (src/api/services.py) and is NOT modified here;
importing from it is read-only reuse, not a dependency in the other direction.

THE ONE NEW PIECE OF CRASH-DETECTION LOGIC (see docs/pulse_state_serialization_investigation.md
"A real gotcha for the future feature"): a resumed PulseScenarioDriver run exits 1 and logs
`[ERROR] [<t>(s)] !!!! Simulation time does not equal expected end time !!!!` even on a completely
correct resume, because the driver's own internal consistency check compares the final time only
against *this scenario's own* AdvanceTime sum, not the state file's already-elapsed clock.
_filter_benign_resume_mismatch() swallows ONLY this exact message, and ONLY when its own logged
time matches our independently-computed expected absolute final time (prior elapsed offset + this
scenario's requested duration) -- any other fatal marker, or a mismatched time, still raises. This
is deliberately narrow: it must not mask a genuine, different-cause failure that happens to also
produce an "[ERROR]"-tagged line.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import tempfile

from src.analytics.simulation_features import _COLUMN_SUBSTRINGS, _pick_column
from src.pulse_runner import runner as _runner
from src.pulse_runner.cli_state_scenario import build_initial_scenario, build_resume_scenario
from src.pulse_runner.runner import (
    COMPLETENESS_TOLERANCE_S,
    PULSE_BIN_DIR,
    PULSE_DRIVER,
    PulseExecutionError,
)

# Public name kept stable for src/api/continuous_state_pipeline.py's `except PulseSdkError` --
# a plain alias, not a subclass, so callers written against either name see the same exception.
PulseSdkError = PulseExecutionError

_BENIGN_RESUME_MISMATCH_RE = re.compile(
    r"\[(?P<time>[\d.]+)\(s\)\].*simulation time does not equal expected end time", re.IGNORECASE
)

DEFAULT_TIMEOUT_S = 300


def _filter_benign_resume_mismatch(fatal_hits: list[str], expected_final_time_s: float) -> list[str]:
    remaining = []
    for hit in fatal_hits:
        m = _BENIGN_RESUME_MISMATCH_RE.search(hit)
        if m and abs(float(m.group("time")) - expected_final_time_s) < COMPLETENESS_TOLERANCE_S:
            continue
        remaining.append(hit)
    return remaining


def _run_state_scenario(
    scenario: dict,
    scenario_path: pathlib.Path,
    expected_final_time_s: float,
    is_resume: bool,
    timeout_sec: int,
):
    scenario_path.write_text(json.dumps(scenario, indent=2))
    log_path, results_path = _runner._expected_paths(str(scenario_path))

    try:
        result = subprocess.run(
            [PULSE_DRIVER, str(scenario_path)],
            cwd=PULSE_BIN_DIR,
            timeout=timeout_sec,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as e:
        raise PulseExecutionError(
            f"PulseScenarioDriver timed out after {timeout_sec}s on {scenario_path}"
        ) from e

    fatal_hits = _runner._scan_log_for_fatal_markers(log_path)
    if is_resume:
        fatal_hits = _filter_benign_resume_mismatch(fatal_hits, expected_final_time_s)

    if result.returncode != 0:
        # A resumed run legitimately exits 1 on nothing but the known benign
        # "expected end time" false positive (see module docstring) -- once that specific hit is
        # filtered out above, an empty fatal_hits list on a resume means this exit code is that
        # known false positive, not a real failure. Any other nonzero exit (including a resume
        # with OTHER fatal markers still present) still raises.
        if not (is_resume and not fatal_hits):
            raise PulseExecutionError(
                f"PulseScenarioDriver exited {result.returncode} on {scenario_path}\n"
                f"stderr: {result.stderr[-2000:]}\nunfiltered fatal markers: {fatal_hits[:10]}"
            )
    elif fatal_hits:
        raise PulseExecutionError(
            f"fatal marker(s) found in {log_path} despite exit code 0:\n" + "\n".join(fatal_hits[:10])
        )

    return _runner._check_csv_completeness(results_path, expected_final_time_s)


def _snapshot_from_df(df) -> dict:
    time_col = next((c for c in df.columns if c.strip().lower().startswith("time")), None)
    last = df.iloc[-1]
    return {
        "simulation_time_s": float(last[time_col]),
        "heart_rate": float(last[_pick_column(df, _COLUMN_SUBSTRINGS["heart_rate"])]),
        "map": float(last[_pick_column(df, _COLUMN_SUBSTRINGS["map"])]),
        "cardiac_output": float(last[_pick_column(df, _COLUMN_SUBSTRINGS["cardiac_output"])]),
        "stroke_volume": float(last[_pick_column(df, _COLUMN_SUBSTRINGS["stroke_volume"])]),
    }


def run_initial(
    patient_json_path: str,
    ejection_fraction_pct: float,
    severity: float,
    stabilization_s: float,
    duration_s: float,
    timeout_sec: int = DEFAULT_TIMEOUT_S,
) -> tuple[str, dict, "pd.DataFrame"]:
    """First-ever run for a patient. Returns (state_json_str, snapshot, df) -- `df` is this
    encounter's full raw Pulse output (stabilize + CVMod + advance), the same shape
    src.pulse_runner.runner.run_pulse() returns, so src.analytics.simulation_features.
    analyze_simulation()/extract_waveform_data() work on it unchanged -- lets
    src/api/continuous_state_pipeline.py produce a real SimulationRun/RiskAssessment via the exact
    same analytics code src/api/services.py already uses, instead of a separate code path.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        state_out = pathlib.Path(tmp_dir) / "state_out.json"
        scenario = build_initial_scenario(
            patient_json_path=patient_json_path,
            ejection_fraction_pct=ejection_fraction_pct,
            severity=severity,
            stabilization_s=stabilization_s,
            duration_s=duration_s,
            state_out_path=str(state_out),
        )
        expected_final = stabilization_s + duration_s
        df = _run_state_scenario(
            scenario, pathlib.Path(tmp_dir) / "scenario.json", expected_final,
            is_resume=False, timeout_sec=timeout_sec,
        )
        if not state_out.exists():
            raise PulseExecutionError(f"SerializeState did not produce {state_out}")
        return state_out.read_text(), _snapshot_from_df(df), df


def resume_and_advance(
    state_json: str,
    ejection_fraction_pct: float,
    severity: float,
    duration_s: float,
    prior_offset_s: float,
    scenario_type: str | None = None,
    timeout_sec: int = DEFAULT_TIMEOUT_S,
) -> tuple[str, dict, "pd.DataFrame"]:
    """Resumes from state_json (the previously-saved state's raw file content, as returned by a
    prior run_initial()/resume_and_advance() call), reissues CardiovascularMechanicsModification,
    applies today's Exercise action if scenario_type calls for one, advances, and re-saves.
    Returns (new_state_json_str, snapshot, df) -- see run_initial()'s docstring for why `df` (this
    encounter's raw Pulse output -- here just the reissue/Exercise/advance window, NOT including
    the initial stabilization, since that already happened on a prior day) is returned.

    `prior_offset_s` is the absolute simulation time already elapsed before this call (the prior
    call's own returned snapshot["simulation_time_s"]) -- required to compute the correct expected
    absolute final time for both the completeness check and the benign-resume-mismatch filter (see
    module docstring); NOT optional the way it might look from sdk_runner.py's old signature,
    which never needed it since the SDK has no such false-positive check.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        state_in = pathlib.Path(tmp_dir) / "state_in.json"
        state_in.write_text(state_json)
        state_out = pathlib.Path(tmp_dir) / "state_out.json"
        scenario = build_resume_scenario(
            state_in_path=str(state_in),
            ejection_fraction_pct=ejection_fraction_pct,
            severity=severity,
            duration_s=duration_s,
            scenario_type=scenario_type,
            state_out_path=str(state_out),
        )
        expected_final = prior_offset_s + duration_s
        df = _run_state_scenario(
            scenario, pathlib.Path(tmp_dir) / "scenario.json", expected_final,
            is_resume=True, timeout_sec=timeout_sec,
        )
        if not state_out.exists():
            raise PulseExecutionError(f"SerializeState did not produce {state_out}")
        return state_out.read_text(), _snapshot_from_df(df), df
