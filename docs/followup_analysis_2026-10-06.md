# Follow-up analysis, 2026-10-06 (items 1-4)

Read-only, from the already-saved scenario-test CSVs -- no new Pulse runs, no code changes
(the two PR #5 additions are in a separate commit). Figures recomputed directly from the saved
`pulse_*`/`predicted_scenario`/`predicted_severity`/`risk_bucket` columns.

## 1. P07: ALERT from day 2-5, in all 6 seeds, before its own day-10 perturbation

**Reported as what it is: P07 is in ALERT before perturbation in every single seed.** Per
instruction, this is NOT counted as a detection in §4's restated numbers -- P07's genuine,
story-driven detection (first ALERT on/after day 10) is tracked separately and still holds in
all 6 seeds (confirmed, `followup_item1_{dev,heldout}.json`: `first_detect_ALERT_day=10` every
time) -- both things are true at once: a real pre-perturbation false alert, AND a real
post-perturbation detection.

Days 1-10, all 6 seeds:

| day | seed 42 | seed 43 | seed 44 | seed 45 | seed 46 | seed 47 |
|---|---|---|---|---|---|---|
| 1 | cardiac_stress/0.133/**Ex**/95.2/LOW | deconditioning/0.109/no/95.2/LOW | stable/0.054/no/95.2/LOW | stable/0.055/no/95.2/LOW | stable/0.088/no/95.2/LOW | stable/0.072/no/95.2/LOW |
| 2 | cardiac_stress/0.188/**Ex**/95.2/**HIGH** | deconditioning/0.176/no/95.2/LOW | cardiac_stress/0.124/**Ex**/95.2/MODERATE | deconditioning/0.133/no/95.2/LOW | deconditioning/0.185/no/95.2/LOW | deconditioning/0.140/no/95.2/LOW |
| 3 | cardiac_stress/0.235/**Ex**/63.7/**HIGH** | deconditioning/0.214/no/95.5/LOW | cardiac_stress/0.119/**Ex**/72.5/**HIGH** | deconditioning/0.181/no/95.5/LOW | deconditioning/0.214/no/95.5/LOW | cardiac_stress/0.179/**Ex**/95.5/**HIGH** |
| 4 | cardiac_stress/0.300/**Ex**/61.9/**HIGH** | deconditioning/0.212/no/95.2/LOW | cardiac_stress/0.181/**Ex**/75.4/MODERATE | cardiac_stress/0.248/**Ex**/95.2/**HIGH** | cardiac_stress/0.298/**Ex**/95.2/**HIGH** | cardiac_stress/0.217/**Ex**/63.9/**HIGH** |
| 5 | cardiac_stress/0.306/**Ex**/67.0/**HIGH** | cardiac_stress/0.219/**Ex**/95.3/**HIGH** | cardiac_stress/0.252/**Ex**/67.4/**HIGH** | cardiac_stress/0.251/**Ex**/57.6/**HIGH** | cardiac_stress/0.403/**Ex**/62.6/**HIGH** | cardiac_stress/0.231/**Ex**/63.6/**HIGH** |
| 6 | cardiac_stress/0.339/**Ex**/56.4/**HIGH** | deconditioning/0.255/no/60.7/**HIGH** | cardiac_stress/0.324/**Ex**/59.7/**HIGH** | cardiac_stress/0.304/**Ex**/65.1/**HIGH** | cardiac_stress/0.367/**Ex**/64.5/**HIGH** | cardiac_stress/0.262/**Ex**/64.1/**HIGH** |
| 7 | cardiac_stress/0.364/**Ex**/56.7/**HIGH** | cardiac_stress/0.289/**Ex**/63.7/**HIGH** | cardiac_stress/0.363/**Ex**/60.0/**HIGH** | deconditioning/0.507/no/67.2/**HIGH** | deconditioning/0.511/no/67.1/**HIGH** | cardiac_stress/0.291/**Ex**/57.2/**HIGH** |
| 8 | cardiac_stress/0.347/**Ex**/56.8/**HIGH** | cardiac_stress/0.326/**Ex**/67.5/**HIGH** | cardiac_stress/0.355/**Ex**/59.8/**HIGH** | cardiac_stress/0.310/**Ex**/60.2/**HIGH** | deconditioning/0.517/no/61.0/**HIGH** | cardiac_stress/0.307/**Ex**/57.2/**HIGH** |
| 9 | cardiac_stress/0.354/**Ex**/56.8/**HIGH** | cardiac_stress/0.318/**Ex**/57.1/**HIGH** | cardiac_stress/0.311/**Ex**/59.8/**HIGH** | deconditioning/0.316/no/60.0/**HIGH** | deconditioning/0.515/no/60.6/**HIGH** | cardiac_stress/0.258/**Ex**/57.2/**HIGH** |
| 10 | cardiac_stress/0.421/**Ex**/56.5/**HIGH** | cardiac_stress/0.384/**Ex**/57.2/**HIGH** | cardiac_stress/0.359/**Ex**/59.9/**HIGH** | deconditioning/0.502/no/60.4/**HIGH** | deconditioning/0.513/no/60.9/**HIGH** | deconditioning/0.323/no/57.3/**HIGH** |

(format: predicted_scenario/predicted_severity/Exercise fired/map_start/risk_bucket)

**What produces this**: P07's own authored day-1 schedule is already stepped up from its
`baseline_wearable` -- resting HR 80 -> 85 (+5bpm), HRV 27 -> 24ms (-3ms) -- present on day 1
itself, before any designed event (P07's `event` field is `None` for days 1-9; the `acute_onset`
event doesn't start until day 10). This step is not noise; it's in `cohort.yaml`'s own authored
schedule, identical in every seed. **Checked against the other 4 should_catch patients' own
day-1-vs-baseline steps, the mechanism is quantitative, not unique to P07**:

| patient | HR step (baseline -> day 1) | HRV step | reaches HIGH in all 6 seeds? |
|---|---|---|---|
| P05 | +1.6 bpm | -1.0 ms | never (0/6) |
| P04 | +2.4 bpm | -1.2 ms | 3/6 |
| P06 | +4.0 bpm | -2.4 ms | 6/6 (but no pre-perturbation ALERT -- its own perturbation starts day 4, close to day 1) |
| **P07** | **+5.0 bpm** | **-3.0 ms** | 6/6, **with ALERT starting day 2-5 -- 5-9 days before its day-10 perturbation** |
| P10 | +5.0 bpm (tied largest) | -3.0 ms (tied largest) | 6/6 |

P07 and P10 share the largest day-1 steps of the five should_catch patients. The classifier's
rolling-window trend features (first7mean/last7mean delta/slope) pick this step up as a genuine
HR-up/HRV-down trend from day 1 -- the same direction `cardiac_stress` training examples show --
regardless of noise realization, which is why it reproduces in every one of P07's 6 seeds rather
than being seed-dependent like P04's. **P07's unusually long gap between its designed
perturbation (day 10) and the earliest point its own baseline step could plausibly be felt (day
1) is what turns this into a sustained pre-perturbation false ALERT specifically for P07, not
just an early-but-still-pre-perturbation blip.**

## 2. Scenario label accuracy: scenario-test cohort vs. the 91.33% ML test-set accuracy

Day-by-day `predicted_scenario` vs. each patient's pre-registered expected label, all 10
patients x 6 seeds (1260 patient-days):

| patient | expected | days | matched | accuracy | predicted-label distribution |
|---|---|---|---|---|---|
| P01 | stable | 126 | 0 | 0.000 | deconditioning:122, cardiac_stress:4 |
| P02 | stable | 126 | 0 | 0.000 | deconditioning:118, fluid_overload:7, cardiac_stress:1 |
| P03 | stable | 126 | 0 | 0.000 | deconditioning:99, fluid_overload:27 |
| P04 | fluid_overload | 126 | 3 | 0.024 | deconditioning:113, cardiac_stress:10, fluid_overload:3 |
| P05 | deconditioning | 126 | 105 | 0.833 | deconditioning:105, stable:20, cardiac_stress:1 |
| P06 | cardiac_stress | 126 | 59 | 0.468 | deconditioning:57, cardiac_stress:59, stable:10 |
| P07 | acute_deterioration | 126 | 0 | 0.000 | deconditioning:83, cardiac_stress:39, stable:4 |
| P08 | stable | 126 | 37 | 0.294 | cardiac_stress:66, stable:37, deconditioning:23 |
| P09 | stable | 126 | 7 | 0.056 | deconditioning:118, stable:7, cardiac_stress:1 |
| P10 | acute_deterioration | 126 | 11 | 0.087 | deconditioning:63, cardiac_stress:43, acute_deterioration:11, stable:9 |

**Overall scenario-test label accuracy: 222/1260 = 17.62%.**

| metric | value | what it measures |
|---|---|---|
| ML Model 1 test-set accuracy (`results/results_v1_offline/ml_metrics.json`) | **91.33%** | single cross-sectional snapshot per held-out synthetic patient, i.i.d. with training distribution |
| Scenario-test cohort label accuracy (this table) | **17.62%** | day-by-day, rolling 21-day window, applied to 10 authored story trajectories across 6 seeds each |

**These are not comparable claims about the same thing, and the gap is the headline finding
itself, not a contradiction.** The 91.33% figure describes the classifier's accuracy on data
shaped like what it was trained on (one row per patient, drawn from the same generator). The
17.62% figure describes accuracy on a fundamentally different task: a continuously-updating
rolling window walking through hand-authored day-by-day trajectories (including the deliberate
day-1 baseline steps in §1, multi-day events, and the carried-forward Pulse state mechanism
documented throughout this investigation) -- out-of-distribution relative to how the training
rows were generated. `deconditioning` is over-predicted almost everywhere (dominant or
co-dominant for 8 of 10 patients) -- the same "label collapse" finding `RESULTS.md` §6 already
flagged, now quantified precisely against the formal ML metric it should be read alongside.

## 3. P01 seed 47, day 5: Exercise intensity

`src/pulse_runner/cli_state_scenario.py::build_exercise_action(scenario_type, severity)`:
```python
factor = EXERCISE_SCENARIO_INTENSITY_FACTOR.get(scenario_type)  # cardiac_stress -> 1.0
return scenario_file._exercise_action(severity * factor)
```
Day 5: `predicted_scenario="cardiac_stress"` (factor 1.0), `predicted_severity=0.097` ->
raw intensity = `0.097 * 1.0 = 0.097`.

`src/patient_builder/scenario_file.py::_exercise_action(intensity)`:
```python
intensity = max(0.1, min(intensity, MAX_EXERCISE_INTENSITY))  # MAX_EXERCISE_INTENSITY = 0.5
```
**0.097 is below the floor, so the actual issued intensity is clamped up to 0.1, not 0.097.**

**Is intensity scaled by severity?** Yes -- linearly, before the floor/ceiling clamp:
`intensity = severity * EXERCISE_SCENARIO_INTENSITY_FACTOR[scenario_type]` (factor 1.0 for
`cardiac_stress`, 0.6 for `acute_deterioration`).

**Is there a minimum severity below which Exercise doesn't fire at all?** No. `build_exercise_
action()` only returns `None` when `scenario_type` isn't `cardiac_stress`/`acute_deterioration`
-- there is no severity-based gate. But there IS a minimum *intensity* floor (0.1) applied
unconditionally once it does fire: **any `cardiac_stress`/`acute_deterioration` prediction, no
matter how low the severity (even near 0), issues an Exercise action of at least 0.1 intensity
-- severity scaling only has room to matter above `0.1/factor` (0.1 for `cardiac_stress`, ~0.167
for `acute_deterioration`).** Report only; not changed.

## 4. Restated: per-series counts (not "all seeds must agree")

**Correction (2026-10-07): this section originally reported 21/30 and called it "story-driven
detections." That number is actually "any ALERT on/after perturbation start" (a looser measure --
it doesn't check whether the series ALSO false-alerted earlier). The correct story-driven
count, under the strict rule (the series' own FIRST-EVER ALERT must be on/after perturbation
start), is 14/30 -- see `docs/followup_analysis_2026-10-07.md` item 1, which is now the
authoritative number. Both are kept below, correctly labelled.**

Using the real `decide_alert()` output (not the raw `risk_bucket` shortcut
`weight_sensitivity.py` used for its own, different purpose):

- **should_catch, story-driven detections (series' first-ever ALERT is on/after its own
  perturbation start): 14/30 patient-seed series** (5 patients x 6 seeds) -- P06 6/6, P10 5/6,
  P04 2/6, P05 1/6, P07 **0/6** (P07's early false ALERT, §1, disqualifies every one of its 6
  seeds from this strict count, even though all 6 also show a genuine post-day-10 ALERT).
- **should_catch, any ALERT on/after perturbation start (weaker -- ignores earlier false
  alerts): 21/30 patient-seed series.** P06, P07, P10: 6/6 each. P04: 2/6. P05: 1/6.
  *(Corrected 2026-10-09: this line previously read P04 3/6, P05 0/6. Recomputed from the saved
  per-seed CSVs, seeds 42-47: P04 first alerts on days 8 and 10 in 2 seeds; P05 on day 6 in 1
  seed. The total, 21/30, was already right.)*
- **should_stay_quiet, series with any ALERT (any day): 8/18 patient-seed series** (3 patients x
  6 seeds). P08: 6/6 (every seed). P01: 1/6 (seed 47 only). P09: 1/6 (seed 47 only).

The 21/30 "any ALERT on/after perturbation start" figure cross-checks against `results/
results_v1_offline/weight_sensitivity.json`'s baseline (21/30, 8/18, computed independently via
raw `risk_bucket=="HIGH"` rather than `decide_alert()`) -- same numbers both ways in this
dataset, confirming C3's downgrades never change whether a series ever reaches `ALERT` at all
(C3 only trims how many *consecutive* days a streak stays `ALERT` once it starts,
§`alert_fix_plan.md`), only the per-day WATCH/ALERT split within a series that does. The strict
14/30 figure was not itself cross-checked against that file, since `weight_sensitivity.py` never
computed the strict "first ever ALERT" condition at all.
