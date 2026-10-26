# Experiment 4 pre-registration: weekly re-baseline of the continuous twin

**Committed before any Experiment 4 Pulse run on the cohort.** The commit that adds this file is
the pre-registration. Experiments 1 and 2 and their results stay as they are. Experiment 3
(exercise stop) was abandoned before any job finished (local branch `exp3-abandoned`) and is not
reported. Experiment 4 is the next number so the abandoned one stays traceable.

Framing is the same as Experiments 1 and 2: this checks how the pipeline responds to controlled
synthetic patient stories. It is not clinical validation.

## 1. Question

In Experiment 2, 471 of 475 Pulse-HIGH days were decided by the baseline term (`map_start`), and
358 of the 475 had an end-of-encounter HR below 50 bpm. The cause is Pulse 4.3.1's baroreflex
set-point resetting. After exertion keeps MAP more than 5% off the set point for 420 s, the set
point moves toward MAP. The continuous pipeline's saved state carries the moved set point forward,
so the twin stays at MAP ~65 mmHg / HR ~45 bpm after exertion ends (paper §V-H;
`results/scenario_tests/diagnosis_baroreflex/` on `origin/paper/balanced-framing`).

`ENABLE_BASELINE_ANCHOR` (commit `0a1a1d5`) restarts the twin from the patient file once a state
chain holds 7 saved states. That day it also records the drift: resumed end minus fresh end.

**Experiment 4 asks two things.**
1. How large is the drift the continuous twin builds up in a week, and does it come only from
   exertion?
2. When the stuck state is cleared every week, how many of the twin's alert days go away, and do
   first-detection and false-alert results change?

## 2. What changes (and nothing else)

| | Experiment 2 (control arm) | Experiment 4 |
|---|---|---|
| `ENABLE_BASELINE_ANCHOR` | unset (off) | **1** |
| `BASELINE_REFRESH_DAYS` | n/a | **7** |
| Cohort | `cohort_exp2.yaml` | `cohort_exp4.yaml`: same `patients` block (identical, checked by the builder), `meta` adds `required_flags` |
| Seeds | 48–53 | **48–53** (same, so the wearable readings are identical day by day) |
| Max parallel jobs | 6 | 2 |

**Experiment 2's saved results are the control arm. They are not re-run.** System code is
unchanged since the Experiment 2 runs, apart from the flag: `git diff f353bd0 8ddcefa -- src backend
config requirements.txt docker-compose.yml` touches only `benchmark_scores.py` (MAGGIC, not called
by the pipeline) and `exp2_analyze.py`. With the flag on, nothing differs from Experiment 2 until
the first refresh: the anchor only records. Same models, Pulse image and package pins
(scikit-learn 1.9.0, numpy 2.4.6, pandas 3.0.6, checked in the image).

**Refresh timing.** The warm-up day starts the chain (state 1). Monitored days 1–6 are states 2–7.
Monitored day 7 is the first refresh, after its normal resumed run. Day 8 resumes from the fresh
state, and the next refreshes fall on days 14 and 21. A failed Pulse day saves no state, so it
delays that series' later refreshes by one day. The CSV records the real refresh days.

**Harness-only changes** (no system code): `run_patient_seed.py` refuses to start unless the flags
match `meta.required_flags`, and with the flag on it appends 14 columns (`ANCHOR_CSV_FIELDS`)
taken from `SimulationRun.baseline_anchor_json`/`exercise_applied`. `run_batch.py` reads
`SCENARIO_TEST_MAX_PARALLEL`. The scoring script, `exp4_analyze.py`, is committed with this file
and reuses `exp2_analyze.py`'s definitions unchanged.

## 3. Unchanged system (hard rule)

- Frozen results-v1 models (hash-checked at start), risk-scorer weights, thresholds,
  `decide_alert()`, C3 guard, classifier comparison threshold 0.55: unchanged.
- All other flags off. No scorer, model, threshold, story or flag change after results are seen.
  Any deviation goes in a dated amendment beside this file.

## 4. Integrity checks (must hold, or the result is reported as a harness/engine failure)

- **I1.** Classifier label and severity identical to Experiment 2 on all 1,260 patient-days. The
  classifier sees only the wearable readings, which are seeded and do not depend on Pulse.
- **I2.** Pulse output (`pulse_hr_end`, `pulse_map_end`, `pulse_co_end`, `risk_score`) identical
  to Experiment 2 on monitored days 1–7, since the first refresh happens after day 7's run. If
  Pulse is not bit-for-bit repeatable, the maximum difference is reported. The comparison then
  rests on I1 plus the refresh-day drift.
- **I3.** Refreshes due vs performed; any refresh errors are listed.

## 5. Outcomes

Definitions are those of Experiment 2 (`exp2_analyze.py`): should_catch = P04, P05, P06, P07, P10
(onset day 4); should_stay_quiet = P01, P08, P09; deployed system = `decide_alert()` ALERT. Failed
Pulse days count as no alert (primary), and are also reported counted as alerts.

**Primary**

- **P1. Drift on refresh days** (resumed end minus fresh end), split by the Exercise the chain
  carried. **A**: no Exercise in the chain before the refresh day and none that day. **B**:
  Exercise earlier in the chain, none on the refresh day. **C**: Exercise on the refresh day.
  Median and IQR of HR, MAP and CO drift, and the share of days with MAP drift ≤ −15 mmHg.
- **P2. Post-onset deployed alert days** in the 30 should_catch series (Experiment 2: 268).
- **P3. Experiment 2's headline outcomes, recomputed:** sensitivity, pre-onset alert rate,
  strict detection, false alerts per 100 patient-days, quiet series silent, and label accuracy.

**Secondary**

- **P4.** Pulse-HIGH days on days 8–21, should_catch and should_stay_quiet (Experiment 2: 330 and 71).
- **Reset-eligible check.** An Experiment 2 deployed alert day on days 8–21 is *reset-eligible*
  when the series had no exertion label from the day after the last refresh (day 7 or 14) through
  that day. That is a day the stuck state should no longer reach. Experiment 2 has 132 such days
  (all should_catch: P04 35, P05 15, P06 9, P07 46, P10 27) and 90 others. Report how many of each
  are still alerts in Experiment 4.
- **Stuck-state share.** Pulse-HIGH days with end HR < 50 bpm (Experiment 2: 358/475).
- **Anchor.** On Pulse-HIGH days, MAP drop against the chain baseline; share ≥ 20 mmHg.
- Per-patient alert days; refresh-day drift per patient.

## 6. Predictions (committed before the Pulse runs)

**How the numbers were derived (disclosed).** All predictions come from Experiment 2's saved
CSVs, the control arm, which were already public. Days 1–7 of Experiment 4 should equal
Experiment 2 (I2), so day 7's resumed values are already known. The fresh side is estimated from
each series' post-warm-up state (day-1 `pulse_*_start`: HR 71.2–72.3, MAP 94.5–95.4). Group sizes
from Experiment 2's labels (chain definition): A ≈ 123, B ≈ 38, C ≈ 19 of 180 refresh days.
Day-7 estimates: A HR −3.7 / MAP +0.3, B HR −23.3 / MAP −31.1, C HR −26.5 / MAP −27.4.

Before this file, the flag ran once on real Pulse: 4 days, one test patient from
`scripts/verify_continuous_state_pipeline.py`, refresh every 2 days, outside the cohort. That run
checked the mechanism only. No cohort patient or seed was run with the flag.

**Hypothesis.** The refresh clears the stuck state. The next day starts at MAP ~95 mmHg, so the
baseline term no longer fires. The state comes back only when a new exertion label applies
Exercise (Experiment 2: first HIGH 0–1 days after the first exertion label in most series). Every
first alert in Experiment 2 falls on or before day 7, and P08 keeps getting exertion labels.

| Outcome | Experiment 2 | **Predicted, Experiment 4** |
|---|---|---|
| I1 label/severity days differing | — | **0** |
| I2 Pulse days 1–7 differing | — | **0** |
| P1 group A: median MAP drift | — | **within ±3 mmHg** |
| P1 group A: median HR drift | — | **−10 to +3 bpm** |
| P1 group B: median MAP drift; share ≤ −15 mmHg | — | **≤ −15 mmHg; ≥ 75% of B days** |
| P1 group B: median HR drift | — | **≤ −10 bpm** |
| P1 group C: median MAP drift | — | **≤ −15 mmHg** |
| P2 post-onset deployed alert days, should_catch | 268 | **100–190** (estimate 136) |
| P3 sensitivity | 24/30 | **23–25/30** |
| P3 pre-onset alerts | 10.0/100, 7/30 | **unchanged (10.0/100, 7/30)** (days 1–3 are identical) |
| P3 strict detection | 17/30 | **16–18/30** |
| P3 false alerts / 100 patient-days | 4.8 | **3.0–6.0** |
| P3 quiet series silent | 12/18 | **12/18** (P01 6/6, P09 6/6, P08 0/6) |
| P3 label accuracy | 37.1% | **37.1%** (follows from I1) |
| P4 Pulse-HIGH days 8–21: should_catch / should_stay_quiet | 330 / 71 | **80–200 / 50–80** |
| Reset-eligible days still alerting | — | **≤ 20% of 132** |
| Other days (exertion since refresh) still alerting | — | **≥ 50% of 90** |
| Stuck-state share of HIGH days | 358/475 (75%) | **≥ 60%** (the HIGH days left are still the stuck state) |
| Anchor: HIGH days with MAP drop ≥ 20 mmHg vs baseline | — | **≥ 80%** |

**What each result would mean (committed now).**
- **P2 in range and P3 unchanged:** most of the twin's sustained alerting during an ongoing
  deterioration comes from the stuck engine state, not from simulated deterioration. First
  detection does not depend on it.
- **P2 near 268:** the refresh does not clear the state, or the state returns within a day without
  new exertion. The §V-H explanation would then be incomplete.
- **Group A drift outside ±3 mmHg:** the continuous twin drifts even without exertion, a separate
  problem from the baroreflex reset.

Any outcome is reported as found.

## 7. How it is run

On the same Mac (Apple Silicon, Docker Desktop, `linux/amd64` under emulation), from a checkout of
the commit that adds this file. All flags except the two below are unset.

```bash
cp artifacts/results-v1/models/*.joblib models/ && shasum -a 256 -c docs/results-v1-models.sha256
ENV="-e ENABLE_BASELINE_ANCHOR=1 -e BASELINE_REFRESH_DAYS=7 -e SCENARIO_TEST_COHORT=/workspace/config/scenario_tests/cohort_exp4.yaml"
# smoke test first: one dev-seed job (P06, seed 42) into a separate directory, never scored
docker run --rm --platform linux/amd64 -v "$PWD:/workspace" -w /workspace $ENV \
  -e SCENARIO_TEST_OUTPUT_DIR=/workspace/results/scenario_tests/exp4_smoke \
  m2k-hf-pulse-backend python -m src.evaluation.scenario_tests.run_patient_seed P06 42
# then the full batch
docker run --rm --platform linux/amd64 -v "$PWD:/workspace" -w /workspace $ENV \
  -e SCENARIO_TEST_OUTPUT_DIR=/workspace/results/scenario_tests/exp4 -e SCENARIO_TEST_MAX_PARALLEL=2 \
  m2k-hf-pulse-backend python -m src.evaluation.scenario_tests.run_batch
PYTHONPATH=. python3 -m src.evaluation.scenario_tests.exp4_analyze
```

The smoke test must print `Flag check: OK` with the anchor on, show a refresh on days 7, 14 and 21
(the `refresh_performed` column), and write its CSV before the batch starts. Its output is not
part of Experiment 4.

60 jobs (10 patients × seeds 48–53), at most 2 at a time. Each job is about 25 Pulse runs (1
warm-up, 21 days, 3 refreshes), and the batch is estimated at about 10 hours. Outputs:
`results/scenario_tests/exp4/daily_results_P??_seed??.csv`; logs in `exp4/logs/`; per-run SQLite
DBs in `exp4/dbs/` (gitignored). A job interrupted by sleep or overheating is rerun from day 1,
and the interruption is noted in the results file.
