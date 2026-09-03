"""Continuous-state-sync feature (feature/continuous-state-sync branch): demo seed script.

Advances an existing patient's continuous Pulse state forward by N days against the REAL local
DB (not an isolated temp DB like scripts/verify_continuous_state_pipeline.py) -- run this once
BEFORE a live demo so the demo itself is just clicking through the existing, unmodified frontend
(Patient Dashboard / Trends & History) and pointing at real, pre-seeded escalating risk data,
with zero risk of a live Pulse call failing mid-presentation. Writes real SimulationRun/
RiskAssessment/PulseState rows via src.api.continuous_state_pipeline.run_daily_continuous_pipeline()
-- the same function the (currently unwired) feature itself would call, so this is a real exercise
of the feature, not a separate demo-only code path.

WHY ONE DAY PER SUBPROCESS, NOT AN IN-PROCESS LOOP:
docs/continuous_state_sync_status.md Sec 2.7 spent a full investigation on a segfault eventually
traced (Sec 6.1) to the abandoned SDK path's PulseEngine.initialize_engine(), not actually a
joblib/Pulse fork collision -- but that conclusion rests on the CLI-driver path (this module's own
dependency, src/pulse_runner/cli_state_runner.py) already running PulseScenarioDriver as a plain
subprocess exec per call, never sharing a process with the loaded RandomForest models
(clf.n_jobs=-1/reg.n_jobs=-1, confirmed fork-prone in Sec 2.7's gdb trace) at the OS-process level.
Looping N days in one Python process would still call the classifier N times in that SAME process
that also drives Pulse launches -- reintroducing the exact process-sharing shape Sec 2.7 was
investigating, even though Sec 6.1 later pinned the specific segfault elsewhere. Given a demo has
zero tolerance for a surprise crash, this script pays a small fixed per-day subprocess-launch cost
to stay outside that shape entirely, rather than relying on a root-cause finding that was reached
under different conditions than "call the classifier N times in a row in one process."

Usage (must run inside the Pulse Docker container -- PulseScenarioDriver is a Linux amd64 binary):
    docker exec -e PYTHONPATH=/workspace -w /workspace <pulse-backend-container> \\
        python3 -m scripts.demo_seed_continuous --patient-id <id> --days 4

Requires: patient already exists, has a submitted ClinicalReport, and has a full 21-day wearable
window (same gate run_daily_continuous_pipeline() itself enforces via NotEnoughDataError) -- this
script does not create a patient or seed wearable data; see docs/continuous_state_sync_status.md
Sec 6.5 / this session's own verification for how the demo patient
(1a8f8ea9-ae18-4ad6-be37-ea3349b0a068, acute_deterioration, severity=0.495, empirically verified
safe for at least 4 continuous days) was created.
"""
from __future__ import annotations

import argparse
import subprocess
import sys

WORKER_FLAG = "--_worker-single-day"

# Exit codes, distinguished so a caller (or a human watching a live re-run) can tell failure kinds
# apart at a glance -- not just "it broke".
EXIT_OK = 0
EXIT_FATAL_PULSE = 2
EXIT_NOT_ENOUGH_DATA = 3
EXIT_NO_SUCH_PATIENT = 4
EXIT_UNEXPECTED = 1


def _run_single_day(patient_id: str, day_number: int) -> int:
    """Runs INSIDE the per-day subprocess only (see module docstring). Imports Pulse/DB/classifier
    modules here, not at module top level, so the driver process (which re-execs this file N
    times) never itself imports them."""
    from src.api import models
    from src.api.continuous_state_pipeline import NotEnoughDataError, run_daily_continuous_pipeline
    from src.api.database import SessionLocal
    from src.pulse_runner.cli_state_runner import PulseSdkError

    db = SessionLocal()
    try:
        state = run_daily_continuous_pipeline(patient_id, db)
    except NotEnoughDataError as e:
        print(f"[day {day_number}] NOT ENOUGH DATA: {e}", file=sys.stderr)
        return EXIT_NOT_ENOUGH_DATA
    except ValueError as e:
        print(f"[day {day_number}] NO SUCH PATIENT: {e}", file=sys.stderr)
        return EXIT_NO_SUCH_PATIENT
    except PulseSdkError as e:
        # Covers both a Pulse FATAL marker (e.g. "Can't transport with a negative volume
        # included") and an IrreversibleState event -- src/pulse_runner/cli_state_runner.py's
        # _run_state_scenario() raises this same exception type for both (see that module's
        # docstring for the exact detection logic, including the benign-resume-mismatch filter
        # that does NOT apply here since a real fatal marker is what reaches this except clause).
        print(f"[day {day_number}] PULSE FATAL: {e}", file=sys.stderr)
        return EXIT_FATAL_PULSE
    else:
        run = (
            db.query(models.SimulationRun)
            .filter(models.SimulationRun.patient_id == patient_id)
            .order_by(models.SimulationRun.started_at.desc())
            .first()
        )
        assessment = run.risk_assessment if run else None
        print(
            f"[day {day_number}] scenario={run.scenario_type if run else '?'} "
            f"severity={run.severity:.4f} "
            f"risk_score={assessment.risk_score if assessment else '?'} "
            f"risk_bucket={assessment.risk_bucket if assessment else '?'} "
            f"simulation_time_s={state.simulation_time_s}"
        )
        return EXIT_OK
    finally:
        db.close()


def _run_driver(patient_id: str, days: int) -> int:
    """One subprocess per day, sequential -- a day's crash or bad-data gate stops the sequence
    immediately rather than continuing onto a day whose prior state is now missing/failed."""
    for day_number in range(1, days + 1):
        result = subprocess.run(
            [sys.executable, "-m", "scripts.demo_seed_continuous", "--patient-id", patient_id,
             WORKER_FLAG, "--day-number", str(day_number)],
            cwd="/workspace",
        )
        if result.returncode != 0:
            print(
                f"Aborted at day {day_number}/{days} (exit {result.returncode}) -- "
                f"patient's continuous state is unchanged since the last successful day.",
                file=sys.stderr,
            )
            return result.returncode
    print(f"Done: {days}/{days} days advanced cleanly for patient {patient_id}.")
    return EXIT_OK


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patient-id", required=True)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument(WORKER_FLAG, action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--day-number", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if getattr(args, WORKER_FLAG.lstrip("-").replace("-", "_")):
        return _run_single_day(args.patient_id, args.day_number)
    return _run_driver(args.patient_id, args.days)


if __name__ == "__main__":
    sys.exit(main())
