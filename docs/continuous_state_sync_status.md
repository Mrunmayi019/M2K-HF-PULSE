# Continuous State Sync — Branch Status (feature/continuous-state-sync)

**Read this first if picking up this branch in a fresh session.** Not merged, not reviewed,
explicitly NOT to be merged into `main` or wired into the live pipeline until the owner reviews
and approves it. `main`/the current demo pipeline (`src/api/services.py`, `src/pulse_runner/
runner.py`) are untouched by this branch's work.

## What this branch is

A prerequisite investigation (`docs/pulse_state_serialization_investigation.md`) confirmed Pulse
supports save/resume of engine state. This branch implements a *parallel*, not-yet-wired-in daily
pipeline that resumes a patient's Pulse state across days instead of rebuilding it from scratch
each time (see that doc for the full state-serialization background).

## Done and verified

- **Branch** created off a clean `main`, nothing there touched.
- **DB schema** (`src/api/models.py`): new `PulseState` table, additive only — no existing
  columns/tables changed. Stores the serialized state blob (`state_json`) plus
  `last_ejection_fraction_pct`/`last_severity` (the two scalar inputs to the existing, unmodified
  `ef_to_cardiovascular_modifiers()` — chosen over storing its output multiplier dict, since that
  stays valid even if the function's internal formula is recalibrated later).
- **`src/pulse_runner/sdk_runner.py`** (new, separate from `runner.py`): Pulse SDK-based
  save/resume (not the CLI driver — see file docstring for why: the CLI driver has a
  false-positive exit-code-1 on every resumed run). Implements the confirmed
  reissue-CardiovascularMechanicsModification-on-every-resume pattern. **Verified bit-for-bit
  exact** against an independent continuous run, using this real module (not scratch scripts).
- **`src/api/continuous_state_pipeline.py`** (new, separate from `services.py`): the daily
  pipeline — resume → reissue CardiovascularMechanicsModification with current EF/severity →
  apply today's scenario-specific Exercise action if the classifier calls for one → advance. Full
  multi-rate update strategy (severity recomputed every day; EF/BNP only on a new
  ClinicalReport) documented in the module docstring.
- Host test suite: **162/162 passing** after every step above.

## Blocked: a real, confirmed native segfault — not yet fixed

Running the actual daily-pipeline function (day 1 init → day 2 resume → day 3 new-clinical-report,
via `scripts/verify_continuous_state_pipeline.py`) inside the Pulse container segfaults
(exit code 139) partway through `run_initial()`'s `advance_time_s()` call.

**Root cause, confirmed (not just suspected):**
- 8+ isolation tests ruled out: general sklearn+Pulse-SDK coexistence in one process, import
  graph size, real vs. synthetic classifier features, open vs. closed DB session, function-call
  nesting depth (tested 0–3 levels of plain wrapper functions — no crash at any depth).
- A bisection test (inlining two helper functions) made the crash disappear — **but this is not a
  real fix**. Confirmed by running the real crashing repro under `gdb`: it did not crash either,
  but the trace showed dozens of worker threads spawning plus an actual `fork()` right around the
  classifier `predict()` calls. Both "fixes" were luck — gdb and the inlining both perturbed
  timing enough to dodge a race, not remove it.
- Checked the trained models directly: both `RandomForestClassifier`/`Regressor` have
  **`n_jobs=-1`**, 300 estimators — joblib's fork-based parallel backend across all CPU cores.
  This matches the gdb trace exactly.
- **Confirmed mechanism:** joblib's fork-based parallelism (from `n_jobs=-1` RandomForest
  `predict()`) racing with Pulse's own internal native threading, when both run in the same OS
  process. This is a well-known hazard class on Linux (forking a multithreaded process while a
  native library holds internal locks/threads is inherently unsafe) — not a bug in this project's
  own logic.

**Tested fix: `n_jobs=1` override at inference time (not a retrain).** Set
`clf.n_jobs = reg.n_jobs = 1` on the already-loaded model objects in
`_load_scenario_classifier_models()`, no change to the committed `.joblib` files.
- Verified the override genuinely took effect: an isolated `predict()` call with it set spawned
  **zero** extra threads and completed in 36ms.
- **Re-ran the full 3-day verification script with the fix in place — still segfaulted, same
  point, same signature (exit 139).**
- **Conclusion: `n_jobs=1` does NOT resolve it.** The race is broader than `RandomForest.predict()`'s
  own `n_jobs`-controlled parallelism — likely `joblib.load()`'s own unpickling process, numpy/BLAS
  automatic thread-pool warmup, or something else scikit-learn/numpy trigger natively, independent
  of that one parameter. Not fully isolated which specific mechanism, but ruled out `n_jobs` as a
  sufficient fix.
- This change has been **reverted** — `_load_scenario_classifier_models()` in
  `src/api/continuous_state_pipeline.py` is back to its original form (no `n_jobs` override left
  in as dead/misleading code).

## Next step (not started)

**Subprocess isolation**, per the owner's own fallback plan: run the classifier's `predict()`
calls and the Pulse SDK's engine operations in genuinely separate OS processes, so the
fork-happy joblib backend and Pulse's native engine never coexist in one process — architecturally
identical to how `src/pulse_runner/runner.py` already isolates Pulse via a `subprocess` call to
`PulseScenarioDriver`, just applied to the SDK path instead of the CLI-driver path.

Concretely, likely shape (not yet implemented or verified):
- `continuous_state_pipeline.py` keeps doing DB/classifier work in the main process as today.
- The Pulse SDK calls (`run_initial`/`resume_and_advance` in `sdk_runner.py`) get moved into a
  child process spawned fresh per call (e.g. `multiprocessing.get_context("spawn")` — NOT
  `"fork"`, to avoid inheriting the parent's already-loaded sklearn/joblib state entirely — or a
  small standalone script invoked via `subprocess.run()`, passing inputs in and reading the new
  state JSON + snapshot back out via file or stdout).
- Re-run `scripts/verify_continuous_state_pipeline.py` against this to confirm the crash is
  actually gone (not just moved/hidden by different timing — the gdb/inlining experience above is
  a caution against declaring victory without a clean, repeated pass).
- Once verified: re-run the full host test suite (162 tests as of this note), confirm nothing
  broke, then continue to the originally-scoped Step 5 (re-verify the classifier's 21-day-window
  logic against the new resumed-state behavior) — not started yet either.

## Housekeeping notes for whoever picks this up

- `scenarios/call_depth_test/`, `scenarios/inline_no_function_test/`, `scenarios/
  wrapped_identical_test/`, etc. under the repo root are leftover debug-run scratch output from
  this investigation (untracked, not gitignored by the current `.gitignore` patterns since they're
  new subdirectory names) — safe to delete, not needed for future work.
- `models/phase3_eval_report.txt` shows as locally modified (not committed on this branch) because
  the scenario classifier was retrained mid-session to fix an unrelated, pre-existing staleness
  bug (the committed `.joblib` files predated a `nyha_ordinal` feature removal from an earlier,
  unrelated commit on `main`). This retraining was necessary to unblock any testing at all, but is
  out of scope for this feature — left uncommitted/unresolved intentionally; decide separately
  whether to commit the new eval numbers or retrain again to match.
- `frontend/package.json`/`package-lock.json` show as locally modified — this is the pre-existing,
  intentional local vite@5 downgrade (Node 22.11 on this machine can't run vite 8's native
  binding), unrelated to this feature, not committed to this branch.
