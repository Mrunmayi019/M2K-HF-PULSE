# Integration pre-results: `integrate/pre-results`

Branch `integrate/pre-results`, created off `main` at `8efd1f3` on 2026-10-02, to produce a frozen,
verified system version for results-section scenario testing. Team decision: `fix/unstable-alert-
fallback` (classifier-fallback alerting when Pulse is unstable) is part of the final system.

## 1. Branches merged

| Merge | Commit | Brings in |
|---|---|---|
| `origin/fix/unstable-alert-fallback` | `d71fdab` (merge commit) | Tip `702efd9` -- a rebased copy of `feature/continuous-state-sync` (`1ffeaac`, `21b9353`, `cb7dff6`) + `feature/real-outcome-validation`'s `ab795a9`, `928b23f` + its own two alert-fallback commits (`a239970`, `702efd9`) |
| `origin/feature/real-outcome-validation` | `f4223a2` (merge commit) | Tip `1bc5ec7` -- only the one commit not already in the branch above (a HANDOFF.md edit) |

Both merges were clean (`git merge --no-ff`), zero conflicts -- SQLAlchemy auto-merged
`docs/methodology.md`, `src/api/models.py`, `src/api/schemas.py`, `src/api/services.py`,
`tests/test_api.py` with no manual intervention. `copilot/*` branches were out of scope per
instruction (`copilot/show-md-files-in-preview-mode` was already merged into `main`'s `8efd1f3`
and has since been deleted upstream; the other two are trivial CI/test fixes not needed here).

## 2. Step 6 verification (pre-existing code, before any new fixes)

- Backend: `PYTHONPATH=. pytest tests/ -v` -- **246/246 passed**, 9.5s, 3 benign warnings from
  tests deliberately exercising the documented `acute_deterioration` crash zone.
- Frontend: `npm ci && npm run build` (exact CI command) -- clean, 606ms, no errors.
- `src/pulse_runner/cli_state_runner.py`, `cli_state_scenario.py`, `src/api/
  continuous_state_pipeline.py`, and the alert-fallback logic in `src/api/` all imported cleanly
  with expected symbols present.
- Confirmed main's pre-merge fixes survived: Vitals table STATUS column removed, ECG relabelled
  ("rate-scaled reference template" wording present in `CardiacWaveformPanel.jsx`/
  `DoctorReportCard.jsx`), optional patient `label` field present on both the `Patient` model and
  `PatientResponse` schema.

## 3. Docker / Pulse environment (this Mac, Apple Silicon)

- `docker image inspect kitware/pulse:4.3.1 --format '{{.Architecture}}'` → `amd64`.
- Host (`uname -m`) → `arm64`. Confirmed genuinely emulated: `docker run --platform linux/amd64
  kitware/pulse:4.3.1 uname -m` inside the container reports `x86_64`.
- The image was not cached locally (fresh Docker daemon) -- a full pull was required. Its digest
  (`sha256:fb9b43b769e9...`) matches exactly the manifest hash independently verified against
  Docker Hub's API during the original containerd-snapshotter corruption investigation
  (`docs/continuous_state_sync_status.md` §2.1) -- confirmed to be the real, uncorrupted image.
- Backend image built via `docker build --platform linux/amd64 -t m2k-hf-pulse-backend -f
  backend/Dockerfile .` -- succeeded, ~231s pip install (amd64 emulation), only 2 harmless
  `FromPlatformFlagConstDisallowed` lint warnings (pre-existing in the Dockerfile, not fixed here).
- Latest available Pulse engine version is actually 4.4.0 (released 2026-09-30), but Kitware has
  not published a Docker image past 4.3.1, and every published tag (including 4.3.1) is
  `linux/amd64`-only -- no multi-arch image exists. Recommendation (not acted on): do not upgrade;
  every characterized limitation in this project (crash rates, the `Mode`/`Type` schema field
  found by reading `Actions.proto`, the ~45-55% CO gap) was found against 4.3.1 specifically and
  would need full re-verification against any new version, for no feature benefit to this project.

## 4. Local DB schema drift, found and fixed (non-destructive)

The real local `data/db/m2k_hf_pulse.db` predated the merged code's schema additions -- exactly the
same already-documented gap as `docs/continuous_state_sync_status.md` §6.4 (`Base.metadata.
create_all()` only creates missing *tables*, never adds missing *columns*). Missing: `waveform_data`
on `simulation_runs`; `baseline_deficit_score`, `dominant_mechanism` on `risk_assessments`.

Fixed: backed up the file (`data/db/m2k_hf_pulse.db.bak_pre_schema_fix_20261002_181930`, gitignored,
same directory), then `ALTER TABLE ... ADD COLUMN` for the 3 missing nullable columns. No existing
row touched (confirmed patient count unchanged, 1 row, before/after).

No existing demo patient with a full 21-day window existed on this local DB (1 patient, 0 wearable
readings, 0 simulation runs) -- the demo patients referenced in prior docs (e.g.
`7693f167-c7ae-4f4f-bd59-18e8bb119a7a`) only ever existed on whatever machine produced those docs.
Per instruction: proceeded with a fresh synthetic patient instead (§8 below), rather than skipping
the live run.

## 5. Merge-only bug found and fixed: `project_physiology()` call in `continuous_state_pipeline.py`

**Found** while attempting to run `scripts/verify_continuous_state_pipeline.py` for the first time
on the integration branch: `run_daily_continuous_pipeline()` crashed immediately on day 1 with
`TypeError: project_physiology() got an unexpected keyword argument 'deterioration_rate_per_day'`.

**Root cause, confirmed by checking each branch in isolation:**
- `origin/feature/continuous-state-sync` alone: `project_physiology()`'s 4th parameter is named
  `deterioration_rate_per_day` -- matches `continuous_state_pipeline.py`'s call site exactly.
- `origin/feature/real-outcome-validation`: that parameter was renamed to `composite_rate`, **and
  its meaning changed** -- it now wants the raw, unconverted population-SD-equivalents/day rate,
  not pre-multiplied by `SD_RATE_TO_RISK_SCORE_PER_DAY`. `services.py`'s own comment documents this
  exact bug being fixed there on 2026-09-10 (`docs/methodology.md` §8). `continuous_state_
  pipeline.py` -- a file unique to `continuous-state-sync`, never touched by `real-outcome-
  validation`'s own commits -- never got the same fix.
- This is a genuine **merge-only** bug: not present on either branch alone, never caught by the
  pytest suite (`scripts/verify_continuous_state_pipeline.py` is Docker-dependent, not part of CI).
  Every call to `run_daily_continuous_pipeline()` would hit it -- not an edge case.

**Fix:** mirrored `services.py`'s exact fix -- `composite_rate=rate_info["composite_rate"]`,
unconverted, with the same explanatory comment. Removed the now-unused `SD_RATE_TO_RISK_SCORE_
PER_DAY` import.

## 6. Full cross-branch call-site sweep

Every function `continuous_state_pipeline.py`, `cli_state_runner.py`, and `cli_state_scenario.py`
call from a module either `real-outcome-validation` or `unstable-alert-fallback` touched
(`projection.py`, `deterioration_rate.py`, `score_reporting.py`, `services.py`, `models.py`,
`schemas.py`, `patient_file.py`, `scenario_file.py`, `runner.py`):

| Caller → callee | Signature | Meaning/units | Notes |
|---|---|---|---|
| → `projection.project_physiology()` | was broken | was broken | **Fixed, §5** |
| → `deterioration_rate.compute_deterioration_rate()` / `days_to_next_stage()` | OK | OK | Identical usage to `services.py` |
| → `services.apply_tier1_fallback()`, `get_wearable_window()`, `WEARABLE_WINDOW_DAYS` | OK | OK | |
| → `services.FLUID_OVERLOAD_CAVEAT_MESSAGE` / `EF_FALLBACK_MASKS_...` | OK | **partial** | **Fixed, §7** -- a second, always-appended caveat constant (`ECG_REFERENCE_TEMPLATE_CAVEAT_MESSAGE`) was silently missing entirely |
| → `patient_file.build_patient_file()` | OK | OK | New `hr_baseline_bpm` param defaults `None`, backward-compatible |
| → `scenario_file.STABILIZATION_S` | OK | OK | Unchanged constant (60) |
| → `models.PulseState/SimulationRun/RiskAssessment` field construction | OK | OK | All fields exist with matching types (incl. the 3 `ALTER TABLE`'d columns, §4) |
| `cli_state_runner.py` → `runner.COMPLETENESS_TOLERANCE_S/PULSE_BIN_DIR/PULSE_DRIVER/PulseExecutionError/_expected_paths()/_scan_log_for_fatal_markers()/_check_csv_completeness()` | OK | OK | `runner.py`'s +88 lines (preflight guardrail) were additive only |
| `cli_state_scenario.py` → `patient_file.ef_to_cardiovascular_modifiers()` | OK | OK | Unchanged despite +144 lines elsewhere (BCG additions) |
| `cli_state_scenario.py` → `scenario_file._cardiovascular_modification_action()/_exercise_action()/DATA_REQUESTS` | OK | OK | |
| any of the three → `score_reporting.py` or `schemas.py` | -- | -- | **None import from either module at all** -- root cause of §8's alert-fallback gap |

## 7. Fix: ECG-caveat parity gap (Part A)

`continuous_state_pipeline.py` built `risk_caveats` as only the fluid_overload-specific message (or
`None` otherwise) -- `services.py` always additionally appends `ECG_REFERENCE_TEMPLATE_CAVEAT_
MESSAGE` regardless of scenario type. Fixed by extracting `build_risk_caveats(scenario_type,
ef_is_fallback, risk_bucket)` into `services.py`, called identically from both pipelines.
`services.py`'s own observable behavior is unchanged (confirmed: the exact fluid_overload-caveat
test in `tests/test_api.py` still passes unmodified).

## 8. Fix: alert-fallback parity (Part B) -- the continuous pipeline bypassed the fix entirely

**Found:** `run_daily_continuous_pipeline()` only ever constructed its `SimulationRun` row *after*
`run_initial()`/`resume_and_advance()` already succeeded; its `except PulseSdkError: raise` was a
no-op re-raise. On a Pulse failure, **no row was written at all** -- worse than the pre-fix
`services.py` behavior, and `routes.py`'s `_build_status()`/the classifier-only fallback alert
(the entire point of `fix/unstable-alert-fallback`) could never fire for a continuous-pipeline
failure.

**Design, approved in stages:**
- `SimulationRun` is now created with `status="running"` *before* calling Pulse (mirrors
  `services.py`'s ordering exactly), committed+refreshed immediately.
- A new shared helper, `services.mark_simulation_run_failed(db, run, error_message)`, extracted
  from `_run_assessment_pipeline()`'s two near-identical failure blocks (both now call it too, so
  there is one failure-recording code path, not two independent ones).
- The `try/except` around the Pulse call narrowly wraps **only** `run_initial()`/
  `resume_and_advance()` (and the `patient.json` write immediately before `run_initial()`, mirroring
  `services.py`'s own try-block scope) -- nothing after (PulseState write, risk scoring, projection,
  the RiskAssessment insert) is in scope. A code bug there (e.g. §5's TypeError) still raises
  normally and is never recorded as a Pulse failure. `logger.exception(...)` logs the full
  traceback; `mark_simulation_run_failed()` stores just `f"{type(e).__name__}: {e}"` in
  `error_message`.
- `run_daily_continuous_pipeline()`'s return type changed to `models.PulseState | None` -- `None`
  on a recorded Pulse failure.
- Updated both callers that assumed a non-`None` return (`scripts/verify_continuous_state_
  pipeline.py`, `scenarios/run_real_patient_continuous.py`): both now look up the failed
  `SimulationRun` and exit loudly with its `error_message` instead of hitting an opaque
  `AttributeError` on `None`.

**Day-after-failure behavior, confirmed and pinned by test, not changed:** a failed day is skipped
entirely, never compensated for. No `PulseState` row is written on failure (construction only ever
happens after a successful call), so the next call's `last_state` lookup (`ORDER BY saved_at DESC
LIMIT 1`, queried fresh every call) naturally returns the last *successful* day's state. Confirmed
from `resume_and_advance()`'s own implementation: `expected_final = prior_offset_s + duration_s` --
the advance is always exactly one `DAILY_ENCOUNTER_DURATION_S` (600s) from wherever the resumed
state left off, with **no catch-up/compensation logic anywhere**. So: day N fails → day N+1 resumes
from day N−1's state and advances by **one** encounter, not two -- the engine's simulated clock
ends up permanently one encounter (600s) behind the calendar for every failed day. `scenario_type`/
`severity` are unaffected by this lag (always computed from the *current* rolling 21-day wearable
window), so only the Pulse-simulated physiological clock itself falls behind, not the classifier's
inputs.

**Known limitation, documented rather than fixed (schema/route/frontend change required):** a
non-Pulse exception (a code bug, not a Pulse failure) leaves its pre-created `SimulationRun` at
`status="running"` forever -- there is no third terminal status. Investigated setting
`status="error"` on this path: `SimulationRun.status` is a plain free-text `String` column (no DB
constraint), but `routes.py`'s `_build_status()` passes `latest_run.status` straight through into
`StatusResponse.simulation_status`, which is a strict Pydantic `Literal["collecting", "pending",
"running", "complete", "failed"]` -- any other value would raise a validation error (500) on
`/patients/{id}/status` the moment this path is hit. Six frontend files (`Sidebar.jsx`,
`ErrorState.jsx`, `AppShell.jsx`, `ReportsPage.jsx`, `usePatientReport.js`, `mockData.js`) also key
off `simulation_status` with no `"error"` case. Fixing this properly needs widening the schema
`Literal`, auditing `routes.py`'s branches, and adding frontend handling -- out of scope for this
integration pass; **left as `status="running"` forever on this one failure mode**, not fixed.

## 9. New tests (`tests/test_continuous_state_pipeline.py`, no Docker needed)

Pulse mocked at two points: `continuous_state_pipeline.run_initial`/`resume_and_advance` (the
day-advance call) and `src.pulse_runner.runner.run_pulse` (which `project_physiology()`'s own
7/14/30-day horizon re-simulations call independently -- missed on the first pass, found when the
first test attempt tried a real subprocess call to `/pulse/bin/PulseScenarioDriver`).

- `test_failure_is_recorded_and_matches_normal_pipeline_alert_fallback` -- failed `SimulationRun`
  row exists with the right `scenario_type`/`severity`/`error_message`; `_build_status()` reports
  `simulation_status="failed"`, `latest_assessment_stale=True`, a classifier-only fallback alert;
  the last good `PulseState` is untouched (same id/state_json/simulation_time_s).
- `test_non_pulse_exception_is_not_swallowed_and_not_recorded_as_pulse_failure` -- a `TypeError`
  from `project_physiology` propagates normally; the `SimulationRun` stays `status="running"`
  (pins §8's documented limitation), never misreported as `"failed"`.
- `test_day_after_failure_resumes_from_last_good_state_one_encounter_behind` -- pins the §8
  day-after-failure behavior: day 3 (after day 2 fails) resumes from day 1's exact `state_json`/
  `simulation_time_s`, advances by exactly one `DAILY_ENCOUNTER_DURATION_S`, not two.
- `test_build_risk_caveats_always_includes_ecg_caveat`, `test_fluid_overload_ef_fallback_mask_is_
  selected_correctly`, `test_continuous_pipeline_produces_same_caveats_as_shared_helper` -- §7's
  caveat-parity fix, both as direct unit tests of `build_risk_caveats()` and end-to-end through the
  continuous pipeline.

Also added: `TestProjectionConsistency::test_continuous_and_normal_pipelines_produce_identical_
projection_for_identical_inputs` (§11 below) -- 7 new tests total.

**Full suite: 253/253 passing** (246 pre-existing + 7 new), `PYTHONPATH=. pytest tests/ -v`.

## 10. Cross-machine check: re-running `verify_continuous_state_pipeline.py` on this Mac vs §6.3

Re-ran the (now-fixed, §5) 3-day script for real inside the Docker container on this Mac and
compared check-by-check, value-by-value against `docs/continuous_state_sync_status.md` §6.3
(produced on a different machine):

| | §6.3 (documented) | This Mac | Match? |
|---|---|---|---|
| day1/2/3 `simulation_time_s` | 660.0 / 1260.0 / 1860.0 | 660.0 / 1260.0 / 1860.0 | exact |
| day1/2 `last_ejection_fraction_pct` | 45.0 | 45.0 | exact |
| day3 `last_ejection_fraction_pct` | 30.0 | 30.0 | exact |
| day1 `last_severity` | 0.4826 | 0.47613 | off by 0.0065 |
| day2 `last_severity` | 0.4828 | 0.47631 | off by 0.0065 |
| day3 `last_severity` | 0.4784 | 0.47046 | off by 0.0079 |

All 6 of the script's own PASS/FAIL checks hold (OVERALL: PASS) -- every structural property
(EF carry-forward, simulation_time_s stepping, append-only PulseState rows) matches exactly. The
`last_severity` difference (~0.006-0.008, not floating-point noise) is explained precisely, not
hand-waved: **`requirements.txt` does not pin scikit-learn's version.** The committed
`models/*.joblib` files were last saved with scikit-learn **1.9.0**; this container's Python 3.9.2
can only install **1.6.1** (`pip show scikit-learn` confirmed on both the host venv and the
container), triggering `InconsistentVersionWarning` on every model load. This is the *exact same*
train/inference version-mismatch class of issue already documented once in
`docs/continuous_state_sync_status.md` §2.6 and "fixed" there by retraining inside the container --
that fix has since drifted (the committed models were retrained again on the host at some later
point, without a matching in-container retrain). Not fixed here -- retraining models is out of
scope for an integration pass and would change outputs project-wide; flagged as a real, open,
pre-existing environment-drift issue.

**SpO2:** not part of this comparison. It's a deterministic *input*
(`seed_patient_and_window()`'s fixed formula, identical code both times), never printed or checked
as an output by this script. Pulse's own simulated `OxygenSaturation` output is a separate,
already-documented-elsewhere broken reading (defaults to 0 without an explicit decimal format) and
isn't one of this script's 6 checks either way.

## 11. Step 4: projection consistency between the two pipelines

For identical patient demographics/EF/BNP/wearable window, identical mocked classifier output, and
identical mocked Pulse encounter result, `services._run_assessment_pipeline()` and
`continuous_state_pipeline.run_daily_continuous_pipeline()` were run against two separately-seeded
but input-identical patients. Confirmed via a real test, not just code-reading:
**`projection_json`, `risk_score`, `risk_bucket`, `nyha_class`, and `deterioration_direction` came
back bit-for-bit identical.** Expected, since both now call `project_physiology()` with the same
argument shape (§5's fix made this true) and build their `RiskAssessment` from the same analytics
functions in the same order -- not a coincidence, a direct consequence of the shared code path.

## 12. Do forward projections feed into anything the next day's pipeline uses? No.

Traced precisely, both pipelines (identical shape in each):
1. `sim_features = analyze_simulation(df)` -- from **today's real Pulse output**.
2. `risk = compute_risk_score(...)` -- from `sim_features`.
3. `nyha_class = classify_nyha(..., risk_score=risk["risk_score"], ...)`.
4. `rate_info = compute_deterioration_rate(trends_df)` / `days_forward = days_to_next_stage(...)`.
5. **Only then** is `project_physiology(...)` called, consuming today's already-finalized
   `severity`/`composite_rate` as *inputs* -- its own output (`projection_json`) is written to the
   `RiskAssessment` row purely for display (the frontend's Forward Projection panel).

The `PulseState` row the *next* day reads back stores `last_ejection_fraction_pct`/`last_severity`
from the classifier's **today** values (`new_state = models.PulseState(..., last_ejection_fraction_
pct=ejection_fraction_pct, last_severity=severity, ...)`) -- never anything projection-derived.
`RiskAssessment.score_provenance` (the alert decision) calls `build_score_report(classifier_
severity=self.severity, pulse_risk_score=self.risk_score, scenario_type=self.scenario_type, ...)` --
`build_score_report()`'s signature (`src/analytics/score_reporting.py`) takes no projection input at
all. **Conclusion: projections are a pure write-only, display-only side effect of each day's
assessment -- nothing downstream reads them back.**

**Proposed (not implemented) for scenario-test speed, pending approval:** add `compute_projection:
bool = True` to `run_daily_continuous_pipeline()`. When `False`, skip the `project_physiology(...)`
call and set `projection_json = None` directly (column is nullable, `src/api/models.py` line 119) --
nothing else changes, since nothing else depends on projection output (confirmed above). Default
`True` preserves current behavior exactly; the scenario-test harness would opt in explicitly.

## 13. Parallel Pulse throughput on this Mac (10 CPUs available to Docker Desktop)

A short calibration scenario (30s stabilize + 30s advance = 60s simulated) run N-at-once inside one
container, isolating raw `PulseScenarioDriver`-subprocess concurrency from the project's existing
2-concurrent-patient ceiling (`docs/real_world_data_integration.md` §8.3, which was bottlenecked by
FastAPI's SQLAlchemy connection pool, a confound not present here):

| N | Result | Total wall | Mean per-call | Peak CPU | Peak memory |
|---|---|---|---|---|---|
| 2 | 2/2 OK | 31.3s | 31.2s | -- | -- |
| 4 | 4/4 OK | 42.3s | 41.7s | -- | -- |
| 6 | 6/6 OK | 50.5s | 50.4s | 600% (6 cores) | 302MB / 7.75GB |

Zero failures at any level tested, memory negligible. Slowdown vs. N=2 (near-ideal parallel): N=4 is
1.35x slower/call, N=6 is 1.61x slower/call -- real contention, no cliff, no crashes. Not tested
beyond N=6. Benchmark script was a throwaway (`scripts/_benchmark_concurrent_pulse.py`), deleted
after use, not committed.

**Rough scenario-test wall-time estimate (10 patients x 14 days x 3 seeds = 420 patient-days),
extrapolating the above ratios onto the documented ~110-120s/call full-duration baseline (a
different-duration workload than the 60s calibration scenario, and assuming a `stable`-like mix
with no crash-zone retries -- real uncertainty, not a measurement):**

| Concurrency | Est. per-call (full duration) | Est. throughput | Est. total (no projection) | Est. total (with projection, 4x calls/day) |
|---|---|---|---|---|
| N=6 (best tested) | ~177-193s | ~117 patient-days/hr | **~3.6h** | **~14-15h** |

The projection toggle (§12) is the single biggest lever on this estimate.

## 14. Live 14-day continuous-state-sync run against a flat/non-perturbed patient

`scripts/verify_continuous_state_live_14day.py` (new, committed): seeds 21 baseline + 14
incrementally-added wearable readings (35 total, all identical values -- no day-to-day drift at
all), EF/BNP held constant (no new `ClinicalReport`), run once against the real Pulse engine. Goal:
isolate whether a genuinely stable patient's risk score/NYHA class/alert status drifts over 14 days
of continuous-state-sync purely from the resume mechanism itself (repeated CVMod reissue, Pulse's
own state-resume behavior), with zero input signal driving any real change.

Confirmed before the run: `build_resume_scenario()` puts `CardiovascularMechanicsModification`
unconditionally as `Actions[0]` (wrapped in `PatientAction`, Pulse's required schema shape) on every
call -- verified directly by building a real resume scenario dict and inspecting it, not just by
reading source.

**Status: running at the time of this commit** (started 2026-10-02, ~14 real Pulse calls at
~2-4min/call under amd64 emulation expected). Results (per-day wall time, `simulation_time_s` step
correctness, risk_score/risk_bucket/NYHA/alert drift or lack thereof across the 14 days) will be
reported as a follow-up once complete -- not blocking this PR per explicit instruction not to block
on it.
