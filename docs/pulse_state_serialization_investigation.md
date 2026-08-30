# Pulse State Serialization — Feasibility Investigation

**Date:** 2026-08-30
**Scope:** Standalone verification only. No changes were made to `src/patient_builder/`,
`src/pulse_runner/`, `src/api/`, or the database. This document reports what was found and
tested in support of a possible future continuous-state-synchronization feature (carrying a
patient's Pulse state forward between daily runs, instead of rebuilding it from scratch).

## Goal

Confirm whether Pulse supports saving and resuming simulation state, using the engine's actual
source/API (not assumptions), and if so, prove it works end-to-end with a real test.

## Environment issues found along the way

### 1. Local `kitware/pulse:4.3.1` image was corrupted — root cause: local containerd-snapshotter extraction bug (FIXED)

Docker Desktop was installed but not running; once started, the `kitware/pulse:4.3.1` image was
already present locally but had ~2,019 of ~9,451 files as 0 bytes, including
`PulseScenarioDriver` and `PyPulse.cpython-39-x86_64-linux-gnu.so`. Initially suspected disk-full
corruption (C: drive was at 97% full), but Docker's data root was confirmed to already live on
D: (126GB free, via `CustomWslDistroDir` in `settings-store.json`), ruling that out.

**First (incorrect) conclusion:** a full `docker rmi` + fresh `docker pull` reproduced the exact
same 2,019 zero-byte file count, while an unrelated large image (`python:3.11-slim`) pulled and
ran cleanly — this was initially read as proof the *published* `kitware/pulse:4.3.1` image was
broken on Docker Hub. That conclusion was wrong, caught by testing more rigorously (below).

**Actual root cause, confirmed:** the corruption was local, specific to this machine's Docker
Desktop having `UseContainerdSnapshotter: true` enabled (a newer, opt-in image-storage backend).
Proof: `docker save kitware/pulse:4.3.1` was used to export the image's raw layer blobs exactly
as stored in the registry, bypassing WSL2/containerd extraction entirely. Each blob's filename
(its own content-addressed sha256) was verified to match its actual content hash, and one blob's
hash (`fb9b43b769e9...`) matched the exact manifest digest Docker Hub's public API reports for
this tag — cryptographic proof the local copy is bit-for-bit identical to what's published.
Extracting that raw layer tar directly (`tar -tvzf`, no container runtime involved) showed
`pulse/bin/PulseScenarioDriver` at a correct 13,534,624 bytes — **not 0 bytes**. The registry
content was always fine; only this machine's containerd-snapshotter extraction into the running
container's filesystem was corrupting it.

**Fix:** disabled Docker Desktop's containerd snapshotter (Settings → General → uncheck "Use
containerd for pulling and storing images" → Apply & Restart), which switches the storage driver
back to the classic `overlay2`. After removing and re-pulling `kitware/pulse:4.3.1` under
`overlay2`, the zero-byte count dropped to a normal background rate (26/9,451) and
`PulseScenarioDriver` ran a real scenario successfully (`Version: 4.3.1`, produced valid output).

**Consequence for this project:** the existing pipeline is **not** blocked by anything outside
local control. `src/pulse_runner/runner.py`'s pin to 4.3.1 (needed for
`src/patient_builder/scenario_file.py`'s `CardiovascularMechanicsModification` action) should now
work via Docker on this machine, once the containerd-snapshotter setting stays disabled.

`kitware/pulse:4.2.0` was also pulled and confirmed intact independently of this bug (real
~12.5MB `PulseScenarioDriver`, only 87/43,241 files empty — a normal background rate), and was
used for the tests below since it was the first known-working image at the time. It does **not**
have `CardiovascularMechanicsModification`, so it isn't a drop-in replacement for the real
pipeline as currently written — 4.3.1 (now working) should be used for the real pipeline instead.

## What Pulse's serialization API actually looks like (from source, not docs)

Two real, independent mechanisms exist:

**1. Low-level Python SDK** (`pulse.engine.PulseEngine`, wrapping the `PyPulse` pybind11 module
— confirmed in `/source/src/python/pybind/PulseEngines.cpp`):

```cpp
.def("serialize_from_file", &PulseEngineThunk::SerializeFromFile)
.def("serialize_to_file", &PulseEngineThunk::SerializeToFile)
.def("serialize_from_string", &PulseEngineThunk::SerializeFromString)
.def("serialize_to_string", &PulseEngineThunk::SerializeToString)
```

`PulseEngine` even implements Python's pickle protocol (`__getstate__`/`__setstate__`) directly
on top of binary `serialize_to_string`/`serialize_from_string` — an engine instance is literally
picklable.

**2. Scenario-JSON / CLI level** — what this project's `pulse_runner/runner.py` actually drives
via `PulseScenarioDriver`. Confirmed against the real protobuf schema
(`pulse/cdm/bind/Engine.proto`, `pulse/cdm/bind/Actions.proto`,
`pulse/engine/bind/Scenario.proto`):

- `SerializeStateData` (an action, sibling to `AdvanceTime`, not wrapped in `PatientAction`):
  ```json
  {"SerializeState": {"Type": "Save", "Filename": "/workspace/state_saved.json"}}
  ```
  (`Type` is an enum: `Save = 0`, `Load = 1`.)
- `ScenarioData.StartType` is a `oneof` of `EngineStateFile` (string path) or
  `PatientConfiguration` — i.e. a **new** driver process can start directly from a saved state
  file instead of building a patient from scratch:
  ```json
  {"Scenario": {"EngineStateFile": "/workspace/state_saved.json", "AnyAction": [...]}}
  ```
- The top-level scenario JSON must be wrapped in `{"Scenario": {...}}` per
  `pulse/engine/bind/Scenario.proto`'s `ScenarioData{ Scenario, Configuration }` — confirmed by
  running the driver and reading its own parse errors, matching Pulse's own bundled examples
  (`/pulse/bin/EngineState.json`, `/pulse/bin/InitialPatientState.json`).

No evidence of partial/selective state — this serializes the whole engine, not a curated subset.

## Test performed

Using `kitware/pulse:4.2.0`, `StandardMale.json` (bundled patient), and a sustained `Exercise`
action (0.3 intensity — a version-agnostic substitute for `CardiovascularMechanicsModification`,
which doesn't exist in 4.2.0's schema):

| Scenario | What it does |
|---|---|
| `scenario_full.json` | One continuous process: stabilize 60s → Exercise → advance 180s straight through (0→240s). Ground truth. |
| `scenario_save.json` | Same, but only advances 90s post-Exercise (0→150s), then `SerializeState`/`Save` to `state_saved.json`. |
| `scenario_resume.json` | New process, `EngineStateFile: state_saved.json`, **no re-issued Exercise action**, advances the remaining 90s. |

### Results

- The resumed run's internal clock started at **150s** (not reset to 0) — confirmed in its own
  log: `[SimTime(s)] 150(s)` immediately after `[SerializingFromFile]`.
- `scenario_save`'s last row (t=150.00) and `scenario_resume`'s first row (t=150.02) matched
  exactly (HR=152.461435, MAP=58.503545, SV=68.638643, ...).
- `scenario_resume`'s final row (t=240.00) was **bit-for-bit identical** to the same timestamp in
  `scenario_full`'s uninterrupted run (HR=156.835338, MAP=61.420524, CO=10256.508396,
  SV=65.396667, ...).
- The ongoing `Exercise` effect (elevated HR, depressed MAP) persisted through save/resume
  **without being re-issued** in the resume scenario — confirming action-in-progress state, not
  just static vitals, is captured.

**Conclusion: full-fidelity, gapless continuation.** No discontinuity, no reset to baseline.

### A real gotcha for the future feature

The resumed run's process **exited with code 1**, logging:

```
[ERROR] [240(s)] !!!! Simulation time does not equal expected end time !!!!
```

This is a false positive: `PulseScenarioDriver`'s own internal consistency check compares the
final simulation time only against the *scenario's own* `AdvanceTime` sum (90s), without knowing
the loaded state already carried 150s of elapsed time — so it flags 240s ≠ 90s as an error, even
though the physiology is entirely correct.

**This directly collides with the existing crash-detection design** in
`src/pulse_runner/runner.py`:
- `FATAL_LOG_MARKERS = ("irreversible", "fatal", "[error]")` would flag this line.
- `result.returncode != 0` already raises `PulseExecutionError` on its own.

**A naive integration of resume via the CLI driver would misreport every successful resumed run
as a crash.** Verified via the SDK that this check does not exist at that layer — calling
`serialize_from_file()` then `advance_time_s()` directly raises no exception and no error is
logged. Two ways to handle this when building the real feature:

1. **Prefer the SDK** (`pulse.engine.PulseEngine`) over shelling out to `PulseScenarioDriver` for
   a resumed run — avoids the false-positive entirely, and also avoids per-invocation process
   startup cost (see below).
2. If staying with the CLI driver, special-case this specific benign message in the crash
   detector only for resumed runs with a known state-file time offset.

## Cost: format, size, timing

Measured directly via the SDK (`time_serialize.py`), isolated from process-startup overhead:

- **File format:** JSON (binary format also exists in the API but wasn't cleanly measured here —
  a minor, unrelated bug was hit in `PulseEngine.serialize_to_string`'s wrapper, which forwards
  its format argument without converting it the way `serialize_from_string` does).
- **Size:** 2,327,768 bytes (**~2.33MB**) for one whole-body adult model's full state.
- **Save (`serialize_to_file`):** ~0.31–0.44s.
- **Load (`serialize_from_file`):** ~0.43s.
- **Dominant real-world cost:** each fresh `PulseScenarioDriver`/`PulseEngine` process spends
  ~10–30s on substance/config file loading before it does anything — far more than the
  serialize/deserialize step itself. This favors keeping a long-lived engine process (SDK) across
  a patient's daily runs over spawning the CLI driver fresh each time, if minimizing overhead
  matters at production scale.

## Bottom line

Pulse's save/resume mechanism is real, well-documented in its own source, and verified here to
produce numerically exact continuation of full engine state — a solid foundation for a
continuous-state-sync feature. The one thing to design around is the CLI driver's false-positive
exit-code-1 on resume (see above). The `kitware/pulse:4.3.1` corruption that blocked the existing
pipeline turned out to be a local Docker Desktop containerd-snapshotter bug on this machine, now
fixed by disabling that setting — not an external blocker.

Standalone test scripts (`build_scenarios.py`, `time_serialize.py`) used for this investigation
were written to a scratch directory outside this repository and are not committed here.
