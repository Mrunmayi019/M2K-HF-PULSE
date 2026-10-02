# Pre-registered expected outcomes — scenario test

**Written and committed BEFORE any simulation was run.** Generated from `config/scenario_tests/
cohort.yaml` (same commit). Results-tag basis: `results-rc1` (provisional, unreviewed — PR #4 not
yet merged; see `docs/integration_pre_results.md`).

Framing (repeated in `RESULTS.md`): these tests check that the pipeline responds as designed to
controlled synthetic patient stories; they are not clinical validation. No claim of heart-failure
detection or diagnosis is made anywhere in this document or in the results it precedes.

**Amendment note (2026-10-03, full reasoning in `results/scenario_tests/protocol_amendments.md`):**
following the P10 pilot, `config/scenario_tests/cohort.yaml` was regenerated with (A) a neutral
EF/BNP band across all 10 patients (was previously matched to each story's severity, a confound)
and (B) smoother multi-day transitions for chronic/lifestyle changes that were previously
single-day cliffs (genuinely acute events were deliberately left sudden). **The expectations below
are unchanged from the original pre-registration** — they describe what each *story* is designed
to produce, independent of this baseline/authoring fix, and are not edited to match any observed
or anticipated result.

## Pre-registered groups

- **Should catch** (5): P04, P05, P06, P07, P10
- **Should stay quiet** (3): P01, P08, P09
- **Edge cases**, described individually, not scored against either group (2): P02, P03

## Per-patient expectation

| # | Story | Expected label | Expected alert behavior | Group |
|---|---|---|---|---|
| P01 | Stable patient, ordinary life | stable | No alert | should_stay_quiet |
| P02 | Salty weekend (wearable-only weight bump days 5-7, recovers by day 10) | stable or fluid_overload (brief) | Mild or no alert; settles after day 10 | edge_case |
| P03 | Slow, quiet weight gain (+0.3kg/day from day 4, wearable only, severity flat) | stable or fluid_overload (late) | Late alert or missed entirely | edge_case |
| P04 | Fluid overload building up (severity 0.20→0.50, days 4-21) | fluid_overload | Alert, labelled fluid_overload | should_catch |
| P05 | Gradual deconditioning (steps falling stepwise, severity 0.20→0.35) | deconditioning | Alert, labelled deconditioning | should_catch |
| P06 | Cardiac stress (severity 0.20→0.40, exertion episodes days 6/10/14/18) | cardiac_stress | Alert, labelled cardiac_stress | should_catch |
| P07 | Sudden deterioration (severity jumps 0.20→0.40 over days 10-13, held) | acute_deterioration | Fast alert after day 10, labelled acute_deterioration | should_catch |
| P08 | Stressful fortnight, healthy heart (acute stress + poor sleep days 5-16, severity flat 0.20) | stable (transient noise only) | Brief rises then recovery; no HF alert | should_stay_quiet |
| P09 | Active, stable patient (light exercise alternate days, severity flat 0.20) | stable | No alert | should_stay_quiet |
| P10 | Everything goes wrong (severity 0.20→0.45, weight/steps/stress/sleep all worsening) | acute_deterioration or fluid_overload | Earliest, strongest alert of the cohort | should_catch |

## Severity caps honored in this design (hard rule)

- ≤0.40 for `cardiac_stress` and `acute_deterioration` scenario *stories* (P06 peaks at 0.40, P07
  peaks at 0.40) — note these are the story's `severity_target`, not necessarily the classifier's
  own independently-predicted severity, which may differ (a finding, not an error).
- ≤0.45 for any patient with an Exercise-triggering event (P10 peaks at 0.45; P06 is itself capped
  at 0.40, both under the 0.45 ceiling for any Exercise-affected patient).
- ≤0.55 for everyone else (P04 peaks at 0.50, P05 at 0.35, all others flat at 0.20 — all comply).

## Primary vs. secondary analysis window (pre-registered)

- **Primary**: all 21 monitored days.
- **Secondary**: a day-14 snapshot read from the *same* runs (never re-simulated) — reported
  alongside the primary analysis for every applicable table, per `RESULTS.md` §9.

## Alerting rule for "counts as alerted" (pre-registered)

A patient counts as **alerted** only if it alerts in **all 3 seeds** (42, 43, 44). Any seed
disagreement is reported separately, not averaged away.

## What would make this test fail to discriminate as designed (pre-registered risk)

- If a `should_stay_quiet` patient (P01/P08/P09) alerts in all 3 seeds, that's a false alert —
  reported honestly, not re-tuned away (hard rule: no changing scorer/model/threshold logic to
  make results match these expectations).
- If a `should_catch` patient (P04/P05/P06/P07/P10) never alerts, that's a miss — same handling.
- P02/P03 are explicitly edge cases with no pass/fail criterion — their outcome is described, not
  scored.
