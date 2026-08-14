"""Re-validation of the nyha_ordinal fix (see docs/methodology.md Sec 9,
docs/real_world_data_integration.md Sec 8.2): replays a stratified sample of SYNTHETIC patients
(known ground-truth severity, unlike the real PerHeart cohort) through the live, already-fixed
API, using the same proven-reliable infrastructure and 2-worker empirically-safe concurrency as
scripts/perheart_real_data_replay.py -- not the standalone kitware/pulse:4.3.1 image, which was
observed to time out on every call in this environment regardless of scenario type (an unrelated,
pre-existing environment issue, not something introduced by the fix).

Directly computes live severity MAE against real ground truth, the same comparison Phase 8 (real
mode) makes -- gives an apples-to-apples number against the documented 0.271 pre-fix baseline.

Expanded for publication rigor (PUBLICATION_TODO.md P1 "Expand statistical rigor on the small
samples"): default n_per_scenario raised from 1 (the original 5-patient run) to 6 (30 patients),
converted from a sequential httpx.Client loop to the same async/semaphore-bounded concurrency
pattern as the PerHeart replay (2 workers max -- see that script's MAX_SAFE_WORKERS comment for
why this ceiling is empirical, not assumed), and bootstrap 95% CIs added for both severity MAE and
scenario accuracy instead of point estimates alone.

Usage: python -m scripts.nyha_fix_live_revalidation [n_per_scenario]
    python -m scripts.nyha_fix_live_revalidation 6   # 30 patients total (6 per scenario type)
"""
from __future__ import annotations

import asyncio
import datetime
import pathlib
import sys
import time

import httpx
import numpy as np
import pandas as pd

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE_URL = "http://localhost:8000"
WINDOW_DAYS = 21
MAX_SAFE_WORKERS = 2  # matches scripts/perheart_real_data_replay.py's empirically-derived ceiling
HTTP_TIMEOUT_S = 60.0
POLL_INTERVAL_S = 10
POLL_TIMEOUT_S = 900
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 42

n_per_scenario = int(sys.argv[1]) if len(sys.argv) > 1 else 6


def bootstrap_ci(values: np.ndarray, statistic_fn, n_resamples: int = N_BOOTSTRAP, seed: int = BOOTSTRAP_SEED) -> tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    n = len(values)
    point = statistic_fn(values)
    boot_stats = np.empty(n_resamples)
    for i in range(n_resamples):
        resample_idx = rng.integers(0, n, size=n)
        boot_stats[i] = statistic_fn(values[resample_idx])
    lo, hi = np.percentile(boot_stats, [2.5, 97.5])
    return point, lo, hi


async def run_one_patient(client: httpx.AsyncClient, sem: asyncio.Semaphore, lock: asyncio.Lock, patient: pd.Series, wearable_df: pd.DataFrame, checkpoint_path: pathlib.Path) -> dict:
    async with sem:
        pid_label = patient["patient_id"]
        started = time.monotonic()
        print(f"=== {pid_label} ({patient['scenario_type']}, true severity={patient['severity']:.3f}) ===", flush=True)

        rows = (
            wearable_df[wearable_df["patient_id"] == pid_label]
            .sort_values("day")
            .head(WINDOW_DAYS)
            .to_dict("records")
        )
        result = {
            "patient_id": pid_label,
            "true_scenario_type": patient["scenario_type"],
            "true_severity": float(patient["severity"]),
            "predicted_scenario_type": None,
            "predicted_severity": None,
            "severity_abs_error": None,
            "simulation_status": "skipped_insufficient_wearable_rows",
            "wall_clock_s": 0.0,
            "error_message": None,  # present on every row from the start -- a later row adding a
            # key the checkpoint CSV's header (fixed by the first row written) doesn't have
            # corrupts the file for a subsequent pd.read_csv (this bit an actual run: harness_error
            # rows added this key only in the except branch, producing a ragged CSV).
        }
        if len(rows) < WINDOW_DAYS:
            print(f"  SKIP {pid_label}: only {len(rows)} wearable rows", flush=True)
            async with lock:
                pd.DataFrame([result]).to_csv(checkpoint_path, mode="a", header=not checkpoint_path.exists(), index=False)
            return result

        try:
            r = await client.post("/patients", json={
                "age": int(round(patient["age"])),
                "sex": patient["sex"],
                "height_cm": float(patient["height_cm"]),
                "weight_kg": float(patient["weight_kg"]),
            })
            r.raise_for_status()
            api_id = r.json()["id"]

            resp = await client.post(f"/patients/{api_id}/clinical-report", json={
                "ejection_fraction_pct": float(patient["ejection_fraction_pct"]),
                "nt_probnp_pg_ml": float(patient["nt_probnp_pg_ml"]),
            })
            resp.raise_for_status()

            start_date = datetime.date.today() - datetime.timedelta(days=WINDOW_DAYS)
            for i, row in enumerate(rows):
                resp = await client.post(f"/patients/{api_id}/wearable-sync", json={
                    "recorded_date": str(start_date + datetime.timedelta(days=i)),
                    "resting_hr_bpm": row["resting_hr_bpm"],
                    "spo2_pct": row["spo2_pct"],
                    "weight_kg": row["weight_kg"],
                    "steps_per_day": row["steps_per_day"],
                    "sleep_hours": row["sleep_hours"],
                    "hrv_rmssd_ms": row["hrv_rmssd_ms"],
                })
                resp.raise_for_status()

            elapsed = 0
            status = None
            while elapsed < POLL_TIMEOUT_S:
                status = (await client.get(f"/patients/{api_id}/status")).json()
                if status["simulation_status"] in ("complete", "failed"):
                    break
                await asyncio.sleep(POLL_INTERVAL_S)
                elapsed += POLL_INTERVAL_S

            assessment = (status or {}).get("latest_assessment") or {}
            pred_severity = assessment.get("severity")
            true_severity = float(patient["severity"])
            result.update({
                "predicted_scenario_type": assessment.get("scenario_type"),
                "predicted_severity": pred_severity,
                "severity_abs_error": abs(pred_severity - true_severity) if pred_severity is not None else None,
                "simulation_status": (status or {}).get("simulation_status", "unknown"),
                "wall_clock_s": round(time.monotonic() - started, 1),
            })
        except Exception as e:  # never let one patient's HTTP error abort the whole batch
            result.update({
                "simulation_status": "harness_error",
                "error_message": f"{type(e).__name__}: {e}",
                "wall_clock_s": round(time.monotonic() - started, 1),
            })

        print(
            f"  -> {pid_label}: {result['simulation_status']}, predicted severity={result['predicted_severity']}, "
            f"abs_error={result['severity_abs_error']}",
            flush=True,
        )
        async with lock:
            pd.DataFrame([result]).to_csv(checkpoint_path, mode="a", header=not checkpoint_path.exists(), index=False)
        return result


async def main_async() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--resume-from", type=str, default=None, help="path to a previous run's results.csv; skips already-'complete' patients, retries the rest, writes a merged combined_results.csv")
    args, _ = parser.parse_known_args()

    patients_df = pd.read_csv(REPO_ROOT / "data/synthetic/patients.csv")
    wearable_df = pd.read_csv(REPO_ROOT / "data/synthetic/wearable_trends.csv")

    sample = (
        patients_df.groupby("scenario_type", group_keys=False)
        .sample(n=n_per_scenario, random_state=99)
        .reset_index(drop=True)
    )

    prior_df = None
    already_complete: set[str] = set()
    if args.resume_from:
        prior_df = pd.read_csv(args.resume_from)
        already_complete = set(prior_df[prior_df["simulation_status"] == "complete"]["patient_id"])
        print(f"Resuming from {args.resume_from}: {len(already_complete)} already complete, skipping those.")
        sample = sample[~sample["patient_id"].isin(already_complete)].reset_index(drop=True)

    print(f"Patients to run this pass: {len(sample)} (of {n_per_scenario * 5} total sampled), concurrency={MAX_SAFE_WORKERS}")

    out_dir = REPO_ROOT / "data" / "validation_runs" / datetime.datetime.now().strftime("%Y%m%d_%H%M%S_nyha_fix_revalidation")
    out_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = out_dir / "results.csv"
    sem = asyncio.Semaphore(MAX_SAFE_WORKERS)
    lock = asyncio.Lock()

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=HTTP_TIMEOUT_S) as client:
        tasks = [
            run_one_patient(client, sem, lock, patient, wearable_df, checkpoint_path)
            for _, patient in sample.iterrows()
        ]
        for coro in asyncio.as_completed(tasks):
            await coro

    results_df = pd.read_csv(checkpoint_path) if checkpoint_path.exists() else pd.DataFrame()

    if prior_df is not None:
        combined = pd.concat([prior_df[prior_df["simulation_status"] == "complete"], results_df], ignore_index=True)
        combined = combined.drop_duplicates(subset="patient_id", keep="last").sort_values("patient_id")
        combined.to_csv(out_dir / "combined_results.csv", index=False)
        print(f"Wrote {out_dir / 'combined_results.csv'} ({len(combined)} total patients)")
        results_df = combined
    print("\n\n=== SUMMARY ===")
    print(results_df.to_string(index=False))

    completed = results_df[results_df.simulation_status == "complete"]
    if len(completed):
        mae_values = completed["severity_abs_error"].to_numpy()
        mae_point, mae_lo, mae_hi = bootstrap_ci(mae_values, np.mean)

        acc_flags = (completed["predicted_scenario_type"] == completed["true_scenario_type"]).to_numpy().astype(float)
        acc_point, acc_lo, acc_hi = bootstrap_ci(acc_flags, np.mean)

        print(f"\nCompleted: {len(completed)}/{len(results_df)}")
        print(f"Live severity MAE (post-fix): {mae_point:.4f}  [95% bootstrap CI {mae_lo:.4f}, {mae_hi:.4f}]  (n={len(completed)}, 2000 resamples)")
        print(f"Live scenario accuracy (post-fix): {acc_point:.4f}  [95% bootstrap CI {acc_lo:.4f}, {acc_hi:.4f}]")
        print("Compare against: 0.048 offline MAE (this session's retrain), 0.271 live pre-fix (Phase 8, methodology.md Sec 7/8)")

        summary_lines = [
            "# nyha_ordinal fix -- expanded live re-validation summary",
            "",
            f"Sample: {len(sample)} synthetic patients ({n_per_scenario} per scenario type, known ground truth), "
            f"replayed through the live, fixed API at {MAX_SAFE_WORKERS}-worker concurrency.",
            f"Completed: {len(completed)}/{len(results_df)}",
            "",
            f"Live severity MAE (post-fix): {mae_point:.4f}  [95% bootstrap CI {mae_lo:.4f}, {mae_hi:.4f}]",
            f"Live scenario accuracy (post-fix): {acc_point:.4f}  [95% bootstrap CI {acc_lo:.4f}, {acc_hi:.4f}]",
            "",
            "Compare against: 0.048 offline severity MAE (this session's retrain), "
            "0.271 live severity MAE pre-fix (Phase 8, docs/methodology.md Sec 7/8).",
        ]
        (out_dir / "summary.md").write_text("\n".join(summary_lines) + "\n")
        print(f"\nWrote {out_dir / 'summary.md'}")

    results_df.to_csv(out_dir / "results.csv", index=False)
    print(f"Wrote {out_dir / 'results.csv'}")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
