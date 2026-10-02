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

## 2026-10-03 (continued): A and B approved and implemented

**A approved as proposed** — implemented exactly: EF 48-57% / BNP 200-290 pg/mL, assigned in
patient-ID order (P01->48/200 ... P10->57/290), in `src/evaluation/scenario_tests/build_cohort.py`.

**B approved with a limit: fix authoring artifacts, don't remove realistic sudden events.**
Implemented via two new helpers, `_ramp()` (two-point linear phase-in) and `_piecewise_ramp()`
(phase-in through several successive plateaus), replacing single-day cliffs with 2-3 day
transitions:

| Patient | What changed | What stayed sudden (unchanged) |
|---|---|---|
| P02 | nothing -- already a 3-day peak (days 5-7) as written | weight gain over days 5-7, exactly as originally written |
| P03 | nothing -- weight creep was already a smooth linear day-over-day ramp | -- |
| P04 | steps -30% now phases in over days 9-11 (was a cliff at day 10); poor-sleep onset now phases in over days 13-15 (was a cliff at day 14) | -- |
| P05 | each of the 3 step-reduction tiers (-20%/-40%/-60%) now transitions over ~2 days at its boundary (days 3-5, 8-10, 14-16) instead of switching instantly | -- |
| P06 | nothing -- severity/HR/HRV/steps were already continuous; exertion episodes are a genuine acute event | exertion episodes on days 6, 10, 14, 18 stay single-day |
| P07 | onset compressed to days 10-12 (3 days, per explicit instruction -- was 4 days, 10-13) and the steps drop now phases in over the same window | the onset is still realistically fast (3 days), not smoothed into a long ramp -- this is "sudden deterioration," not gradual |
| P08 | poor-sleep fortnight's onset (day 8) and recovery (by day 15) now phase in over ~2 days each | the 4 acute stress episodes (days 5, 9, 12, 16) stay single-day events |
| P09 | nothing -- no cliffs existed | -- |
| P10 | steps -50% now phases in over days 3-6 (was a cliff at day 4); poor-sleep onset/recovery now phases in over ~2 days each (was cliffs at day 8/day 14) | the 2 acute stress episodes (days 6, 10) stay single-day events |

**No predicted severity/risk/alert trajectory was previewed for any of these new schedules.** The
only offline check run was the day-1 baseline-severity table already shown above (§A) -- unaffected
by B, since all B changes take effect on day >=3 at the earliest and that table only used day-1
data. `cohort.yaml` regenerated and committed alongside this log entry, before any rerun.

**Severity caps are now explicitly expected-range notes, not rules** (per instruction) -- recorded
here so `RESULTS.md` can state this plainly rather than re-deriving it.

**New analysis-section commitments** (to be added to `analyze.py`/`RESULTS.md` §5, not yet run):
report both models' top-10 feature importances (confirming/updating the weight-importance finding
below for P02/P03's discussion); report the pilot explicitly as an observation demonstrating the
fallback alert working; report P02/P07/P08 specifically on how the system responded to their
(deliberately still-sudden) abrupt events.

Proceeding now to rerun the pilot (P10, seed 42).

## 2026-10-03: Pilot rerun result (P10, seed 42, amended cohort)

**21/21 days complete, 0 failed** -- a complete reversal of the pre-amendment pilot's 8-day crash
streak (days 9-16). Original kept as `daily_results_P10_seed42_pilot_v1_preamendment.csv` for
direct comparison. `simulation_time_s` stepped uniformly +600s across all 21 days, no gaps.
Day 1-2 predicted `stable` at severity 0.056-0.062 (matching the pre-registered day-1 offline
check, 0.0533, almost exactly) with no alert; alert correctly engaged from day 3 once
`deconditioning` severity crossed the threshold, and stayed on for the rest of the run as severity
climbed into the 0.76-0.91 range. One day (day 11) predicted `acute_deterioration` at severity
0.84 -- inside the documented crash-zone range -- and this time **completed without crashing**;
the system still correctly flagged it `unstable`/`alert_basis=classifier_only` regardless of the
successful completion, exactly as designed (a crash-zone parameter combination is untrusted
whether or not it happens to finish cleanly). Total wall time 17.3 min (vs. 12.0 min
pre-amendment -- expected, since nothing short-circuited via a fast ~8s failure this time).

**This confirms the amendment addressed the real problem**, not just this one patient's
particular crash: severity still climbs to a similarly extreme range late in the run (0.76-0.91,
not far from the original's 0.81-0.90) because P10's *story* genuinely is severe by day 21 -- but
the engine no longer crashes repeatedly getting there, and the one crash-zone day it does predict
completes cleanly instead of failing 8 times in a row.

---

## 2026-10-03: Two questions investigated before the full batch (from saved pilot data, no new runs)

### Q1: Day 3's alert -- P10's story starts day 4. Was it real? What drove it?

**Confirmed from the saved CSV: day 3's `event` column is empty (no story perturbation active
yet).** Days 1-5:

| Day | `event` | predicted_scenario | predicted_severity | risk | alert | wearable steps | wearable HR | wearable HRV |
|---|---|---|---|---|---|---|---|---|
| 1 | (none) | stable | 0.0557 | 0.0001 | False | 5154 | 85.87 | 23.98 |
| 2 | (none) | stable | 0.0624 | 0.0000 | False | 3571 | 84.06 | 28.94 |
| 3 | (none) | deconditioning | 0.1835 | 0.0050 | **True** | 6937 | 88.50 | 20.61 |
| 4 | everything_ramp | deconditioning | 0.2597 | 0.0036 | True | 4116 | 87.76 | 22.34 |
| 5 | everything_ramp | deconditioning | 0.2834 | 0.0035 | True | 3221 | 86.45 | 16.08 |

**The day-3 alert was real but not story-driven -- it was driven by noise in my own test
harness, not by P10's story (which hadn't started).** Steps swing 5154 -> 3571 -> 6937 across
days 1-3 purely from the noise layer (base target ~5400 throughout). Traced to the exact
mechanism: `src/evaluation/scenario_tests/run_patient_seed.py`'s noise SD for `steps_per_day`/
`hrv_rmssd_ms` was computed as `current_value * 0.15` (~810 for P10's steps, ~3.6-4 for HRV)
instead of `population_sd * 0.15` (300 / 1.8) -- the convention `generate_wearable_trends.py`
actually uses, and what the classifier/regressor were trained against. **2.7x oversized noise on
steps, ~2x on HRV -- precisely the two features with the highest combined regressor importance
(90.3%, `feature_importances.csv`).** This is a bug in the scenario-test runner (test code), not
real-pipeline behavior. **Fixed**: `NOISE_SD` now loads population SDs from `reference_stats.yaml`
for all five relative-noise vitals (HR/steps/HRV/SpO2/sleep), matching `generate_wearable_trends.
py` exactly; `WEIGHT_NOISE_SD_KG=0.3` is unchanged (your explicit instruction, not population-
derived). Confirmed new values: HR=1.2, steps=300.0, HRV=1.8, SpO2=0.18, sleep=0.15.

### Q2: Day 11's "classifier fallback that still completed" -- bug or real pipeline behavior?

**Real, deliberate, pre-existing pipeline behavior -- confirmed directly from source, not
inferred.** `src/analytics/score_reporting.py::determine_simulation_status()`'s own docstring
(lines 107-112):

> `"unstable"`: Pulse was invoked and EITHER failed OR landed in/near the documented crash zone
> (`is_known_unstable_configuration()`) -- checked regardless of whether the run happened to
> succeed. **A "lucky" success inside the crash zone is still not a reliable data point** (4/8
> failure rate documented in `docs/synthetic_deterioration_stress_test.md`); this function
> deliberately does not let a successful outcome override that.

Day 11 predicted `acute_deterioration` at severity 0.843 -- inside the documented crash-zone range
-- and Pulse happened to complete without error. `determine_simulation_status()` still returns
`"unstable"` for this case BY DESIGN (the code path above, not a special case I'm inferring), so
`build_score_report()`'s `alert_basis="classifier_only"` and my harness's `alert_source=
"unstable_fallback"` label follow directly and correctly from real, documented pipeline logic.
**Not a scenario-test-runner bug. Not changed, per instruction — not the pipeline's to touch.**

### Resolution

Q1 was a scenario-test-runner bug -- fixed as described, pilot rerun below. Q2 is expected,
documented real-pipeline behavior -- nothing changed. Proceeding to the full batch
(10 patients x 3 seeds, N=6 parallel) after the Q1-fix pilot rerun confirms sensible behavior.
