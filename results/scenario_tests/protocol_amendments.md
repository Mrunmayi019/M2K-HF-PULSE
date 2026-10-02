# Protocol amendment log

Timestamped record of deviations from the original scenario-test brief, with reasons. The
pre-registered cohort/expectations in `expected_outcomes.md` are NOT edited in place; this file
records what changed and why, so the original pre-registration stays an honest historical record.

---

## 2026-10-03: Pilot (P10, seed 42) run; full batch started then stopped before any job completed

**What happened:** the pilot (P10, seed 42) was run to completion per the brief (§3) — 21/21
days processed, 8 failed (days 9-16, real Pulse crash-zone instability), fully recovered from day
17. Full results and analysis are in `RESULTS.md` §3, kept and reported as an observation, not
discarded.

The full batch (10 patients x 3 seeds, N=6 parallel) was then launched. **It was stopped before
any of the first 6 concurrent jobs completed a single monitored day** (confirmed via live process
inspection: all 6 were still mid-day-1, ~2 minutes in). No partial `daily_results_*.csv` files
were written by the batch; only the pilot's own CSV exists. Nothing from the batch needs to be
discarded because nothing from the batch was produced.

**Why stopped:** the pilot showed predicted severity reaching 0.81-0.90 by day 2 — far above the
story's injected target (0.20, ramping only from day 4) — raising the question of whether the
cohort's pre-registered patient *profiles* (not just their stories) were confounding the test.
Investigated before any further runs, per instruction.

---

### Q1: How does `severity_injected` actually enter the pipeline? Does Pulse run on our injected severity, or the classifier's own prediction?

**`severity_injected` (cohort.yaml's `severity_target`) only ever shapes the synthetic wearable
stream. It is never passed to Pulse, and never passed to the classifier. Pulse runs entirely on
the classifier's own independently predicted `scenario_type`/`severity`.**

Exact code path, `src/api/continuous_state_pipeline.py::run_daily_continuous_pipeline()`:

```
line 214: scenario_type = str(clf.predict(features_df[cols])[0])
line 215: severity = float(reg.predict(features_df[cols])[0])
...
line 240: new_state_json, snap, df = run_initial(..., severity=severity, ...)      # first day
line 248: new_state_json, snap, df = resume_and_advance(..., severity=severity, ...)  # later days
```

`features_df` (line 214) comes entirely from `build_inference_features(ml_row, trends_df)`, where
`trends_df` is the patient's real, already-stored `WearableReading` rows for the rolling 21-day
window (`get_wearable_window()`). **`severity_injected`/`severity_target` does not appear anywhere
in `src/api/`, `src/pulse_runner/`, or `src/analytics/`** — confirmed by grep, zero hits. It exists
only in `config/scenario_tests/cohort.yaml` and the test harness
(`src/evaluation/scenario_tests/run_patient_seed.py`), where it is read once, by my own
`build_cohort.py` schedule functions, to compute that day's `resting_hr_bpm`/`steps_per_day`/etc.
wearable values — the only channel through which it can possibly influence anything downstream.

This is as-designed (Hard Rule 1 explicitly requires using the real
`run_daily_continuous_pipeline()`, not a bypass) — the classifier is meant to be exercised for
real, not fed an answer key. The consequence, confirmed below, is that the classifier's own
prediction can diverge sharply from the intended story, and when it does, that divergence is a
real finding about the classifier, not a test-harness bug.

---

### Q2: Patient profiles — how assigned, and was P10's sick baseline deliberate?

| # | Story | Group | Age | Sex | Height | Weight | EF% | BNP |
|---|---|---|---|---|---|---|---|---|
| P01 | Stable, ordinary life | should_stay_quiet | 58 | F | 162 | 70 | 64 | 90 |
| P02 | Salty weekend | edge_case | 50 | M | 178 | 88 | 60 | 110 |
| P03 | Slow, quiet weight gain | edge_case | 75 | F | 158 | 68 | 58 | 180 |
| P04 | Fluid overload building up | should_catch | 70 | M | 170 | 95 | 30 | 650 |
| P05 | Gradual deconditioning | should_catch | 82 | F | 155 | 60 | 55 | 320 |
| P06 | Cardiac stress | should_catch | 60 | M | 180 | 100 | 58 | 280 |
| P07 | Sudden deterioration | should_catch | 68 | F | 165 | 80 | 28 | 700 |
| P08 | Stressful fortnight, healthy heart | should_stay_quiet | 45 | M | 175 | 82 | 65 | 80 |
| P09 | Active, stable | should_stay_quiet | 52 | F | 168 | 65 | 66 | 70 |
| P10 | Everything goes wrong | should_catch | 73 | M | 172 | 92 | 25 | 900 |

**Deliberate, not accidental — and a design error.** I assigned each patient's EF/BNP to match
this project's own existing `SCENARIO_EF_PROFILE` convention (`src/data_synthesis/
generate_patients.py`: `stable`/healthy-heart stories -> EF ~62-66 "healthy" profile;
`cardiac_stress`/`deconditioning` -> EF ~55-58 "hfpef" profile; `fluid_overload`/
`acute_deterioration` -> EF ~25-30 "hfref" profile), and specifically chose **P10's EF/BNP to be
the single sickest in the cohort because its story ("everything goes wrong") was the most severe
narratively** — reasoning, in the moment, "the worst story deserves the worst baseline." That
reasoning is exactly backwards for what this test needs: it makes every `should_catch` patient
sicker *at baseline*, not just sicker *in trajectory*, so the test cannot separate "did the
pipeline catch the story" from "did the pipeline catch the baseline." Owning this directly: it was
my error, not a tooling or data limitation.

---

### Q3: What actually drove predicted severity to 0.81-0.90? (offline recomputation on saved P10 data, no new Pulse runs)

**Not EF/BNP — confirmed directly, not assumed.** Re-ran `build_inference_features()` +
`severity_regressor.predict()` on P10's own saved day-2 and day-6 wearable history, swapping only
EF/BNP, wearable trend held fixed:

| Day | EF=25, BNP=900 (real P10) | EF=45, BNP=300 (mid-range) | EF=60, BNP=100 (healthy-ish) |
|---|---|---|---|
| 2 | 0.4641 | 0.4634 | 0.4561 |
| 6 | 0.6075 | 0.6165 | 0.6107 |

**Swinging EF across its entire clinical range (25->60) and BNP across its entire range
(900->100) changes predicted severity by at most 0.008-0.009 at these points.** The regressor's
own `feature_importances_` confirm this directly, not just for these two points:

| Feature | Importance |
|---|---|
| `resting_hr_bpm_delta` | 0.318 |
| `resting_hr_bpm_slope` | 0.314 |
| `steps_per_day_slope` | 0.192 |
| `steps_per_day_delta` | 0.080 |
| `weight_kg_slope` | 0.028 |
| `weight_kg_delta` | 0.016 |
| `hrv_rmssd_ms_slope` | 0.008 |
| `spo2_pct_slope` | 0.007 |
| `spo2_pct_delta` | 0.007 |
| `ejection_fraction_pct` | **0.006** |

`ejection_fraction_pct` is 10th out of ~29 features; `nt_probnp_pg_ml` doesn't appear in the top
10 at all. **HR trend (63.2% combined) and steps trend (27.2% combined) drive essentially the
entire prediction.**

**A second, more consequential finding, not asked for directly but found while tracing this:** the
`resting_hr_bpm`/`steps_per_day` *features* are a `_delta`/`_slope` computed over the full rolling
21-day window (first-7-day mean vs. last-7-day mean, and a linear fit across all 21 points --
`src/scenario_classifier/features.py::_wearable_features()`). My own hand-authored schedule
(`build_cohort.py`) introduces **discrete, same-day step changes** (e.g., P10's steps cut exactly
50% starting day 4, in one step, not a ramp) to implement "from day 4: ... steps -50%" as written.
By day 6 of monitoring, the rolling 21-day window holds 18 days at the old baseline and only 3 at
the new, halved level -- a sharp step-function shape **the population training data
(`generate_wearable_trends.py::_trend_curve()`) never produces** (that generator only ever outputs
a smooth `frac` or `frac**2` curve across the *entire* window, never a mid-window discontinuity).
This is a real, separate confound from the EF/BNP question: my schedule's sudden-onset shape is
likely out-of-distribution for what the regressor was trained on, which plausibly explains
*why* a modest injected severity (0.20-0.35) produces an extreme, erratic predicted severity
(0.46-0.90) better than the EF/BNP hypothesis does (which the table above rules out almost
entirely). Addressed in the proposal below.

---

## Proposed revised design (NOT applied — awaiting approval)

### A. Neutral EF/BNP band

Spread EF 48-57% and BNP 200-290 pg/mL evenly across the 10 patients, assigned in patient-ID order
(P01->48/200, P02->49/210, ..., P10->57/290) -- **not** sorted by `expected_group`, so no group is
systematically sicker at baseline. This band sits deliberately between the generator's own
`hfref` ceiling (EF<=40) and `hfpef` floor (EF>=50), and above the `bnp_stage_b_threshold_pg_ml`
(35) by a wide margin without reaching any `nt_probnp_cutoff_pg_ml` age-banded cutoff (450/900/1800)
-- a genuinely "moderate, non-diagnostic" baseline by this project's own reference thresholds
(`src/data_synthesis/reference_stats.yaml`), not an arbitrary pick.

**Day-1 predicted severity under this band, computed offline for real** (each patient's own real
age/sex/weight/height/day-1 wearable schedule, only EF/BNP changed):

| Patient | Group | EF | BNP | Day-1 predicted scenario | Day-1 predicted severity |
|---|---|---|---|---|---|
| P01 | should_stay_quiet | 48 | 200 | deconditioning | 0.0622 |
| P02 | edge_case | 49 | 210 | deconditioning | 0.0544 |
| P03 | edge_case | 50 | 220 | deconditioning | 0.0454 |
| P04 | should_catch | 51 | 230 | deconditioning | 0.0464 |
| P05 | should_catch | 52 | 240 | stable | 0.0586 |
| P06 | should_catch | 53 | 250 | stable | 0.0554 |
| P07 | should_catch | 54 | 260 | stable | 0.0500 |
| P08 | should_stay_quiet | 55 | 270 | stable | 0.0841 |
| P09 | should_stay_quiet | 56 | 280 | stable | 0.0958 |
| P10 | should_catch | 57 | 290 | stable | 0.0533 |

All 10 patients start low (0.045-0.096) with **no group-based pattern** -- `should_catch` patients
are not systematically higher than `should_stay_quiet` ones at day 1. Whatever divergence appears
over the following 20 days will be attributable to each patient's *story* (the wearable trend
shape), not their starting clinical profile.

**Honest caveat, following directly from Q3's evidence:** because EF/BNP carry so little weight in
this model (<1% combined importance), neutralizing them removes a real confound and is the
methodologically correct fix -- but the evidence above says it will **not**, by itself, prevent
another P10-style extreme over-prediction, since that was driven by HR/steps trend shape, not
baseline EF/BNP. Recommending as a **second, complementary** change: author every patient's
wearable-trend transitions as gradual ramps over several days (matching `_trend_curve()`'s smooth
`frac`/`frac**2` style this project's own training data uses), not single-day step functions, even
where the brief's prose describes a threshold-style change (e.g., "from day 10 steps fall ~30%" ->
ramp from day 8-10 rather than a cliff exactly at day 10). This keeps every patient's wearable
inputs inside the shape of data the regressor was actually trained on.

### B. Are the severity caps (<=0.40 / <=0.45 / <=0.55) actually enforceable?

**Not as rules, on the evidence above.** The caps describe `severity_target` (what the story
*intends*) -- they say nothing about what the classifier actually predicts, and §Q3 shows the
classifier's own prediction can run to 0.81-0.90 regardless of a much lower injected target,
driven by wearable-trend shape the test harness controls but didn't, in this first attempt, keep
inside the training distribution. Even with fix A+B above, nothing in the real pipeline
*mechanically prevents* the classifier from predicting a severity that lands in the documented
Pulse crash zone -- the classifier was never designed or constrained to respect these caps; it
predicts whatever its training data says 21 days of wearable numbers imply.

**Recommended framing going forward:** treat the caps as **expected-range notes**, not hard rules
-- document them as what each story *intends*, report the classifier's *actual* predicted severity
honestly alongside it (exactly as `daily_results.csv`'s `severity_injected` vs. `predicted_severity`
columns already do), and **treat any resulting crash-zone entry and Pulse failure as a reportable
finding about classifier calibration, not a test-harness defect to engineer away.** This matches
Hard Rule 1 exactly ("mismatches are findings") and is consistent with how the pilot's own 8-day
failure streak was already handled and reported, not hidden.

---

**Stopping here per instruction**, pending approval of design changes A (neutral EF/BNP band) and
B (smoother transition shapes) before any rerun.
