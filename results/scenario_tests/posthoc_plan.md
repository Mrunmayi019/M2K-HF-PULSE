# Post-hoc analysis plan

**Written and committed BEFORE any post-hoc rule is computed**, per instruction. This plan is
separate from, and does not alter, the pre-registered `results/scenario_tests/expected_outcomes.md`
or the pre-registered `results/scenario_tests/RESULTS.md`. Everything below is read-only analysis
of the already-saved, frozen-harness CSVs (`results/scenario_tests/daily_results_*.csv`) -- no
re-simulation, no change to the harness, cohort, or schedules.

## Context: which "alert" this plan operates on

A prior check (Q1 of this follow-up) found that `RESULTS.md`'s pre-registered `alert_flag` column
(`current_alert.get("alert") == "alert"` from `src/analytics/score_reporting.py::alert_decision()`,
gated on `severity > 0.15`) is **real production code, but code the dashboard never actually
displays** -- every frontend component that shows risk/alert state reads `assessment.risk_bucket`
instead, which comes from a different function (`src/analytics/risk_score.py::compute_risk_score()`,
`risk_bucket == "HIGH"` when `risk_score >= 0.65`, `MODERATE_HIGH_BOUNDARY`). Full grep evidence and
the corrected headline numbers are in `results/scenario_tests/posthoc_followup.md`.

**Everything below (R1/R2/R3, "risk above threshold") refers to this system-facing definition:
`risk_score >= 0.65` per day, the same cutoff `risk_bucket == "HIGH"` uses.** Not the pre-registered
`alert_flag` column.

## Candidate rules

All three take the per-day boolean `today_risk_high = (risk_score >= 0.65)` as input (already in
the saved CSVs via `risk_score`; no recomputation of risk_score itself) and produce a smoothed
per-day `rule_alert`:

- **R1**: `rule_alert[day] = today_risk_high[day] AND today_risk_high[day-1]` -- alert only if risk
  is above threshold for 2 consecutive days.
- **R2**: `rule_alert[day] = today_risk_high[day] AND today_risk_high[day-1] AND today_risk_high[day-2]`
  -- alert only if risk is above threshold for 3 consecutive days.
- **R3**: `rule_alert[day] = mean(risk_score[day-2 .. day]) >= 0.65` -- alert only if the 3-day
  rolling mean of risk_score is above threshold. (Undefined for the first 2 days of any run;
  treated as `False` there, since there's no prior data to average.)

A **baseline** (`rule_alert[day] = today_risk_high[day]`, i.e. no smoothing at all -- the
system-definition alert from Q1/Q3, unmodified) is reported alongside R1/R2/R3 for comparison; it
is not itself a "post-hoc rule" since it adds nothing to what the real dashboard already does.

## What is reported for each rule (baseline, R1, R2, R3)

- **should_catch detection**: how many of the 5 should_catch patients (P04, P05, P06, P07, P10)
  alert in all 3 seeds under that rule, out of 5.
- **Mean lead time**: for should_catch patients that ARE detected, the first-alert day minus the
  story's own first scheduled event day, averaged across patients and the fastest seed per patient
  (consistent with how `analyze.py`'s `lead_time_days` is defined for the pre-registered table).
- **False alerts per 100 patient-days**: computed over the should_stay_quiet group (P01, P08, P09)
  only, same denominator convention as `analyze.py::false_alert_rate()`.

All three reported for the 21-day primary window (day-14 snapshot is not separately redone here;
the primary window is the one this follow-up's rule selection is based on).

## Selection criterion (written before computing any rule's result)

The chosen rule must, in this order:

1. **Preserve every should_catch detection the baseline (unsmoothed, system-definition) rule
   achieves.** A rule that trades away a real detection to cut false alerts is rejected outright,
   regardless of how good its false-alert number looks -- missing a should_catch patient is worse
   than tolerating extra false alerts in this cohort, since should_catch patients are the ones a
   clinical deterioration alert exists for.
2. Among rules satisfying (1), pick the one with the **fewest false alerts per 100 patient-days**
   in the should_stay_quiet group.
3. Ties broken by the **shorter mean lead time** across detected should_catch patients (faster
   detection preferred when false-alert rates are equal).

This criterion is fixed before any rule is run. If no rule satisfies (1), that is reported as a
finding (none of R1/R2/R3 improves on the baseline without cost), not grounds to invent a fourth
rule post-hoc.

## Confirmation run (proposed, not run as part of this plan)

Whichever rule is selected will be proposed for a confirmation run on fresh seeds (45, 46, 47),
same frozen harness, same 10 patients -- to check the rule holds on data it wasn't selected on.
Time estimate and the explicit "not started yet" statement are in
`results/scenario_tests/posthoc_followup.md` (§5), not here.
