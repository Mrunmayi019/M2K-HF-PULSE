# Research feature flags: wiring, behaviour and evaluation

Branch `feature/wire-research-features`. Five pieces of research code were finished but not wired into the app (`docs/gap_report.md` §1a). Each one now runs behind its own flag, and every flag defaults to off. With all flags off, every API response is identical to `main` (4c60e3f). `tests/test_flags_off_parity.py` checks this against a golden file captured from unmodified `main` before any flag code existed.

No scorer weights, thresholds, models or existing parameter values were changed.

## 1. What each flag wires

| Flag | Acts | Code | Parameters (unchanged, and where they came from) |
|---|---|---|---|
| `PIPELINE_MODE=continuous` | before Pulse | `src/api/continuous_state_pipeline.py` | 600 s per daily encounter (same as fresh). Reissuing the heart modification on resume comes from the bit-for-bit resume tests (`docs/continuous_state_sync_status.md` §2.5, §6.2). |
| `ENABLE_BCG_MODIFIERS` | before Pulse | `bcg_to_cardiovascular_modifiers()` | Reference values are subject 102's own measurements (R-J 175 ms, amplitude 1.1115). Sensitivity 0.3 is borrowed from the EF compliance term. Floor 0.6. Mappings come from Bicen 2017 and Feng 2023. |
| `ENABLE_HR_BASELINE` | before Pulse | `build_patient_file(hr_baseline_bpm=…)` | Pulse clamps the value to 50–110 bpm. |
| `ENABLE_ALERT_HYSTERESIS` | after Pulse (alert only) | `hysteresis_alert_states()` | Enter at severity ≥ 0.15 for 2 days; exit below 0.12 for 2 days. Unvalidated placeholders. |
| `ENABLE_SCENARIO_PERSISTENCE` | before Pulse | `scenario_type_persistence()` | N = 6, from an N sweep from 4 to 10 against one false 5-day streak (subject 14). |

### Inputs for BCG and the HR baseline

Both come from optional clinical-report fields entered by a clinician. `hr_baseline_bpm` is a measured resting HR from a clinical source, as in the validation, which used the clinical-sheet HR. It is never derived from wearable data.

The API rejects any value outside the range the two calibration subjects cover:

| Field | Range |
|---|---|
| R-J interval | 175–233 ms |
| I-J amplitude | 1.061–1.172 |
| J-K amplitude | 1.162–1.496 |
| HR baseline | 77–115 bpm |

The three BCG fields must be given together. A value is stored whenever it is given, but it only reaches Pulse when its flag is on. Each run records what was applied in `personalisation_json`, and the API exposes it as `personalisation`. When anything was applied, `risk_caveats` carries this text:

> Experimental personalisation applied (…). Calibrated on 2 subjects from one dataset (Zhan et al. 2025 multi-pathology BCG dataset); BCG amplitude units are specific to that dataset and are not comparable with other sensors. Not validated against outcomes. In the original validation, setting the HR baseline made stroke volume match worse in both subjects.

Where the two pipelines differ:

| | Fresh mode | Continuous mode |
|---|---|---|
| BCG on a `stable` day | Not applied, because the stable scenario has no heart-modification action. Recorded as `applied: false`. | Applied every day including stable ones, because the core heart modification is reissued daily. |
| HR baseline | Applied every run. | Pulse only reads the patient file when a state starts, so it is fixed for the life of the state. A later change needs a twin reset, and the record says so. |
| Forward projection | Never personalised (`projection_personalised: false`). | Same. |

## 2. Order of operations (hysteresis, persistence, `decide_alert()`, C3)

Pinned by `tests/test_alert_flags.py`:

1. Classifier → raw `scenario_type` + `severity`.
2. Scenario persistence. The label sent to Pulse is the confirmed label. Until some label has held for 6 days, nothing is confirmed, so the raw label is used. That fallback is the one choice not taken from the existing function. The raw label is stored as `raw_scenario_type`.
3. Hysteresis state, computed over this patient's classifier severities up to and including today. It needs no Pulse output, so a failed run gets it too.
4. Pulse → `compute_risk_score()` → C3 streak (`compute_baseline_high_streak()`) on today's **raw** risk bucket. Hysteresis never feeds C3, and C3 never feeds hysteresis.
5. `decide_alert()`, unchanged.
6. Hysteresis replaces the level **only** where `decide_alert()` used the severity rule itself: `failed_fallback` and `unstable_completed`. A valid twin result (`risk_scorer` ALERT/NONE, `moderate` WATCH, `c3_downgraded` WATCH) is never touched, because the hysteresis parameters are severity thresholds and say nothing about `risk_bucket`.
7. The separately reported ML signal (`ml_severity_alert`) gets the hysteresis level too, with `hysteresis_applied: true`.

## 3. Continuous mode: concurrency, ordering, mid-stream reports, reset

Each case below is pinned by `tests/test_continuous_mode.py`.

**First day and later days.** The first `/wearable-sync` that fills the 21-day window triggers an initial run (660 s of simulated time). Each later sync resumes the saved state and adds 600 s.

**Failed day.** Behaviour is unchanged. The run is recorded as failed, no state is saved, and the next day resumes from the last good state, still only +600 s. The engine clock therefore falls one encounter behind for each failed day. `GET /twin-state` reports this as `engine_lag_days`.

**Two submissions for one patient at once.**
- A per-patient lock makes the second run wait. It then resumes from the first run's state, so states chain at +600 s and +1200 s.
- The test also shows what happens **without** the lock: both runs resume from the same parent, both end at +600 s (one day of simulated time is lost), and the later write silently becomes the current state.
- The lock is in-process only. Several uvicorn workers, or a script writing to the same DB, can still fork the state this way. The app runs one worker, so this is documented, not solved.
- Both runs read the wearable window at run time, so if both readings were committed first, both days see the same window.

**Days sent out of order.**
- Only a reading dated after every earlier reading advances the twin.
- An older or same-date reading is stored and returns `status: "stored_not_newest"`. It joins the 21-day window from the next run on. The twin is never rewound.
- A gap in dates is not simulated as elapsed time: one run is always one 600 s encounter.
- Fresh mode is unchanged and runs on every reading.

**Clinical report (EF/BNP) changing mid-stream.**
- The next run adopts the new report: EF goes into the reissued heart modification, and BNP goes to the classifier and NYHA.
- "New" is now decided by report id rather than by timestamp. The old rule was "reported after the last state was saved", and it permanently skipped a report submitted while a run was in progress. A test pins this.
- **Crossing the 40% EF cutoff** (e.g. 45 → 30) needs care. The chronic systolic-dysfunction condition can only be set when a state starts, so the twin keeps the old condition while the EF multiplier is recomputed as though the condition matched. In that example the simulated heart is milder than the EF says. Going the other way it double-counts the EF deficit.
- This is reported as `hfref_condition_mismatch: true` on `GET /twin-state` and shown in red on the dashboard. Only a manual reset fixes it. There is no automatic reset rule.

**Reset (`POST /patients/{id}/reset-state`).**
- Appends a `twin_state_resets` row.
- The next run ignores every state saved before it and does an initial run, back to 660 s.
- Nothing is deleted: earlier states, runs and assessments all stay.
- The C3 streak and hysteresis history are alert-side, so they carry across a reset.
- In fresh mode the request is accepted and recorded, with a note that it only matters in continuous mode.

**Dashboard.** A Twin State panel shows:
- pipeline mode
- when the current state started
- days in the state
- `engine_lag_days`
- days since the last Exercise-triggering label (cardiac_stress or acute_deterioration on a resumed day; Exercise stays active in the saved state)
- the condition-mismatch warning
- which experimental flags are on and what the latest run applied
- a two-step "Reset twin state" action

The panel renders nothing when every flag is at its default, so the default dashboard is unchanged.

**Known differences from fresh mode** (already in the code before this branch, not introduced here):
- An initial run applies no scenario actions.
- Resumed days apply the core heart modification plus Exercise, but never the scenario-specific extras (VenousCompliance, HR multiplier).
- From day 2 the risk features measure change during that day's encounter rather than change from a healthy baseline (`continuous_state_pipeline.py` module docstring, CAVEAT).

## 4. Offline evaluation: features that act after Pulse

Only `ENABLE_ALERT_HYSTERESIS` acts after Pulse. It was recomputed offline on the saved scenario-test outputs with the real functions, without tuning: `src/evaluation/scenario_tests/research_flags_eval.py` → `results/scenario_tests/posthoc/research_flags_eval.json`.

The baseline ("current") is the replay already used by `signal_disagreement_eval.py`, including the failed-day fallback. It reproduces the published numbers: P08 has 11 / 9 ALERT days on dev / held-out, and the should_stay_quiet group has 227 ML ALERT days across 6 seeds.

Patient-days with twin ALERT, twin WATCH and ML ALERT, current → with hysteresis:

| Set | Group | Patient-days | ALERT | WATCH | ML ALERT | Failed / crash-zone days |
|---|---|---|---|---|---|---|
| Development (42–44) | should_catch | 315 | 132 → 132 | 66 → 66 | 270 → 255 | 1 |
| | should_stay_quiet | 189 | 11 → 11 | 30 → 30 | 111 → 118 | 0 |
| | edge_case | 126 | 10 → 10 | 4 → 4 | 22 → 22 | 3 |
| | **all** | 630 | **153 → 153** | **100 → 100** | **403 → 395** | 4 |
| Held-out (45–47) | should_catch | 315 | 123 → 123 | 84 → 84 | 268 → 252 | 0 |
| | should_stay_quiet | 189 | 22 → 22 | 47 → 47 | 116 → 120 | 0 |
| | edge_case | 126 | 0 → 0 | 0 → 0 | 39 → 41 | 0 |
| | **all** | 630 | **145 → 145** | **131 → 131** | **423 → 413** | 0 |

- **Twin ALERT and WATCH counts do not change at all, in either set.** Hysteresis can only change the twin level on failed or crash-zone days, and there are only 4 such days, all in development. Each of them already came after at least 2 consecutive high-severity days, so the hysteresis state agreed with the fallback. The "reach ALERT in all seeds" result for every patient is unchanged as well.
- **The ML signal changes in both directions.**
  - In every should_catch patient it fires about 1 day later per seed: −3 to −4 days per patient per set, a total of −15 (dev) and −16 (held-out).
  - For should_stay_quiet P01 it stays on longer through the deadband: 12 → 18 (dev) and 13 → 18 (held-out).
  - P08 (+1, +1) and edge case P02 (+3, +2) also go up.
  - The net is fewer ML ALERT days, made up of a detection delay on true cases and more false-alert days on P01.
- **What this means.** On this cohort, wiring hysteresis with its existing parameters does not change what the dashboard's main alert says. Its only visible effect is on the secondary ML signal, and that effect is mixed.

## 5. Features that act before Pulse: the scenario-persistence run

Continuous mode, BCG, HR baseline and scenario persistence all change what Pulse simulates, so they cannot be evaluated offline.

**The proposal: one run with `ENABLE_SCENARIO_PERSISTENCE=1`.**
- 10 patients × seeds 42–44, through the same frozen harness (`run_batch.py` → `run_patient_seed.py`). It uses the frozen results-v1 models, which are hash-checked, and `compute_projection=False`.
- Every other flag stays off. `PIPELINE_MODE` doesn't matter here because the harness calls the continuous pipeline directly, as it did for results-v1.
- Outputs go to a separate directory through the new `SCENARIO_TEST_OUTPUT_DIR` env var, so the frozen results are not overwritten. This is the only harness change: when the variable is unset, the paths are as before.
- The raw classifier labels end up in each per-run DB (`simulation_runs.raw_scenario_type`). That allows a day-by-day comparison of simulated label, risk bucket and alert against the saved flags-off run.

Command, run inside the backend image:

```
docker run --rm -v "<repo>:/workspace" -w /workspace \
  -e ENABLE_SCENARIO_PERSISTENCE=1 \
  -e SCENARIO_TEST_OUTPUT_DIR=/workspace/results/scenario_tests/flag_runs/scenario_persistence \
  m2k-hf-pulse-release-pulse-backend:latest \
  python -m src.evaluation.scenario_tests.run_batch
```

**Time estimate.**
- The saved development run averaged 88.5 s per patient-day (median 85.7 s, maximum 141.5 s) with 6 jobs in parallel. That is about 31 min per patient-seed (21 days) and about 15.5 h of serial work.
- At the harness's 6-way parallelism that comes to **about 2.6 h** wall time on the machine that produced results-v1.
- On this PC the live check (§6) took 225–456 s per day for 4 Pulse calls, so roughly 60–110 s per call when nothing else is running. Six calls in parallel will be slower per call. Allow **3–4 h**.

**Not proposed.**
- BCG and HR baseline: the scenario cohort has no BCG or HR-baseline inputs, so any run would need invented inputs.
- Continuous mode: this is already what the scenario-test results exercise.

### 5.1 Results: all 10 patients, seeds 42–44

All 30 patient-seeds finished on 2026-10-08. Raw output: `results/scenario_tests/flag_runs/scenario_persistence/`; comparison: `results/scenario_tests/posthoc/scenario_persistence_eval.json`.

The run was started on 2026-10-07 with `ENABLE_SCENARIO_PERSISTENCE=1` and every other flag off. It was stopped twice because the laptop overheated, and resumed with 4 jobs in parallel instead of 6. Each patient-seed starts from a fresh database, so interrupted jobs were simply rerun from day 1. All 30 jobs exited cleanly. The flag-on run had the same 3 failed days as the flags-off run (all in edge_case), and no new ones.

The comparison was made with `src/evaluation/scenario_tests/scenario_persistence_eval.py`.

- **Twin alert levels:** both runs are scored by replaying the current `decide_alert()` over each run's saved Pulse outputs, the same replay used in §4.
- **Legacy column:** the CSVs' own `alert_flag` column records the older, pre-fix alert, so it is reported only as `legacy_alert_flag`.
- **Sanity check, passed:** with the flag on, the classifier's raw label matched the flags-off label on every day. Only the label sent to Pulse changed.

Patient-days, flags off → persistence on (630 patient-days per column):

| Group | Patient-days | Twin ALERT | Twin WATCH | HIGH-risk | ML ALERT |
|---|---|---|---|---|---|
| should_catch (P04–P07, P10) | 315 | 132 → **120** | 66 → 65 | 187 → 175 | 270 → 270 |
| should_stay_quiet (P01, P08, P09) | 189 | 11 → 11 | 30 → 30 | 34 → 34 | 111 → 111 |
| edge_case (P02, P03) | 126 | 10 → 10 | 4 → 4 | 10 → 10 | 22 → 22 |
| **all** | 630 | **153 → 141** | **100 → 99** | 231 → 219 | 403 → 403 |

The flags-off column reproduces the published development-set totals (§4).

Persistence held back a classifier label on 47 patient-days. Of the 30 patient-seeds, **only one changed its outcome: P04 seed 44**, a should_catch patient.

**P04 seed 44 in detail:**
- **Flags off:**
  - The classifier gave two one-day labels in a row: `cardiac_stress` on day 9, then `fluid_overload` on day 10. On every other day it said `deconditioning`.
  - Pulse simulated both labels. `cardiac_stress` starts the Exercise action, and in continuous mode Exercise stays active in the saved engine state (§3).
  - The risk score went to MODERATE on day 9 (WATCH) and HIGH from day 10 to day 21, giving 12 ALERT days, first on day 10.
- **Persistence on:**
  - Neither label held for 6 days, so Pulse was given `deconditioning` on days 9 and 10.
  - Exercise was never started. Risk stayed LOW (score at most 0.008) for all 21 days, and the twin never alerted.
- **Interpretation:**
  - The flags-off alert on this seed came from a two-day label blip whose effect stayed in the carried-forward engine state. The classifier itself never labelled the following 11 days as anything but `deconditioning`.
  - Persistence did what it was designed to do and suppressed the blip. On this seed, though, that removed the only signal that caught a should_catch patient.
  - Seed by seed, P04 (current `decide_alert()` replay) is caught on 2 of 3 seeds without the flag (43 and 44) and on 1 of 3 with it (43 only).
  - Whether that alert was a correct detection or a lucky artifact can't be settled from this cohort: the injected deterioration is real, but the twin reached it through a mislabel.
- **Bottom line for this cohort:** with N = 6, scenario persistence removed no false alerts and cost one should_catch patient-seed its only alert. It is left **off by default**. The evidence does not support turning it on.
- **The other should_catch patients (P05–P07, P10)** and all should_stay_quiet patients (P01, P08, P09) had identical twin and ML alerts with and without the flag. Persistence removed no false alerts there, because none of their alerts depended on a short label change.

## 6. Live check: continuous mode with real Pulse

`scripts/verify_continuous_mode_live.py`, run in the backend image with `PIPELINE_MODE=continuous`, the frozen models, the real API routes, and the real `PulseScenarioDriver`.

Run on 2026-10-07 on this PC, in the image `m2k-hf-pulse-release-pulse-backend` with this branch mounted. Raw output: `results/live_checks/continuous_mode_live.json`. **Verdict: PASS, all 10 checks.**

| Run | Kind | Simulation time (s) | States saved | Wall time (s) | Result |
|---|---|---|---|---|---|
| 1 | initial (21st reading fills the window) | 660 | 1 | 333 | complete, deconditioning, severity 0.047 |
| 2 | resume | 1260 | 2 | 225 | complete, deconditioning, 0.048 |
| 3 | resume | 1860 | 3 | 254 | complete, deconditioning, 0.049 |
| 4 | resume | 2460 | 4 | 299 | complete, deconditioning, 0.053 |
| 5 | resume | 3060 | 5 | 427 | complete, deconditioning, 0.063 |
| — | `POST /reset-state` | — | 5 | — | twin-state shows `reset_pending: true` |
| 6 | initial (fresh start) | **660** | 6 | 456 | complete, deconditioning, 0.113 |

What the checks confirm:
- Each run saved a new, distinct engine state of about 2.33 MB.
- Each resumed run started from the previous run's saved state: +600 s per day, no failed days, `engine_lag_days` stayed 0.
- After the reset, the next run was an initial run back at 660 s with a new state start time.
- All 6 states, 6 runs and 6 assessments were kept.

Wall times include the 3 forward-projection Pulse runs the API does every day. The scenario harness skips those, so it makes 1 Pulse call per day instead of 4.
