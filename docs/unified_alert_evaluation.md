# decide_alert() offline evaluation: ALERT/WATCH rates, dev vs. held-out

Offline, from the already-saved scenario-test CSVs (feature/scenario-testing) -- no new Pulse
runs, since `compute_risk_score()` itself is unchanged; only the alert/watch decision on top of
it is new. Script: `src/evaluation/scenario_tests/unified_alert_eval.py`, replaying the real
`compute_risk_score()` + `compute_baseline_high_streak()` + `decide_alert()` sequentially per
patient-seed-day -- the exact same functions now wired into the live pipeline, not
reimplemented for this evaluation. Full per-seed numbers:
`results/scenario_tests/posthoc/unified_alert_eval_{dev,heldout}.json`.

## should_catch (P04, P05, P06, P07, P10)

| | dev (42-44) | held-out (45-47) |
|---|---|---|
| reach ALERT in all 3 seeds | 3/5 | 3/5 |
| reach at least WATCH in all 3 seeds | 3/5 | 3/5 |

Identical to the pre-existing risk-scorer-alert finding (`results/scenario_tests/
alert_fix_results.md` / `alert_fix_results_heldout.md`) -- P06, P07, P10 reach ALERT in every
seed on both sets; **P04 and P05 reach neither ALERT nor even WATCH in all 3 seeds, on either
set.** This is the structural-limit finding (`scorer_diagnosis.md`, `docs/
decide_alert_preflight_analysis.md`) showing through unchanged: the WATCH tier cannot help a
patient whose `risk_score` never leaves `LOW` at all, and for P04 that's true in 2 of 3 seeds in
*both* seed sets (dev: seed 42; held-out: seeds 45, 46) -- see the per-seed note below for where
WATCH *does* add something, just not enough to move the "all 3 seeds" aggregate.

**Per-seed detail worth surfacing (not part of the pre-registered "all 3 seeds" metric, but a
real result of adding WATCH):** P04's held-out seed 47 -- previously invisible to any alert
signal at all (never reaches `HIGH`) -- now shows **20 of 21 days at WATCH**. This is the exact
case `docs/decide_alert_preflight_analysis.md`'s item (c) flagged in advance (23/126 P04
patient-days reach `MODERATE`, concentrated in this seed): the WATCH tier makes that visible for
the first time, even though it doesn't change the pre-registered "caught in all 3 seeds"
headline for P04.

## should_stay_quiet (P01, P08, P09)

| patient | dev: ALERT (all seeds) | dev: WATCH-or-ALERT (all seeds) | held-out: ALERT (all seeds) | held-out: WATCH-or-ALERT (all seeds) |
|---|---|---|---|---|
| P01 | False | False | False | False |
| P08 | **True** | True | **True** | True |
| P09 | False | False | False | False |

P01 and P09 remain correctly quiet in both seed sets -- confirmed at the WATCH level too, not
just ALERT (zero WATCH days anywhere for P09 in either set; P01 has some WATCH/ALERT days in
individual held-out seeds, see below, but never in all 3, so the aggregate stays False for both
levels).

**P08's false alert is substantially reduced in SEVERITY, not eliminated.** Per-seed:

| | dev seed 42 | dev seed 43 | dev seed 44 | held-out 45 | held-out 46 | held-out 47 |
|---|---|---|---|---|---|---|
| ALERT days | 3 | 3 | 5 | 3 | 3 | 3 |
| WATCH days | 8 | 10 | 12 | 10 | 14 | 14 |

**C3 is visibly firing, exactly as designed**: ALERT is capped at 3 days (dev seed 44's 5 is the
one exception -- see note below) in every seed, with the rest of what used to be a continuous
multi-day ALERT (`RESULTS.md` §7: P08 alerts for 8-14+ consecutive days per seed under the plain
risk-scorer definition) now reading as WATCH instead. The patient still shows elevated risk --
correctly, since the underlying `risk_score` genuinely is high -- but the urgency signal is no
longer repeated every single day for a signal that was never corroborated by `instability_flag`.
(Dev seed 44's 5 ALERT days instead of 3: a brief acute-dominant day resets the streak partway
through before baseline-only HIGH resumes, per `compute_baseline_high_streak()`'s own reset rule
-- not a bug, the same mechanism that protects a genuine re-escalation from being masked by an
old streak count.)

**New finding, not previously surfaced (dev-only checks never covered this): P01's held-out seed
47 reaches a sustained real `HIGH` with `instability_flag==1` on most of those days** (`map_end`
crashes to 46mmHg on day 10, then holds around 59-60mmHg -- below the 65mmHg instability
threshold -- through day 21). **C3 does NOT downgrade this one, correctly**: `instability_seen_in_
streak` is `True`, so the guard never fires, and it reads as a full 12-day ALERT. This is a
genuinely different situation from P08's mechanism (a real crash-zone-adjacent MAP, not a
baseline-only shift with no corroboration) -- whether a "should stay quiet" synthetic patient
crashing this hard in one noise draw is itself a cohort-authoring question is out of scope for
this alert-decision work; flagged here as newly observed, not something `decide_alert()`/C3 is
designed to or should suppress.

## Edge cases (P02, P03)

Neither reaches ALERT or WATCH in all 3 seeds, on either dev or held-out -- unchanged from the
pre-existing risk-scorer-alert finding; described, not scored, per the pre-registration.

## Takeaway

decide_alert() reproduces every should_catch/should_stay_quiet/edge_case pattern already found
and confirmed for the plain risk-scorer alert (same detections, same misses, same two false-alert
sources), while measurably reducing how often P08's one confirmed false alarm reads as urgent
(ALERT capped near 3 days per seed instead of running 8-14+ days continuously) and surfacing a
previously-invisible elevated case (P04 seed 47) as WATCH. It does not and cannot fix P04's/P05's
structural zero-signal misses, and it correctly does NOT suppress the newly-observed P01 seed 47
case, since that one has real corroborating instability.

## Note: WATCH is effectively always on for EF<=40 patients

Checked directly against the original 30-case `fluid_overload` validation dataset (`data/
simulation_runs/features_dataset.csv`, `docs/followup_analysis_2026-10-05.md` item 4): **29 of
29 EF<=40 cases reach at least `WATCH` (`risk_bucket` `MODERATE` or `HIGH`); the single EF>40
case does not (0/1).** This isn't a property of `decide_alert()` or C3 -- it's `ef_to_
cardiovascular_modifiers()`'s own `ChronicVentricularSystolicDysfunction` condition
(`HFREF_EF_THRESHOLD_PCT=40`) congesting `map_start` at construction time, which `baseline_
deficit_score` then reads directly. Worth stating plainly: for this scorer, **EF<=40 is, on this
evidence, close to a sufficient condition for at least a WATCH-level flag on its own**,
independent of anything the acute hemodynamic features or the ML severity classifier contribute.
Not evaluated here: whether this holds outside the 30-case dataset, or whether it's desirable
(a cheap, interpretable floor) or a liability (a patient at the boundary of this cutoff gets a
qualitatively different baseline regardless of how mild their actual presentation is).

## Both signals side by side (fix/alert-both-signals)

The API now returns the twin-based `alert` (`decide_alert()`, unchanged) **and** the ML-severity signal
`ml_severity_alert` (ML Model 1 severity > 0.15, the existing `STABLE_SEVERITY_CAP`, no new
threshold) on every assessment and on `/status`. `signals_disagree` is true when exactly one fires
(the twin fires at ALERT or WATCH; ML at ALERT). On failed or crash-zone runs the twin already falls
back to the same severity rule, so the two can't disagree there.

Offline replay on the saved scenario-test runs, seeds 42–47, all 10 patients
(`src/evaluation/scenario_tests/signal_disagreement_eval.py` →
`results/scenario_tests/posthoc/signal_disagreement.json`). It uses the real `compute_risk_score()`,
C3 streak, crash-zone status and `decide_alert()` per day, with no Pulse runs:

| Group | Patient-days | Disagree | ML flags, twin NONE | Twin flags, ML NONE | Disagree if the twin fires only at ALERT |
|---|---|---|---|---|---|
| should_catch (P04, P05, P06, P07, P10) | 630 | 155 (24.6%) | 144 | 11 | 285 (45.2%) |
| should_stay_quiet (P01, P08, P09) | 378 | 171 (45.2%) | 144 | 27 | 214 (56.6%) |
| edge_case (P02, P03) | 252 | 73 (29.0%) | 60 | 13 | 69 (27.4%) |
| **All** | **1,260** | **399 (31.7%)** | **348** | **51** | **568 (45.1%)** |

- **Disagreement is mostly one-directional.** In 348 of 399 days, the ML model flags the patient
  while the twin's risk score says NONE.
- **It's concentrated in a few patients:**
  - **P09** (should_stay_quiet): 118/126 days, ML ALERT, twin NONE.
  - **P05** (should_catch): 79/126 days, ML ALERT, twin NONE.
  - **P04** (should_catch): 55/126 days, ML ALERT, twin NONE.
  - **P02** (edge_case): 42/126 days, ML ALERT, twin NONE.
- **Neither signal is the right one on its own.** In the should_stay_quiet group the ML signal
  over-fires (ALERT on 227/378 days, 60%). In the should_catch group, 144 days are caught by the ML
  signal alone.
- **These are synthetic patients with unvalidated thresholds.** The numbers describe how the two
  signals behave relative to each other, not which is clinically correct.
