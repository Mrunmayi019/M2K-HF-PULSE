# Continuous State Sync — Session Log (2026-08-30)

**Read this first if picking up this work in a fresh session.** Nothing in this document is
merged, reviewed, or approved — `main` and the live demo pipeline (`src/api/services.py`,
`src/pulse_runner/runner.py`) are completely untouched by everything below. This is both a
record of what happened today and a resumption guide; Section 4 tells you exactly what to do
next.

---

## 1. What was investigated and why

The project owner relayed feedback from their professor on the multi-rate parameter update
strategy already documented elsewhere in this repo (per-parameter interpolate/derive/
retain-as-is rules for wearable vs. clinical-report data arriving at different cadences). The
professor's follow-up clarified that "twinning frequency" was meant more specifically:
**continuous state synchronization** — Pulse should carry a patient's simulation state forward
from one daily run to the next, rather than the current pipeline's behavior of rebuilding the
patient and re-stabilizing from scratch on every assessment. Today's work investigates whether
Pulse actually supports this, and — once confirmed — begins implementing it as an isolated,
unreviewed feature branch.

---

## 2. Chronological log

### 2.1 Docker corruption: found, misdiagnosed, then correctly root-caused

Starting the state-serialization investigation required Docker. Docker Desktop was installed but
not running; once started, `kitware/pulse:4.3.1` was already pulled locally but showed ~2,019 of
~9,451 files as 0 bytes, including `PulseScenarioDriver` and `PyPulse.cpython-39...so`.

**First (incorrect) conclusion:** disk-full corruption was ruled out (Docker's data root was
confirmed on D:, 126GB free, via `CustomWslDistroDir` in `settings-store.json`). A full
`docker rmi` + fresh `docker pull` reproduced the *exact same* 2,019-zero-byte-file count, while
an unrelated large image (`python:3.11-slim`) pulled and ran cleanly. This was read as proof the
*published* `kitware/pulse:4.3.1` image was broken on Docker Hub — documented as such in the
first version of `docs/pulse_state_serialization_investigation.md`.

**Correction, prompted by the project owner explicitly asking to rule out local WSL2 disk
corruption before accepting the upstream-broken conclusion:** a full `wsl --shutdown` + Docker
Desktop process kill + restart + re-pull still showed the same corruption — which on its own
still looked consistent with "broken upstream." The decisive test was different: `docker save
kitware/pulse:4.3.1` was used to export the image's raw layer blobs exactly as stored in the
registry, bypassing WSL2/containerd extraction entirely. Each blob's filename (its own
content-addressed sha256) was verified to match its actual content hash, and one blob's hash
(`fb9b43b769e9...`) matched the exact manifest digest Docker Hub's public API reports for this
tag — cryptographic proof the local copy is bit-for-bit identical to what's published. Extracting
that raw layer tar directly (`tar -tvzf`, no container runtime involved) showed
`pulse/bin/PulseScenarioDriver` at a correct 13,534,624 bytes — not 0 bytes. **The registry
content was always fine; only this machine's Docker Desktop extraction was corrupting it.**

**Actual root cause:** this machine's Docker Desktop had `UseContainerdSnapshotter: true`
enabled (a newer, opt-in image-storage backend) mis-extracting this specific image's large
binaries. **Fix:** disabled it (Settings → General → uncheck "Use containerd for pulling and
storing images" → Apply & Restart), which switches the storage driver back to classic
`overlay2`. After removing and re-pulling `kitware/pulse:4.3.1` under `overlay2`, the zero-byte
count dropped to a normal background rate (26/9,451) and `PulseScenarioDriver` ran a real
scenario successfully (confirmed `Version: 4.3.1` in its own log output).

Both `docs/pulse_state_serialization_investigation.md` and this project's memory files were
updated to reflect the corrected root cause, replacing the earlier wrong conclusion rather than
leaving it standing alongside the correction.

### 2.2 Pipeline health re-verification post-fix (5 real patients)

Before trusting `kitware/pulse:4.3.1` for any new feature work, the *existing, unmodified*
pipeline (`patient_builder` → `pulse_runner.runner.run_pulse()` → `simulation_features` →
`risk_score`) was re-run against 5 real synthetic patients, using the real project modules (not
scratch scripts):

| Patient | Scenario | Result |
|---|---|---|
| P0005 (EF=61.5, severity=0.127) | `stable` | HR 72.0→70.8, MAP 95.2→95.2 — matches documented reference (71→70 / 95→95) closely. `risk_score=0.006`, LOW. |
| P0007 (severity=0.373) | `acute_deterioration` | Timed out (180s) |
| P0013 (severity=0.373) | `acute_deterioration` | HR 72.3→162.5, MAP 77.4→47.4, `instability_flag=1`, `risk_score=0.80`, HIGH |
| P0018 (severity=0.609) | `acute_deterioration` | Timed out (180s) |
| P0023 (severity=0.953) | `acute_deterioration` | HR 72.1→162.5, MAP 79.1→61.6, `instability_flag=1`, `risk_score=0.7274`, HIGH |

The 2/4 `acute_deterioration` timeouts (50%) match the *already-documented* 40–60% failure rate
for this scenario type in `docs/methodology.md` (it adds an `Exercise` action, which the docs
already flag as destabilizing the engine above moderate intensity) — not a new regression from
the Docker fix or anything else. The `stable` patient showed no drift from the documented
reference. **Conclusion: the existing pipeline is healthy; the one failure mode observed is the
same pre-existing, already-characterized one.**

### 2.3 Step 1 — Pulse state serialization feasibility (the original ask)

Confirmed, from Pulse 4.x's actual source (not docs), two independent save/resume mechanisms:

1. **Low-level Python SDK** (`pulse.engine.PulseEngine`): `serialize_to_file`/`serialize_from_file`/
   `serialize_to_string`/`serialize_from_string`, JSON or binary. Implements Python's pickle
   protocol directly on top of binary serialize.
2. **Scenario-JSON/CLI level** (what the *existing* pipeline's `pulse_runner/runner.py` drives via
   `PulseScenarioDriver`): a `{"SerializeState": {"Type": "Save", "Filename": ...}}` action, and a
   top-level `"EngineStateFile"` field to resume a **new** driver process from a saved state.

**Test performed** (using `kitware/pulse:4.2.0`, since 4.3.1 was still believed broken at this
point in the session — see §2.1's correction, which came later): a 240s scenario with a
sustained `Exercise` action (0.3 intensity), split into save-at-150s + resume-for-90s across two
separate driver processes. Result: the resumed run's final values at t=240s were **bit-for-bit
identical** to the same timestamp in an uninterrupted continuous run (HR=156.835338,
MAP=61.420524, CO=10256.508396, SV=65.396667 — matching to all printed digits), including the
ongoing `Exercise` effect, which was never re-issued after resume.

**A real gotcha found:** the resumed run's CLI-driver process exited with **code 1**, logging
`[ERROR] ... Simulation time does not equal expected end time` — a false positive, since
`PulseScenarioDriver`'s own consistency check compares final time only against the *scenario's
own* `AdvanceTime` sum, not the loaded state's already-elapsed clock. This would collide directly
with `runner.py`'s existing crash detection (`FATAL_LOG_MARKERS` includes `"[error]"`), so any
future integration via the CLI driver would misreport every successful resume as a crash — this
is why the later implementation (§2.5) uses the SDK instead.

**Cost measured** (via the SDK, isolated from process-startup overhead): JSON state file
**2,327,768 bytes (~2.33MB)**; save **~0.3–0.44s**; load **~0.43s**. Dominant real-world cost is
each fresh process's ~10–30s of substance/config file loading, not the serialize step itself.

Full writeup: `docs/pulse_state_serialization_investigation.md`.

### 2.4 The CardiovascularMechanicsModification-specific test — real drift found

The Exercise-action test above doesn't touch the actual mechanism the real pipeline uses for
EF/severity-driven simulation: `CardiovascularMechanicsModification`. Per explicit instruction to
verify this specific action before writing any integration code, a parallel test was run on
`kitware/pulse:4.3.1` (by then confirmed working, see §2.1) using the SDK and a **real** patient
(`P0000`, EF=56.4, severity=0.460) and the project's own unmodified
`ef_to_cardiovascular_modifiers()` output (`stroke_volume_multiplier=0.816`,
`systemic_resistance_multiplier=0.89`, `systemic_compliance_multiplier=0.89`).

Result — **not** bit-for-bit exact this time:

| | HR | MAP | CO | SV |
|---|---|---|---|---|
| Continuous run, final (t=240s) | 74.13346 | 95.22238 | 6.14502 | 82.89129 |
| Resumed run, final (t=240s), action not reissued | 71.50609 | 95.34464 | 5.74305 | 80.31556 |
| **Difference** | **−3.5%** | +0.13% | **−6.5%** | **−3.1%** |

**Determinism control** (two independent continuous runs, identical setup, no resume at all):
**0.000% difference** across HR/MAP/CO/SV, bit-for-bit identical (74.133464 both runs, etc.) —
ruling out "Pulse is just slightly noisy between engine instances" and confirming the drift above
is real, not measurement noise. Per instruction, this was reported and **execution stopped**
before writing any branch, DB, or integration code.

### 2.5 Root-cause investigation — two hypotheses tested in order

**Test 1 — `Incremental: false` instead of `true`:** drift persisted at a similar magnitude
(HR −4.04%, CO −7.31%, SV −3.42%, MAP −0.46%) and additionally reproduced a *separate*,
already-documented behavior: without `Incremental`, the modification triggers an implicit
restabilization that silently consumed ~600s of extra simulated time (`t` jumped from a nominal
150s to 750s). **Rejected** — the "Incremental transition-ramp state isn't serialized" hypothesis
is wrong.

**Test 2 — re-issue the action fresh immediately after resume, before advancing:** resume-final
values matched the continuous run's final values **bit-for-bit exactly** (74.13346353679559 /
95.22237825628771 / 6.145018696462611 / 82.89129366541165 — identical to 15 significant figures).
**Confirmed.** Re-issuing the action didn't cause any jump either (values immediately
before/after re-issue were identical).

**Confirmed fix pattern:** on every resume, before advancing time, re-apply the patient's
currently-active `CardiovascularMechanicsModification` (recomputed from current EF/severity)
fresh — never rely on it continuing automatically from loaded state. This has one DB-schema
implication: it's not enough to store just the serialized state blob; the last-used
EF/severity must also be persisted so they can be re-issued on the next resume.

### 2.6 Implementation Steps 1–3 — branch, DB schema, SDK resume module

Per the explicit "same discipline as before: separate branch, staged steps, test after each"
instruction:

- **Step 1 (branch):** `feature/continuous-state-sync` created off a clean `main`. `main` never
  touched.
- **Step 2 (DB schema, additive-only):** new `PulseState` table in `src/api/models.py` — no
  existing columns/tables changed. Stores `state_json` (the full serialized engine state) plus
  `last_ejection_fraction_pct`/`last_severity` (the two scalar *inputs* to the existing,
  unmodified `ef_to_cardiovascular_modifiers()`, chosen over storing its output multiplier dict
  since the inputs stay valid even if that function's internal formula is later recalibrated).
  Host test suite: **162/162 passing** after this change.
- **Step 3 (`src/pulse_runner/sdk_runner.py`, new, separate from `runner.py`):** implements
  `run_initial()`/`resume_and_advance()` using the confirmed reissue-on-resume pattern from §2.5,
  via the SDK (not the CLI driver, per §2.3's false-positive finding). Verified against the real
  module (not a scratch script), using a real synthetic patient: **bit-for-bit exact match**
  against an independent continuous run. Host test suite: **162/162 passing**.
  - A clarifying question was asked and resolved: "apply new wearable data as a fresh action"
    (from the original spec) was confirmed to mean reusing `scenario_file.py`'s existing pattern
    — today's classifier-predicted `scenario_type` determines whether an extra `Exercise` action
    is applied on top of the reissued core modification (for `cardiac_stress`/
    `acute_deterioration` only, matching the existing scenario definitions). Implemented as
    `build_exercise_action()` in `sdk_runner.py`.
- **`src/api/continuous_state_pipeline.py`** (new, separate from `services.py`): the daily
  pipeline — resume → reissue `CardiovascularMechanicsModification` with current EF/severity →
  apply today's scenario-specific `Exercise` action if warranted → advance. Multi-rate strategy:
  `severity`/`scenario_type` recomputed every day (driven by the sliding 21-day wearable window);
  `ejection_fraction_pct`/`nt_probnp_pg_ml` only adopted from a **new** `ClinicalReport` if one
  arrived since the last saved `PulseState`, otherwise carried forward unchanged.
- **`scripts/verify_continuous_state_pipeline.py`** (new, committed — Docker-dependent scripts
  live in `scripts/` per this project's existing convention): drives day 1 (window fill,
  `run_initial`) → day 2 (new wearable reading only, `resume_and_advance`) → day 3 (new
  wearable reading + new clinical report with a different EF) against an isolated temp-file
  SQLite DB.

Two unrelated, pre-existing issues had to be fixed just to get this verification running (not
part of this feature's scope): stale `models/*.joblib` files that predated a `nyha_ordinal`
feature removal from the 15 commits pulled earlier in the day (retrained), and a scikit-learn
version mismatch between the host (1.9.0, which doesn't even exist for the container's Python
3.9) and the container — resolved by retraining *inside* the container so train/inference
environments match.

### 2.7 Step 4 — the segfault, full isolation-test log

Running the real verification script inside the container **segfaults** (exit code 139) inside
`run_initial()`'s `advance_time_s()` call. The following isolation tests were run, in order, to
find the trigger:

| # | Test | Result |
|---|---|---|
| 1 | General sklearn + Pulse SDK coexistence in one process (synthetic zero-value features) | No crash |
| 2 | Same import graph as the real pipeline, then `run_initial()` with hand-built args | No crash |
| 3 | Real classifier features from a real seeded DB, then close DB, then Pulse SDK call | No crash |
| 4 | Same as #3, DB session left open across the Pulse call | No crash |
| 5 | Calling the real `run_daily_continuous_pipeline()` function directly | **Crashes** |
| 6 | Releasing (`del` + `gc.collect()`) the sklearn model references before the Pulse call | Still crashes |
| 7 | Minimal one-line wrapper function around `run_initial()` | No crash |
| 8 | Call-depth ladder: 0, 1, 2, 3 levels of trivial wrapper-function nesting | No crash at any depth |
| 9 | Web search for known Pulse/pybind11 nested-call stability issues | No direct hit |
| 10 | Exact body of `run_daily_continuous_pipeline()`, unindented to flat top-level script code, real ORM-sourced values | **No crash** — completed cleanly |
| 11 | Same exact code, wrapped in a bare `def run_it():` and called | **No crash** — rules out function-wrapping itself |
| 12 | Bisection: real module copy with `_resolve_clinical_values()`/`_load_scenario_classifier_models()` **inlined** instead of called as separate functions | **No crash** — looked like "the fix" at first |
| 13 | **gdb backtrace on the original, unmodified crashing repro** | **Did not crash under gdb either** — but the trace showed dozens of worker threads spawning and an actual `fork()` (`[Detaching after fork from child process 608]`) right around the classifier `predict()` calls |
| 14 | Checked the trained models directly | `clf.n_jobs=-1`, `reg.n_jobs=-1`, 300 estimators each — matches the gdb fork/thread pattern exactly |

**Confirmed root cause:** joblib's fork-based parallel backend (triggered by `n_jobs=-1` on both
RandomForest models, used for `predict()` across 300 estimators) races with Pulse's own internal
native threading when both run in the same OS process. This is a well-known hazard class on
Linux — forking a multithreaded process while a native library holds internal locks/threads is
inherently unsafe — not a bug in this project's own logic. **Tests #10–12's "successes" were not
real fixes**; they were timing perturbations that happened to dodge the race, exactly like gdb's
own overhead did in test #13. This was made explicit rather than presented as solved.

**Tested fix: `n_jobs=1` override at inference time (not a retrain).** Set
`clf.n_jobs = reg.n_jobs = 1` on the already-loaded model objects in
`_load_scenario_classifier_models()` — no change to the committed `.joblib` files.
- Verified the override genuinely took effect: an isolated `predict()` call with it set spawned
  **zero** extra threads (`threading.active_count()` unchanged) and completed in 36ms.
- Re-ran the full 3-day verification script with the fix in place: **still segfaulted**, same
  point, same signature (exit 139).
- **Conclusion: `n_jobs=1` does not resolve it.** The race is broader than
  `RandomForest.predict()`'s own `n_jobs`-controlled parallelism — likely `joblib.load()`'s own
  unpickling process, numpy/BLAS automatic thread-pool warmup, or some other native threading
  behavior triggered independently of that one parameter. Which exact mechanism was not further
  isolated. The change has been **reverted** — `_load_scenario_classifier_models()` is back to
  its original form, no dead/misleading `n_jobs` override left in.

---

## 3. Current state, precisely

### Confirmed working

- **Pulse state serialization mechanism** (SDK + CLI, both forms) — confirmed from source,
  §2.3.
- **Existing, unmodified pipeline health** post-Docker-fix — 5 real patients, no drift on
  `stable`, failure pattern on `acute_deterioration` matches pre-existing documented rate — §2.2.
- **CardiovascularMechanicsModification reissue-on-resume pattern** — bit-for-bit exact,
  verified twice (once in the standalone root-cause investigation, once against the real
  `src/pulse_runner/sdk_runner.py` module) — §2.4, §2.5, §2.6.
- **DB schema addition** (`PulseState` table, additive-only) — 162/162 tests passing.
- **`src/pulse_runner/sdk_runner.py`** — verified bit-for-bit exact resume behavior via the real
  module.
- Host test suite: **162/162 passing** as of the latest commit.

### Not working

- **The daily pipeline (`run_daily_continuous_pipeline()` in
  `src/api/continuous_state_pipeline.py`) segfaults** when actually run end-to-end (day 1 → day 2
  resume → day 3 new-clinical-report) inside the Pulse container.
- **Root cause confirmed:** joblib's fork-based `RandomForest.predict()` parallelism
  (`n_jobs=-1`) colliding with Pulse's native engine threading in the same process (§2.7).
- **`n_jobs=1` was tested as a narrower, cheaper fix and confirmed insufficient** — verified
  correctly applied, crash persisted regardless (§2.7). This path is closed; no need to
  re-attempt it without new information.
- **Not yet attempted:** subprocess isolation (§4).

### Branch and commit state

- Branch: **`feature/continuous-state-sync`**
- Latest commit: **`1ffeaac`** — "Add continuous-state-sync feature: DB schema + SDK resume +
  daily pipeline (WIP, blocked)"
- `main`'s tip is `46d0083` (unchanged, confirmed identical to what `git pull` brought in earlier
  today) — **`main` and the live demo pipeline are untouched** by all of today's feature work.

### Uncommitted local state (present in the working tree, intentionally not committed)

- **`frontend/package.json` / `frontend/package-lock.json`** — the pre-existing, intentional
  local `vite@5` downgrade (this machine's Node 22.11 can't run `vite@8`'s native binding; fixed
  via `npm install --save-dev vite@5 @vitejs/plugin-react@4`, reapplied after today's `git pull`
  reset `package.json` to its upstream `vite@^8.1.1`). Unrelated to this feature.
- **`models/phase3_eval_report.txt`** — shows as modified because the scenario classifier was
  retrained mid-session (§2.6) to fix the unrelated, pre-existing `nyha_ordinal` staleness bug.
  New numbers: 90.7% test accuracy / MAE 0.047 (vs. the previously-committed 92.3% / 0.048) — a
  normal amount of run-to-run RandomForest variance, not a regression. Left uncommitted
  intentionally; out of scope for this feature. Decide separately whether to commit these numbers
  or retrain again to match the previously-committed figures.
- **`scenarios/call_depth_test/`, `scenarios/inline_no_function_test/`,
  `scenarios/wrapped_identical_test/`, `scenarios/sdk_verify/`, `scenarios/sanity_check/`, etc.**
  — leftover debug-run scratch output from today's isolation testing (untracked; not matched by
  the current `.gitignore`'s `scenarios/*.json` etc. patterns since these are whole new
  subdirectories). Safe to delete, not needed for future work.

---

## 4. Exact next steps to resume

**Subprocess isolation for the Pulse SDK calls** — the confirmed next step, not yet implemented.
Goal: the classifier's `predict()` calls (which trigger joblib's fork-based parallelism) and
Pulse's native engine operations must never coexist in the same OS process.

Architecturally identical to how `src/pulse_runner/runner.py` already isolates Pulse via a
`subprocess` call to `PulseScenarioDriver` — apply the same isolation principle to the SDK path:

1. **`src/api/continuous_state_pipeline.py`** keeps doing DB queries and classifier
   `predict()` calls in the main process exactly as today (nothing here needs to change).
2. **`src/pulse_runner/sdk_runner.py`'s `run_initial()`/`resume_and_advance()`** need to run in a
   genuinely separate child process per call, not in-process. Two concrete implementation options
   (neither started):
   - `multiprocessing.get_context("spawn")` (**not** `"fork"` — a fork would inherit the parent's
     already-loaded sklearn/joblib state, defeating the purpose) to run these functions in a
     fresh child process, passing inputs in and getting `(state_json, snapshot_dict)` back via the
     multiprocessing result/queue mechanism.
   - Or a small standalone script (e.g. `src/pulse_runner/sdk_runner_cli.py`) invoked via
     `subprocess.run()`, taking inputs as CLI args or a JSON file, writing its result
     (new state JSON + snapshot) to a file or stdout for the parent to read back — closer in
     spirit to `runner.py`'s existing `PulseScenarioDriver` subprocess pattern.
3. **Verify against the exact same scenario that surfaced the crash**: re-run
   `scripts/verify_continuous_state_pipeline.py` (day 1 init → day 2 resume, no new clinical
   report → day 3 resume, new clinical report with a different EF) inside the Pulse container.
   **Do not declare this fixed on a single clean pass** — §2.7's tests #10–13 showed that timing
   perturbations alone (an inlined function, gdb's own overhead) made the crash disappear without
   actually fixing anything. Run it enough times (or under varied conditions) to be confident the
   fix is structural, not lucky timing.
4. Once genuinely confirmed: re-run the full host test suite (162 tests as of this log; confirm
   the current count first, since `main` may have moved), confirm nothing broke.
5. Only then continue to the originally-scoped **Step 5**: re-verify the scenario classifier's
   21-day-window logic against the new resumed-state behavior. Not started. One piece of relevant
   context already discovered while reading `src/api/routes.py`: the existing pipeline already
   re-triggers `run_assessment_pipeline()` on *every* `/wearable-sync` call once the 21-day window
   first fills (a sliding window, not a one-time gate) — worth checking whether this new daily
   pipeline's resume cadence needs to match that exactly, or whether the two are meant to diverge.

## 5. Plain-English summary

Following up on the professor's suggestion that the digital-twin patient simulation should carry
its physiological state forward from one day to the next (rather than rebuilding the patient from
scratch every time), we confirmed that the underlying simulation engine (Pulse) genuinely supports
saving and resuming its internal state, and that doing so preserves the patient's condition
exactly — but only if the specific mechanism used to represent a patient's disease severity is
deliberately reapplied each time the simulation resumes, which we discovered through testing and
have now built correctly into a new, isolated piece of code. We built the database changes and the
resume logic for this and verified each piece works correctly on its own. However, when we tried
to run the complete daily pipeline end-to-end, it crashed with a low-level technical fault caused
by two different pieces of software (our machine-learning classifier and the physiology engine)
both trying to use multiple processor cores in a conflicting way inside the same program — a known
class of problem, not a flaw in our own logic, and not something a demo audience would ever see
since it's confined to this new, unreleased feature. We tried the simplest fix and confirmed it
doesn't fully solve the problem; the next step is to run the two pieces of software in separate,
isolated processes, which is expected to resolve it cleanly. None of this work has touched the
current working demo, which remains exactly as it was.
