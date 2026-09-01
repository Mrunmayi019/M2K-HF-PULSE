# Continuous State Sync — Session Log (2026-08-30, updated 2026-09-01, 2026-09-02)

**Read this first if picking up this work in a fresh session.** Nothing in this document is
merged, reviewed, or approved — `main` and the live demo pipeline (`src/api/services.py`,
`src/pulse_runner/runner.py`) are completely untouched by everything below. This is both a
record of what happened across both sessions and a resumption guide.

**STATUS AS OF 2026-09-01: working end-to-end.** The 2026-08-30 session ended blocked on a
segfault, diagnosed at the time as a joblib/Pulse threading collision. That diagnosis turned out
to be **wrong** (see §6.1) — investigated further, the real cause was a native bug specific to
the Pulse Python SDK's `initialize_engine()` call, unrelated to scikit-learn/joblib entirely. The
fix was to rebuild the resume mechanism on `PulseScenarioDriver`'s CLI/scenario-JSON layer
instead of the SDK (§6.2), which resolved it completely. The full daily pipeline now runs
end-to-end against a real patient with no crash (§6.3), produces a real risk assessment through
the exact same analytics code the existing pipeline uses (§6.4), and is visually confirmed
working in the actual frontend GUI (§6.6). Section 6 is the current source of truth; Sections
1–5 are the (now partially superseded) 2026-08-30 record, kept as-is for the investigation trail
— **do not trust §3/§4's "not working" / "next steps" content below without reading §6 first**,
it describes a state that no longer holds.

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

**Update 2026-09-01: this turned out to be the wrong diagnosis. See §6 below for what was
actually wrong and how it was fixed — the feature now works end-to-end.**

---

## 6. Session update (2026-09-01) — the real root cause, the fix, and full end-to-end verification

Resumed per explicit instruction, in 4 steps: (1) rebuild the resume mechanism on the CLI driver
instead of the SDK and re-verify the reissue fix with the same rigor as before; (2) run the real
day1→day2→day3 pipeline end-to-end; (3) wire results into the existing frontend/API; (4) confirm
visually in the running GUI. Each step was verified before moving to the next, per instruction.

### 6.1 The 2026-08-30 "joblib fork vs. Pulse threads" diagnosis was wrong

Before starting Step 1, the previous session's fix attempt (`n_jobs=1`) was re-examined as a
sanity check. Bisecting further than the previous session had: calling **only**
`PulseEngine.initialize_engine()` — zero scikit-learn/joblib imported anywhere in the process —
segfaulted, 100% reproducibly across 3 independent fresh-process runs, using the exact same
patient file previously verified to work bit-for-bit. `gdb` showed a native crash entirely inside
Pulse's own C++ code:

```
SESubstanceManager::AddActiveSubstance()
  <- SubstanceManager::InitializeSubstances()
  <- Controller::Initialize()
  <- Controller::InitializeEngine()
```

Meanwhile `PulseScenarioDriver` (the CLI/scenario-JSON path), run on the *identical*
patient/scenario computation, completed cleanly every time (`[Final SimTime] 660(s)`, exit 0).

**Conclusion:** the bug is specific to the Python SDK's `initialize_engine()` path, not a
process-sharing collision with joblib. The 2026-08-30 session's bit-for-bit-exact SDK tests
(§2.4–2.6) weren't wrong about the *reissue-on-resume* finding (that's a property of Pulse's own
state-resume behavior, confirmed independently again at the CLI layer in §6.2) — they just got
lucky on scheduling and never happened to hit this particular crash, the same class of
false-negative already flagged for a different reason in §2.7's tests #10–13. `n_jobs=1`
"fixing" the crash in some runs was never a fix; it was never going to touch this bug at all.

**Action:** `src/pulse_runner/sdk_runner.py` (the SDK-based module) is kept, unmodified beyond an
added docstring warning, as the documented evidence trail for this bug — not deleted, but not
used by anything anymore. It's superseded by two new modules built on the CLI driver instead:
`src/pulse_runner/cli_state_scenario.py` (scenario-JSON builders for save/resume) and
`src/pulse_runner/cli_state_runner.py` (subprocess execution + resume-aware crash detection).
`src/api/continuous_state_pipeline.py` now imports from the latter; its own logic (DB queries,
classifier calls, multi-rate strategy) is otherwise unchanged.

### 6.2 Step 1 — CLI-driver resume mechanism, two real bugs found and fixed, then verified

Porting `sdk_runner.py`'s save/resume logic onto `PulseScenarioDriver`'s scenario-JSON actions
(`SerializeState` to save, `EngineStateFile` to resume — schema described in
`docs/pulse_state_serialization_investigation.md`) surfaced two bugs, both found and fixed before
any result was trusted:

1. **Wrong field name.** The investigation doc's `{"SerializeState": {"Type": "Save", ...}}`
   shape doesn't match 4.3.1's actual schema — confirmed directly against this image's own
   `/source/src/schema/pulse/cdm/bind/Actions.proto`, whose `SerializeStateData` message has a
   field named `Mode` (enum `eMode`, values `Save`/`Load`), not `Type`. The investigation doc's
   test that "confirmed" this schema was actually run against a different Pulse version
   (`4.2.0`) — the field name apparently changed. Fixed in `cli_state_scenario.py`.
2. **Crash-detector logic bug.** The known false-positive gotcha (§2.3: a resumed run exits 1 and
   logs a benign `"Simulation time does not equal expected end time"` error, because the driver's
   own internal check doesn't know about the state file's already-elapsed clock) was correctly
   *detected and filtered* out of the fatal-marker list in the first implementation, but the code
   still unconditionally raised on the nonzero exit code regardless of whether any real fatal
   markers remained. Fixed: a resume's exit code 1 is now only tolerated when, after filtering,
   zero other fatal markers remain; any other nonzero exit (or a resume with genuinely different
   errors present) still raises normally.

**Re-verification, same rigor as the original SDK-layer investigation (§2.4–2.5), now at the CLI
layer**, patient/EF/severity identical to the original test (EF=56.4, severity=0.46) for direct
comparability:

| Check | Result |
|---|---|
| Determinism control (2 independent continuous runs) | Bit-for-bit identical |
| Resume WITHOUT reissuing CVMod (negative control) | HR −3.584%, CO −6.574% drift vs. continuous — confirms the drift is a real Pulse state-resume property, reproduced at this layer too |
| Resume WITH reissue, via the actual production `cli_state_runner.resume_and_advance()` | **HR/MAP/CO/SV all 0.000000% difference** vs. continuous — exact match |

Host test suite: 162/162 passing throughout.

### 6.3 Step 2 — full day1→day2→day3 pipeline, no crash

`scripts/verify_continuous_state_pipeline.py` (unmodified) run twice against a synthetic
seeded patient, both times clean:

```
[day1] simulation_time_s=660.0   last_ejection_fraction_pct=45.0  last_severity=0.4826
[day2] simulation_time_s=1260.0  last_ejection_fraction_pct=45.0  last_severity=0.4828
[day3] simulation_time_s=1860.0  last_ejection_fraction_pct=30.0  last_severity=0.4784
=== VERDICT === all 6 checks PASS, both runs
```

Given §2.7's tests #10–13 showed a crash can "disappear" from timing luck alone, a second
independent run was required before trusting this — both passed identically, no signs of
flakiness. Unlike the abandoned SDK path, this mechanism is a plain subprocess exec per call, not
an in-process race condition, so this is expected to be genuinely stable rather than lucky.

### 6.4 Step 3 — real SimulationRun/RiskAssessment, reusing services.py's own analytics

Checked whether the continuous-sync pipeline writes to the tables the frontend/API already read
(`src/api/routes.py`'s `/status`, `/history`, `/projection`, `/report` all query
`RiskAssessment`/`SimulationRun`/`WearableReading` generically by `patient_id`, agnostic to how a
row was produced) — it didn't; `PulseState` was a separate table with no risk score, NYHA class,
trend, or projection data at all. Fixed by making `run_daily_continuous_pipeline()` also produce
a real `SimulationRun` + `RiskAssessment` row, using the **exact same** analytics functions
`services.py`'s from-scratch pipeline already uses (`analyze_simulation`, `compute_risk_score`,
`classify_nyha`, `compute_deterioration_rate`, `project_physiology`, `extract_waveform_data`) —
none of those functions changed; they're generic over any Pulse-output DataFrame. This is why no
new API endpoint was needed: `/patients/{id}/status|history|projection|report` all "just work"
for a continuous-synced patient already.

`cli_state_runner.run_initial()`/`resume_and_advance()` were extended to also return the raw
per-encounter DataFrame (previously discarded after squeezing into a snapshot dict) so
`analyze_simulation()` has something to operate on.

**Caveat worth flagging, not a bug:** on day 1, the returned df spans stabilize+CVMod+advance, so
`hr_rise`/`map_drop`/`co_drop_pct` measure the same "healthy baseline → modified+advanced end
state" swing `services.py` measures. On day 2+ (a resume), the df spans only *that day's*
reissue+[Exercise]+advance window (no stabilization — already done on a prior day), so those same
deltas measure "state right after today's reissue → end of today's advance," not "healthy
baseline → now." Arguably a more natural notion for continuous monitoring (how much did today's
encounter move the patient), but not numerically the same quantity the from-scratch pipeline
computes, and `risk_score.py`/`staging.py` were calibrated against the from-scratch semantics.
Flagged in `src/api/continuous_state_pipeline.py`'s module docstring; not resolved here — needs a
decision before this feature is used for anything beyond a demo.

**A separate, pre-existing bug found on the real local DB (not this branch's fault):** the actual
runtime `data/db/m2k_hf_pulse.db` predates `main`'s most recent commit's schema additions
(`waveform_data` on `simulation_runs`; `baseline_deficit_score`, `dominant_mechanism` on
`risk_assessments`, both added 2026-08-28). Both real patients with a full 21-day window on this
DB had **zero** risk assessments despite the window being full — consistent with the existing
`services.py` pipeline having silently failed to write new assessments against this stale local
schema ever since that commit landed, since `Base.metadata.create_all()` only creates missing
*tables*, never adds missing *columns* to existing ones. Fixed non-destructively: backed up the
db file (`data/db/m2k_hf_pulse.db.bak_pre_schema_fix`, gitignored, same directory), then
`ALTER TABLE ... ADD COLUMN` for the 3 missing nullable columns — no existing row touched, no
data lost. This restores the DB to what `main`'s own current code already expects; it isn't a
change to any behavior, just an un-break of a local-machine migration gap. `data/db/` is entirely
gitignored, so none of this touches git history or any tracked file.

### 6.5 Step 4 — confirmed visually in the actual running frontend

Ran `run_daily_continuous_pipeline()` twice (day 1, day 2-via-resume) against a **real** existing
patient in the real project DB (`7693f167-c7ae-4f4f-bd59-18e8bb119a7a`, not a throwaway test DB),
additive only — no existing row modified or deleted. Day 2's `simulation_time_s` advanced by
exactly 600.0s from day 1's, confirming a genuine resume, not a from-scratch rebuild.

Started the backend (`uvicorn src.api.main:app`, host venv, pointed at the now-fixed real DB) and
the frontend (`npm run dev`) both from this branch. In the actual browser GUI, selecting this
patient shows, entirely through the existing, unmodified UI:

- **Patient Dashboard:** HIGH RISK / NYHA Class IV, "Fluid Overload" current condition, severity
  index 0.91, EF 32%, BNP 1400, live vitals with 7-day trend arrows, the cardiac waveform panel
  (ECG + PV loop, generated from this pipeline's own Pulse output), and the Forward Projection
  panel (+7/+14/+30 day severity/risk-bucket trajectory).
- **Trends & History:** both assessments listed with a visible risk trend — 12:58 PM MODERATE/III
  → 1:06 PM HIGH/IV — plus the full 22-day wearable history charts.

No frontend code was changed to make this appear — exactly the "point the dashboard at this
patient via the normal API" outcome, confirmed rather than assumed.

### 6.6 Current state, precisely (supersedes §3 above)

**Confirmed working, end-to-end:**
- CLI-driver save/resume mechanism, bit-for-bit exact reissue-on-resume (§6.2).
- Full day1→day2→day3 daily pipeline, twice, no crash (§6.3).
- Real `SimulationRun`/`RiskAssessment` rows produced via the existing analytics code, visible
  through the existing, unmodified API endpoints (§6.4).
- Visually confirmed in the actual running frontend GUI against a real patient (§6.5).
- Host test suite: 162/162 passing throughout today's changes.
- `main` unchanged at `46d0083` throughout (confirmed via `git log main -1` after every step).

**Still open (not blocking, but not resolved either):**
- The day-1-vs-day-2+ semantic difference in what `hr_rise`/`map_drop`/`co_drop_pct` measure
  (§6.4's caveat) — a design question for review, not a bug.
- `sdk_runner.py` (the abandoned SDK path) is left in the tree as a documented dead end, per
  earlier convention of not deleting evidence of a real, reproducible bug finding — could be
  filed as an upstream Pulse issue at some point, not done here.
- No commit has been made this session — branch working tree currently has: modified
  `src/api/continuous_state_pipeline.py`, `src/pulse_runner/sdk_runner.py` (docstring only); new
  `src/pulse_runner/cli_state_scenario.py`, `src/pulse_runner/cli_state_runner.py`; updated
  `docs/continuous_state_sync_status.md` (this file). Same three pre-existing unrelated local
  diffs as before (`frontend/package.json`/`package-lock.json`, `models/phase3_eval_report.txt`)
  plus untracked `scenarios/` debug/verification scripts (safe to delete, not committed, same
  precedent as the 2026-08-30 session).
- The real local DB's schema-drift fix (§6.4) is a local runtime-state change only
  (`data/db/` is gitignored) — worth telling whoever else runs this project locally that their
  own `data/db/m2k_hf_pulse.db` may need the same 3-column `ALTER TABLE` if it predates
  `46d0083`, since nothing about `main`'s own code currently detects or fixes this automatically.

### 6.7 Plain-English summary (supersedes §5 above)

Following up on the professor's suggestion that the digital-twin simulation should carry a
patient's physiological state forward from one day to the next instead of rebuilding from
scratch, we found and fixed the crash that was blocking this. The earlier diagnosis (two software
libraries competing for processor cores) turned out to be a red herring, caught by testing one
piece completely in isolation; the actual cause was a defect specific to one particular way of
talking to the physiology engine (a lower-level programming interface), which a different,
higher-level way of talking to the same engine doesn't have. Switching to that other interface,
and fixing two smaller bugs surfaced along the way, resolved it completely. The full daily
pipeline now runs start-to-finish without crashing, produces a real risk assessment using the
exact same scoring logic the current system already uses, and — most concretely — we watched a
real patient's updated risk status, condition trend, and forward-looking projection appear
correctly in the actual application, using unmodified screens, after two simulated days of
continuous state carried forward rather than rebuilt. One open design question remains (exactly
what a couple of the risk-score's inputs mean on a resumed day versus a brand-new day), flagged
for review but not blocking. The current working demo was not touched or put at risk at any
point; a separate, pre-existing local database issue was found and fixed along the way without
losing any data.

---

## 7. Follow-up investigation (2026-09-01/09-02) — projection_json flatness, root-caused

After §6's end-to-end confirmation, a manual eyeball check of the two real `RiskAssessment` rows
created in §6.5 (patient `7693f167-c7ae-4f4f-bd59-18e8bb119a7a`) surfaced an oddity: row 2's
`projection_json` showed the *same* `risk_score`/`risk_bucket` (0.5044/MODERATE) at all three
horizons despite `projected_severity` correctly ranging 0.946→1.0.

**Investigated and resolved as NOT a bug in this branch's code.** Re-deriving the two
`compute_risk_score()` sub-components (`acute_score`, `baseline_deficit_score`) at each horizon
showed `acute_score = 0.0` at every horizon (HR fell, MAP rose, CO rose during the encounter --
all clamped to 0 by the acute-score formula) while `baseline_deficit_score` stayed pinned at
0.5044 (driven by `map_start`, captured before the severity-driven action is even applied, so it
can't vary with projected severity by construction). `max(acute_score, baseline_deficit_score)`
is correctly returning the baseline floor every time -- expected behavior, not a projection or
resume-specific bug.

Digging into *why* `acute_score` stays 0 across a full severity range led to a real, confirmed
finding: **the `fluid_overload` scenario's own action definition
(`src/patient_builder/scenario_file.py`) has no volume-loading mechanism** -- it only reduces
venous compliance, which (absent an actual volume increase) mobilizes pooled blood into
circulation and makes simulated hemodynamics *improve* with severity instead of worsening. This
is a **pre-existing, `main`-affecting limitation**, not something introduced by or specific to
continuous-state-sync -- confirmed as the mechanistic root cause behind `docs/methodology.md`
§6.1's already-documented observation that `fluid_overload`'s scenario generation barely varies
with severity.

**Documented as a new, clearly-separate entry (not merged with the existing, already-closed
EF-fallback/BNP-proxy `fluid_overload` limitation):**
- `docs/methodology.md` §8: new subsection **"Fluid_overload scenario lacks a volume-loading
  mechanism, diagnosed 2026-09-01"** -- full mechanism, root cause, why it isn't fixed now (needs
  a real volume-loading Pulse action added to the scenario, plus re-running Phase 2 validation and
  likely retraining the severity regressor -- scenario-design rework, not a quick parameter fix),
  and the current mitigation already in place (`baseline_deficit_score`/`max()`, §6.1 -- a working
  safeguard, not a patient-safety gap).
- `docs/methodology.md` §9: a pointer bullet under a new "Directly motivated by the
  continuous-state-sync investigation" group.
- `HANDOFF.md` P2: a new checklist item pointing to both.

**Not fixed, per explicit instruction not to attempt a fix under time pressure.** No code was
changed by this investigation -- only `docs/methodology.md`, `HANDOFF.md`, and this file.

**State as of 2026-09-02, end of session:** branch `feature/continuous-state-sync` has one
committed fix (`cb7dff6`, §6) plus these three doc-only changes on top (uncommitted at the time of
writing -- check `git log` for whether they landed as a follow-up commit). `main` still untouched.
Real DB (`data/db/m2k_hf_pulse.db`) still has the two real `RiskAssessment` rows from §6.5's
verification, additive only, nothing lost. Backend (`:8000`)/frontend (`:5173`) dev servers were
left running in the background during this session; they will need restarting in a fresh session.
