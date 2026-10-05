# Follow-up analysis, 2026-10-07 (strict detection count; OOD check; day-1 step)

Read-only, from the already-saved scenario-test CSVs and the real classifier/regressor -- no new
Pulse runs, no code changes.

## 1. Strict recount: FIRST ALERT must be on/after perturbation start

**Confirmed exactly: 14/30** (P04=2, P05=1, P06=6, P07=0, P10=5), matching the numbers given.
Previously reported "21/30" used a looser rule (ANY alert day on/after perturbation start,
regardless of earlier false alerts) -- the two numbers measure different things and both stay in
the record, relabeled:

- **14/30 -- story-driven detections** (the series' own first-ever ALERT occurs on/after its
  perturbation start -- the correct metric for "did the story, not noise, cause this"). **This
  replaces every prior use of "21/30 story-driven."**
- **21/30 -- any ALERT on/after perturbation start** (kept as a separate, weaker metric: the
  series alerts at least once after the story starts, whether or not it also false-alerted
  earlier -- e.g. P07, which is 0/6 under the strict rule but 6/6 under this one).

Every prior document using "21/30 story-driven" (`docs/followup_analysis_2026-10-06.md`,
`docs/results_v1_offline_analyses.md` on `analysis/results-v1-offline`) has been corrected in
place -- see those files' own 2026-10-07 edits.

## 2. Is the scenario cohort out-of-distribution for the classifier?

**Yes, clearly, dominated by one feature: `ejection_fraction_pct`.** Built each of the 10
patients' monitored-day-1 feature vector from a FLAT, noiseless, zero-event 21-day window (their
own `baseline_wearable` values repeated, zero slope by construction) -- i.e. the generator's own
intended "nothing has happened yet" state, before any harness noise, day-1 step (§3), or story.
Fed through the real `build_inference_features()`/frozen classifier (`src/evaluation/
scenario_tests/ood_check.py`).

**Result: 4 of 10 patients (P01, P02, P03, P04) are predicted `deconditioning` from this
baseline alone** -- P05-P10 predict `stable` correctly:

| patient | EF | predicted (flat baseline) | z(EF) vs. training `stable` |
|---|---|---|---|
| P01 | 48 | deconditioning | -3.44 |
| P02 | 49 | deconditioning | -3.18 |
| P03 | 50 | deconditioning | -2.92 |
| P04 | 51 | deconditioning | -2.66 |
| P05 | 52 | **stable** | -2.40 |
| P06 | 53 | stable | -2.14 |
| P07 | 54 | stable | -1.88 |
| P08 | 55 | stable | -1.62 |
| P09 | 56 | stable | -1.36 |
| P10 | 57 | stable | -1.10 |

`ejection_fraction_pct` is the single largest-magnitude |z| feature for every one of the 10
patients (`results/scenario_tests/posthoc/ood_check.json` has the full per-feature z-scores).
**Training data, same real feature pipeline** (`build_features()` on `data/synthetic/
{patients,wearable_trends}.csv`):

| class | n | EF mean (sd) | EF range |
|---|---|---|---|
| `stable` | 400 | 61.21 (3.84) | 51.3 - 70.7 |
| `deconditioning` | 414 | 50.55 (8.02) | 26.3 - 75.0 |

**Amendment A's neutral EF band (48-57%, one point apart per patient) sits almost entirely
below the training `stable` class's own observed range, and nearly exactly on the
`deconditioning` class's mean.** The classifier's effective decision boundary for this
feature combination, on flat/zero-noise baseline alone, falls between EF 51 (P04,
`deconditioning`) and EF 52 (P05, `stable`) -- a 1-percentage-point margin, almost exactly
bisecting the cohort. This is the dominant, single-feature explanation for roughly half the
cohort's baseline misclassification, independent of noise, the day-1 step (§3), or any story
event -- all three of those are additional, compounding factors on top of this.

**Harness baseline levels vs. `generate_wearable_trends.py`'s own `stable`-patient generation**:
for a training `stable` patient, every vital except `weight_kg` is drawn once per patient from
`reference_stats.yaml`'s population `wearable_baseline` (mean/sd), then held flat (`curve` is
all-zero for `trend_mode="stable"`) with only population-scaled daily noise on top -- the exact
mechanism already confirmed for this project's own noise convention elsewhere in this
investigation. Comparing the scenario cohort's 10 `baseline_wearable` values against those same
population means (resting_hr_bpm 70/sd8, spo2_pct 97/sd1.2, steps_per_day 6000/sd2000,
hrv_rmssd_ms 35/sd12):

| vital | population mean (sd) | cohort mean | cohort range | notable outliers |
|---|---|---|---|---|
| resting_hr_bpm | 70 (8) | 72.4 | 60-82 | none >1.5sd |
| spo2_pct | 97 (1.2) | 96.0 | 93.5-98.0 | **P10 93.5 (-2.9sd), P07 94.0 (-2.5sd), P04 94.5 (-2.1sd)** |
| steps_per_day | 6000 (2000) | 6140 | 4200-8500 | none >1.2sd |
| hrv_rmssd_ms | 35 (12) | 32.4 | 24-45 | P10 24 (-0.9sd) |
| sleep_hours | 7.0 | 7.0 | 6.7-7.5 | none notable |

**SpO2 is the one vital with a real, systematic offset**: the cohort's baseline SpO2 (mean 96.0)
sits below the population mean (97.0), and P04/P07/P10 specifically are authored 2-3 SD below
it -- a deliberate "typical HF patient" choice, not a bug, but it independently pushes those same
three patients (already flagged in `docs/followup_analysis_2026-10-05.md`/`-06.md` for other
reasons -- largest day-1 HR/HRV steps, earliest Exercise triggers) further from the `stable`
training distribution on a second, separate feature.

## 3. The day-1 step: intended, not a harness artefact -- confirmed exact

**Not every patient has one.** Comparing each patient's `baseline_wearable` against
`monitored_day_schedule[0]` (both `severity_target=0.2`, `event=None` for all 10):

| patient | group | HR step | HRV step | steps/day step |
|---|---|---|---|---|
| P01 | should_stay_quiet | 0 | 0 | 0 |
| P02 | edge_case | 0 | 0 | 0 |
| P03 | edge_case | 0 | 0 | 0 |
| P04 | should_catch | +2.4 | -1.2 | 0 |
| P05 | should_catch | +1.6 | -1.0 | 0 |
| P06 | should_catch | +4.0 | -2.4 | -200 |
| P07 | should_catch | +5.0 | -3.0 | 0 |
| P08 | should_stay_quiet | 0 | 0 | 0 |
| **P09** | **should_stay_quiet** | **-2.0** | **+4.0** | **+2125** |
| P10 | should_catch | +5.0 | -3.0 | 0 |

**Confirmed exact: every should_catch patient's step equals `generate_wearable_trends.py`'s own
`SCENARIO_SIGNAL_DELTAS[<that patient's story scenario_type>] * 0.2`** (the flat
`severity_target` every patient starts at) -- not approximately, to the decimal:

| patient | story scenario_type | delta table HR/HRV (at severity 1.0) | x0.2 | observed step |
|---|---|---|---|---|
| P04 | fluid_overload | 12 / -6 | 2.4 / -1.2 | 2.4 / -1.2 (exact) |
| P05 | deconditioning | 8 / -5 | 1.6 / -1.0 | 1.6 / -1.0 (exact) |
| P06 | cardiac_stress | 20 / -12 | 4.0 / -2.4 | 4.0 / -2.4 (exact) |
| P07 | acute_deterioration | 25 / -15 | 5.0 / -3.0 | 5.0 / -3.0 (exact) |
| P10 | acute_deterioration | 25 / -15 | 5.0 / -3.0 | 5.0 / -3.0 (exact) |

**This is intended, documented-convention-consistent cohort authoring, not a harness artefact or
a deviation from `generate_wearable_trends.py`'s own convention -- it faithfully reuses that same
delta table, evaluated at each patient's own flat, pre-registered `severity_target=0.2` (the
"chronic condition baseline" every should_catch story starts from) instead of ramping from zero.**
`stable`-chronic patients (P01/P02/P03/P08) correctly get a zero step, since `generate_wearable_
trends.py` itself has no `SCENARIO_SIGNAL_DELTAS` entry for `"stable"` ("it never drifts").

**P09 is the one unexplained case.** Its step doesn't match any `SCENARIO_SIGNAL_DELTAS` entry
(none has a positive `steps_per_day` delta or shrinks HR while raising HRV -- every entry in that
table is severity-worsening by construction), and P09 is `should_stay_quiet`, not a should_catch
story that would use the table at all. The direction (steps up, HR down, HRV up -- all healthier)
is consistent with its own story ("Active, stable patient, light exercise alternate days"), so
this reads as a deliberate, separate, story-specific authoring choice for P09 specifically
(representing a day-1 activity level already higher than its resting `baseline_wearable`), not
the same mechanism as the should_catch group's step -- not confirmed against `build_cohort.py`'s
actual `schedule_p09` source in this pass (this check only compared cohort.yaml's two recorded
snapshots, not re-read the generating code); flagged as the one open item.

## Verdict: where is the mismatch -- harness or model?

**Both, in different places, and they compound:**

1. **The dominant driver is a cohort-authoring choice that was never checked against the
   trained model's own decision boundary** -- Amendment A's neutral EF band (48-57%) is a
   deliberate, approved fix for a real confound (EF matching severity), but nobody checked it
   against what the classifier actually learned "stable" to look like (EF 51.3-70.7, mean 61.2).
   It isn't a *documented-convention violation* -- no written convention specifies what EF a
   "stable" cohort patient should have -- but it is a mismatch between a harness choice and the
   model's real, trained distribution, and it's the single largest contributor found in this
   investigation (roughly half the cohort, from flat baseline alone, before anything else).
2. **The day-1 step (§3) is NOT a harness deviation -- it faithfully reuses the generator's own
   documented convention** (`SCENARIO_SIGNAL_DELTAS`), just evaluated at each patient's flat
   pre-registered baseline severity instead of zero. It is a real, intended, and correctly-
   implemented design choice that still has the side effect of giving the classifier a small
   early "sick" signal for should_catch patients specifically -- a consequence of a correct
   implementation, not a bug in it.
3. **One authored baseline value (SpO2) is a real population-level offset**, not matched to
   `generate_wearable_trends.py`'s own `stable`-patient population draw -- again a deliberate
   clinical choice (HF patients plausibly do run a bit low), not a documented-convention
   violation, but a further, independent push away from "stable" for the same 3 patients (P04,
   P07, P10) already flagged for other reasons.

Nothing here was fixed or rerun.
