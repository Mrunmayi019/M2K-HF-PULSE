"""Real-world data validation: replays real heart-failure patient physiological data through the
live API, in place of this project's own synthetic data.

Data source: the PerHeart Pilot Dataset (Kolakowski et al., "Multimodal Dataset of In-Home
Physiological and Inertial Measurements from Older Heart Failure Patients", Data 2026, 11(5):106,
Zenodo 10.5281/zenodo.17143199, CC-licensed) -- 27 real heart-failure patients, ages 67-94,
monitored at home for one month via a pulse oximeter, bathroom scale, and BP cuff. Full dataset
writeup, field mapping, and the license discrepancy this script's LICENSE_NOTE.md addresses are in
docs/real_world_data_integration.md.

What's REAL vs IMPUTED per wearable-sync row (see docs/real_world_data_integration.md for why):
  resting_hr_bpm, spo2_pct, weight_kg  -- REAL, from the dataset's own pulse oximeter / scale
  age, sex                             -- REAL, from personal_questionnaires.csv
  height_cm                            -- IMPUTED (dataset never measured it) -- NHANES sex-mean,
                                           already in src/data_synthesis/reference_stats.yaml
  sleep_hours, hrv_rmssd_ms,
  steps_per_day                        -- IMPUTED (dataset never measured them) -- this project's
                                           own existing wearable_baseline assumed_default means,
                                           held constant (no synthetic noise), not new numbers
  ejection_fraction_pct, nt_probnp_pg_ml -- left null -> the API's existing Tier 1 fallback
                                           (src/api/services.py) fires automatically

Every one of these real patients is aged 67-94, outside Pulse's native 18-65 range
(src/patient_builder/patient_file.py) -- the existing pulse_eligible_age/pulse_eligible_weight_kg
proxy-clamp applies to the whole cohort. Flagged per-patient in results.csv, not hidden.

CONCURRENCY DESIGN (see docs/real_world_data_integration.md §8.2 for the full justification):
Each patient's background pipeline makes 4 real Pulse calls, run SEQUENTIALLY within that one
patient's job (1 current-state + 3 projection horizons -- never concurrent with each other), and
each `PulseScenarioDriver` invocation is single-core-bound (observed ~100% of one core). So running
N patients' pipelines concurrently uses up to N cores at once, no more -- there is no risk of one
patient's own 4 calls fighting each other for CPU. Default concurrency is derived from the backend
container's OWN measured CPU count (`docker exec ... nproc`), not an assumed constant, reserving a
few cores for the backend's event loop / DB / host overhead. All HTTP I/O uses `httpx.AsyncClient`
+ `asyncio` (not a thread pool) since this script's own work is 100% I/O-bound (HTTP calls and
polling waits) -- the actual CPU-bound work happens server-side, inside the container, as
independent OS subprocesses; there is nothing to gain from spawning host-side OS threads for pure
network I/O, and an async event loop is the more efficient primitive for it.

Usage (run from repo root, against the already-running `docker compose` stack):
    python -m scripts.perheart_real_data_replay
        # all eligible patients not already 'complete', full auto-detected concurrency

    python -m scripts.perheart_real_data_replay --limit 2
        # quick smoke test

    python -m scripts.perheart_real_data_replay --resume-from data/real_world_validation/<run>/results.csv
        # skips patients already 'complete' in that file, retries failed/never-attempted ones,
        # and writes a merged, complete combined_results.csv covering all of them at the end
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import pathlib
import subprocess
import time
import zipfile

import httpx
import pandas as pd

from src.patient_builder.patient_file import (
    PULSE_MAX_AGE_YR,
    PULSE_MAX_BMI,
    PULSE_MIN_AGE_YR,
    PULSE_MIN_BMI,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw" / "perheart"
OUT_ROOT = REPO_ROOT / "data" / "real_world_validation"

ZENODO_RECORD = "https://zenodo.org/api/records/17459937/files"
MEDICAL_ZIP_URL = f"{ZENODO_RECORD}/medical.zip/content"
QUESTIONNAIRE_URL = f"{ZENODO_RECORD}/personal_questionnaires.csv/content"

BASE_URL = "http://localhost:8000"
WINDOW_DAYS = 21
BACKEND_CONTAINER = "m2k-hf-pulse-main-pulse-backend-1"
RESERVED_CORES = 3  # headroom for the backend's event loop, Postgres, host OS
FALLBACK_WORKERS = 4  # used if the container's nproc can't be queried
# Raw host CPU count is NOT a safe concurrency predictor for this workload -- empirically
# disproven: `nproc - 3` (9 workers) was tried first and caused systemic failure (5/11 patients
# hit httpx ReadTimeout, 6/11 hit the 180s Pulse timeout on BOTH attempts). Root cause, confirmed
# from the backend's own logs, is more specific than "CPU contention": SQLAlchemy's default
# connection pool (`src/api/database.py`'s `create_engine()` sets no pool_size/max_overflow, so
# SQLAlchemy's defaults apply: pool_size=5 + max_overflow=10 = 15 total connections) was exhausted
# -- `sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached`. Each patient's
# background pipeline (`services.run_assessment_pipeline`) holds ONE DB session open for its
# *entire* multi-minute duration (opened once at the top, closed only at the end, spanning all 4
# Pulse calls) -- a pre-existing architectural characteristic, not something this script
# introduced (methodology.md §8 already flags BackgroundTasks-as-thread-pool as a scaling
# limitation for exactly this reason). 9 concurrently in-flight patients, each holding a
# long-lived connection, plus this script's own bursts of POST/GET calls on top, exceeded the
# 15-connection ceiling. A separately-run 2-worker test completed cleanly with no contention. This
# cap is an empirically-set ceiling (matches src/pulse_runner/batch_runner.py's own independently-
# chosen default of 4), not a formula -- raising the DB pool size itself is shared production
# config, out of scope for this one-off script to change unilaterally (same principle already
# applied to the 180s Pulse timeout, see module docstring).
MAX_SAFE_WORKERS = 2
HTTP_TIMEOUT_S = 60.0  # bumped from 30s after the ReadTimeout failures above
# 4 workers was tried next, after the DB-pool fix above: it eliminated ALL ReadTimeout/harness_error
# failures (confirming the pool-exhaustion diagnosis), but 8/11 patients STILL hit the 180s Pulse
# timeout on both attempts (vs. 0/2 at 2 workers) -- i.e. genuine Pulse-level CPU contention, a
# second, independent bottleneck beyond the DB pool one. This means the Docker Desktop VM's
# reported 12 logical CPUs do not translate to 12 truly independent execution lanes for this
# workload in practice (WSL2/virtualization scheduling overhead, or a Docker Desktop resource
# setting capping usable CPU below what `nproc` reports) -- `nproc`-derived sizing is unreliable
# here for a second, distinct reason from the pool-exhaustion one above. 2 is the only concurrency
# level empirically clean twice over (a standalone 2-patient run and, implicitly, this whole
# escalation's own baseline) -- kept as the ceiling until further, more careful profiling
# (out of scope for this one-off script; a real fix would separately tune the DB pool size and
# actually measure sustained real-parallelism on this host, not assume it from reported core count).
POLL_INTERVAL_S = 10
POLL_TIMEOUT_S = 900  # 15 min ceiling/patient/attempt -- observed calls are 150-700s (§8.1)
MAX_ATTEMPTS_PER_PATIENT = 2  # 1 retry -- timeouts observed to be probabilistic, not deterministic

# Reused, already-cited constants (see docs above) -- never invented for this script.
IMPUTED_SLEEP_HOURS = 7.0
IMPUTED_HRV_RMSSD_MS = 35.0
IMPUTED_STEPS_PER_DAY = 6000.0
HEIGHT_CM_BY_SEX = {"Male": 174.32, "Female": 160.46}  # NHANES means, reference_stats.yaml

LICENSE_NOTE = """\
# License note for this directory

Derived from the PerHeart Pilot Dataset (Kolakowski et al., Data 2026, 11(5):106,
https://doi.org/10.5281/zenodo.17143199).

Zenodo's structured record metadata declares CC-BY 4.0. The dataset's own bundled
`load_dataset.py` (authors' own file) states CC BY-NC-SA 4.0 (Attribution-NonCommercial-
ShareAlike) in its footer -- these two statements disagree, and this was not resolved with the
authors before this analysis. Treating the more restrictive reading as binding:

- This directory's contents (model outputs keyed to the dataset's own existing pseudonymous
  user_id 1-27 -- no new identifying information is introduced) are themselves distributed under
  CC BY-NC-SA 4.0 (https://creativecommons.org/licenses/by-nc-sa/4.0/), consistent with the
  ShareAlike clause under either license reading.
- Non-commercial academic/research use (this paper) is permitted under both readings.
- The raw dataset files themselves are NOT committed to this repository -- see data/raw/ (gitignored)
  and docs/data_provenance.md's "never real patient data in git" rule.
"""


def detect_worker_count(reserved_cores: int = RESERVED_CORES) -> int:
    """CPU-count-derived concurrency, capped at MAX_SAFE_WORKERS -- see that constant's comment
    for why raw core count alone is not a safe predictor here (the backend is a single-process
    FastAPI server, not one process per core). Falls back to FALLBACK_WORKERS if the probe fails."""
    try:
        out = subprocess.run(
            ["docker", "exec", BACKEND_CONTAINER, "nproc"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        nproc = int(out.stdout.strip())
        return min(MAX_SAFE_WORKERS, max(1, nproc - reserved_cores))
    except Exception as e:
        print(f"Could not query {BACKEND_CONTAINER}'s CPU count ({e}); falling back to {FALLBACK_WORKERS} workers.")
        return min(MAX_SAFE_WORKERS, FALLBACK_WORKERS)


def ensure_raw_data() -> tuple[pathlib.Path, pathlib.Path]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    medical_dir = RAW_DIR / "medical"
    if not medical_dir.exists():
        zip_path = RAW_DIR / "medical.zip"
        if not zip_path.exists():
            print(f"Downloading medical.zip from {MEDICAL_ZIP_URL} ...")
            r = httpx.get(MEDICAL_ZIP_URL, follow_redirects=True, timeout=60)
            r.raise_for_status()
            zip_path.write_bytes(r.content)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(RAW_DIR)

    q_path = RAW_DIR / "personal_questionnaires.csv"
    if not q_path.exists():
        print(f"Downloading personal_questionnaires.csv from {QUESTIONNAIRE_URL} ...")
        r = httpx.get(QUESTIONNAIRE_URL, follow_redirects=True, timeout=60)
        r.raise_for_status()
        q_path.write_bytes(r.content)

    return medical_dir, q_path


def load_daily_medical(medical_dir: pathlib.Path) -> pd.DataFrame:
    """One row per (user_id, calendar date) with REAL resting_hr_bpm/spo2_pct/weight_kg -- inner
    join, so a date only counts if both the oximeter and the scale were actually used that day."""
    ox = pd.read_csv(medical_dir / "oxidation.csv")
    ox["user_id"] = ox["user_id"].astype(float).astype(int)
    ox["date"] = pd.to_datetime(ox["ts"], unit="s").dt.date
    ox_daily = (
        ox.groupby(["user_id", "date"])
        .agg(resting_hr_bpm=("hr", "mean"), spo2_pct=("sat", "mean"))
        .reset_index()
    )

    bm = pd.read_csv(medical_dir / "body_mass.csv")
    bm["user_id"] = bm["user_id"].astype(float).astype(int)
    bm["date"] = pd.to_datetime(bm["ts"], unit="s").dt.date
    bm_daily = bm.groupby(["user_id", "date"]).agg(weight_kg=("value", "mean")).reset_index()

    return pd.merge(ox_daily, bm_daily, on=["user_id", "date"], how="inner")


def eligible_patients(daily_df: pd.DataFrame, window_days: int = WINDOW_DAYS) -> list[int]:
    counts = daily_df.groupby("user_id")["date"].nunique()
    return sorted(counts[counts >= window_days].index.tolist())


def latest_window(daily_df: pd.DataFrame, user_id: int, window_days: int = WINDOW_DAYS) -> pd.DataFrame:
    g = daily_df[daily_df.user_id == user_id].sort_values("date")
    return g.tail(window_days).reset_index(drop=True)


def build_wearable_rows(window_df: pd.DataFrame) -> list[dict]:
    return [
        {
            "recorded_date": str(r["date"]),
            "resting_hr_bpm": round(float(r["resting_hr_bpm"]), 1),
            "spo2_pct": round(float(r["spo2_pct"]), 1),
            "weight_kg": round(float(r["weight_kg"]), 1),
            "steps_per_day": IMPUTED_STEPS_PER_DAY,
            "sleep_hours": IMPUTED_SLEEP_HOURS,
            "hrv_rmssd_ms": IMPUTED_HRV_RMSSD_MS,
        }
        for _, r in window_df.iterrows()
    ]


async def _attempt_once(client: httpx.AsyncClient, user_id: int, sex: str, age: float, height_cm: float, weight_kg: float, window_df: pd.DataFrame, mapped_dir: pathlib.Path) -> dict:
    """One end-to-end attempt: create patient, submit report, replay 21 real days, poll to
    completion/failure. Raises on transport-level errors; returns the parsed status dict."""
    r = await client.post("/patients", json={"age": age, "sex": sex, "height_cm": height_cm, "weight_kg": weight_kg})
    r.raise_for_status()
    patient_id = r.json()["id"]

    await client.post(
        f"/patients/{patient_id}/clinical-report",
        json={"ejection_fraction_pct": None, "nt_probnp_pg_ml": None},
    )

    rows = build_wearable_rows(window_df)
    pd.DataFrame(rows).to_csv(mapped_dir / f"user_{user_id}.csv", index=False)

    for row in rows:
        resp = await client.post(f"/patients/{patient_id}/wearable-sync", json=row)
        resp.raise_for_status()

    elapsed = 0
    status = None
    while elapsed < POLL_TIMEOUT_S:
        status = (await client.get(f"/patients/{patient_id}/status")).json()
        if status["simulation_status"] in ("complete", "failed"):
            break
        await asyncio.sleep(POLL_INTERVAL_S)
        elapsed += POLL_INTERVAL_S

    return {"patient_id": patient_id, "status": status}


async def run_one_patient(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    lock: asyncio.Lock,
    user_id: int,
    q_row: pd.Series,
    window_df: pd.DataFrame,
    mapped_dir: pathlib.Path,
    checkpoint_path: pathlib.Path,
) -> dict:
    async with sem:
        sex = "Male" if int(q_row["sex"]) == 1 else "Female"
        age = float(q_row["age"])
        height_cm = HEIGHT_CM_BY_SEX[sex]
        weight_kg = float(window_df["weight_kg"].mean())
        bmi = weight_kg / (height_cm / 100.0) ** 2

        base = {
            "user_id": user_id,
            "age": age,
            "sex": sex,
            "n_real_days": len(window_df),
            "real_date_range": f"{window_df['date'].min()}..{window_df['date'].max()}",
            "pulse_age_capped": not (PULSE_MIN_AGE_YR <= age <= PULSE_MAX_AGE_YR),
            "pulse_bmi_capped": not (PULSE_MIN_BMI <= bmi <= PULSE_MAX_BMI),
        }

        result = None
        for attempt in range(1, MAX_ATTEMPTS_PER_PATIENT + 1):
            started = time.monotonic()
            try:
                outcome = await _attempt_once(client, user_id, sex, age, height_cm, weight_kg, window_df, mapped_dir)
                status = outcome["status"] or {}
                assessment = status.get("latest_assessment") or {}
                result = {
                    **base,
                    "patient_id": outcome["patient_id"],
                    "attempt": attempt,
                    "scenario_type": assessment.get("scenario_type"),
                    "severity": assessment.get("severity"),
                    "risk_score": assessment.get("risk_score"),
                    "risk_bucket": assessment.get("risk_bucket"),
                    "nyha_class": assessment.get("nyha_class"),
                    "deterioration_direction": assessment.get("deterioration_direction"),
                    "simulation_status": status.get("simulation_status", "unknown"),
                    "error_message": status.get("error_message"),
                    "wall_clock_s": round(time.monotonic() - started, 1),
                }
            except Exception as e:  # never let one patient's HTTP error abort the whole batch
                result = {
                    **base,
                    "patient_id": None,
                    "attempt": attempt,
                    "scenario_type": None,
                    "severity": None,
                    "risk_score": None,
                    "risk_bucket": None,
                    "nyha_class": None,
                    "deterioration_direction": None,
                    "simulation_status": "harness_error",
                    "error_message": f"{type(e).__name__}: {e}",
                    "wall_clock_s": round(time.monotonic() - started, 1),
                }

            if result["simulation_status"] == "complete":
                break
            if attempt < MAX_ATTEMPTS_PER_PATIENT:
                print(f"  user_{user_id} attempt {attempt} -> {result['simulation_status']}; retrying...", flush=True)

        print(
            f"  user_{user_id} -> {result['simulation_status']} "
            f"(scenario={result.get('scenario_type')}, risk={result.get('risk_bucket')}, "
            f"attempts={result['attempt']})",
            flush=True,
        )
        async with lock:
            pd.DataFrame([result]).to_csv(checkpoint_path, mode="a", header=not checkpoint_path.exists(), index=False)
        return result


def write_summary(results_df: pd.DataFrame, run_dir: pathlib.Path, filename: str = "summary.md") -> None:
    n = len(results_df)
    completed = results_df[results_df["simulation_status"] == "complete"]
    failed = results_df[results_df["simulation_status"] != "complete"]

    lines = [
        "# PerHeart real-world data validation summary",
        "",
        "Source: PerHeart Pilot Dataset (Kolakowski et al., Data 2026, 11(5):106, "
        "Zenodo 10.5281/zenodo.17143199) -- real heart-failure patients, real pulse-oximeter/"
        "scale readings, real ages 67-94. See docs/real_world_data_integration.md for the full "
        "field-by-field real-vs-imputed breakdown and the Pulse age/BMI-capping caveat below.",
        "",
        f"Patients replayed: {n}",
        f"Completed: {len(completed)}/{n} ({100 * len(completed) / n:.0f}%)" if n else "Completed: 0/0",
        f"Required Pulse age capping (true age outside 18-65): {int(results_df['pulse_age_capped'].sum())}/{n}",
        f"Required Pulse BMI capping (true BMI outside ~16.5-29.5): {int(results_df['pulse_bmi_capped'].sum())}/{n}",
        "",
    ]

    if len(failed):
        cols = [c for c in ["user_id", "simulation_status", "error_message", "attempt"] if c in failed.columns]
        lines += ["## Failures", "", failed[cols].to_string(index=False), ""]

    if len(completed):
        lines += [
            "## Risk bucket distribution (real patients)",
            "",
            completed["risk_bucket"].value_counts().to_string(),
            "",
            "## Scenario type distribution (ML Model 1 classification of real patients)",
            "",
            completed["scenario_type"].value_counts().to_string(),
            "",
            "## Severity / risk score summary",
            "",
            completed[["severity", "risk_score"]].describe().to_string(),
            "",
        ]

    lines += [
        "## Timing",
        "",
        f"Total wall clock (sum across patients, overlapping under concurrency): {results_df['wall_clock_s'].sum():.0f}s",
        f"Mean per patient: {results_df['wall_clock_s'].mean():.1f}s",
    ]

    (run_dir / filename).write_text("\n".join(str(l) for l in lines) + "\n")


async def main_async() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None, help="only replay the first N pending patients (smoke test)")
    parser.add_argument("--out-dir", type=str, default=None)
    parser.add_argument("--workers", type=int, default=None, help="override auto-detected concurrency")
    parser.add_argument("--resume-from", type=str, default=None, help="path to a previous run's results.csv; skips already-'complete' patients, retries the rest, writes a merged combined_results.csv")
    args = parser.parse_args()

    medical_dir, q_path = ensure_raw_data()
    daily_df = load_daily_medical(medical_dir)
    questionnaires = pd.read_csv(q_path).set_index("user_id")

    all_eligible = eligible_patients(daily_df)
    print(f"{len(all_eligible)}/27 real patients have >={WINDOW_DAYS} real overlapping HR+SpO2+weight days: {all_eligible}")

    prior_df = None
    already_complete: set[int] = set()
    if args.resume_from:
        prior_df = pd.read_csv(args.resume_from)
        already_complete = set(prior_df[prior_df["simulation_status"] == "complete"]["user_id"])
        print(f"Resuming from {args.resume_from}: {len(already_complete)} already complete ({sorted(already_complete)}), skipping those.")

    pending = [u for u in all_eligible if u not in already_complete]
    if args.limit:
        pending = pending[: args.limit]
    print(f"Patients to run this pass: {len(pending)} -> {pending}")

    workers = args.workers if args.workers else detect_worker_count()
    print(f"Concurrency: {workers} workers")

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = pathlib.Path(args.out_dir) if args.out_dir else OUT_ROOT / timestamp
    mapped_dir = run_dir / "mapped_readings"
    mapped_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "LICENSE_NOTE.md").write_text(LICENSE_NOTE)

    checkpoint_path = run_dir / "results.csv"
    sem = asyncio.Semaphore(workers)
    lock = asyncio.Lock()

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=HTTP_TIMEOUT_S) as client:
        tasks = [
            run_one_patient(client, sem, lock, user_id, questionnaires.loc[user_id], latest_window(daily_df, user_id), mapped_dir, checkpoint_path)
            for user_id in pending
        ]
        for coro in asyncio.as_completed(tasks):
            await coro

    results_df = pd.read_csv(checkpoint_path) if checkpoint_path.exists() else pd.DataFrame()
    if len(results_df):
        write_summary(results_df, run_dir)
        print(f"\nWrote {checkpoint_path}")
        print(f"Wrote {run_dir / 'summary.md'}")

    if prior_df is not None:
        combined = pd.concat([prior_df[prior_df["simulation_status"] == "complete"], results_df], ignore_index=True)
        combined = combined.drop_duplicates(subset="user_id", keep="last").sort_values("user_id")
        combined.to_csv(run_dir / "combined_results.csv", index=False)
        write_summary(combined, run_dir, filename="combined_summary.md")
        print(f"Wrote {run_dir / 'combined_results.csv'} ({len(combined)} total patients)")
        print(f"Wrote {run_dir / 'combined_summary.md'}")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
