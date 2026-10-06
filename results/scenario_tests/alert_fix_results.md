# Alert fix: dev-seed evaluation and chosen candidate

Post-hoc. Candidates and selection rule were written and committed in `alert_fix_plan.md` before
this evaluation ran (`src/evaluation/scenario_tests/alert_fix_eval.py`, dev seeds 42-44, the same
saved CSVs as every other post-hoc analysis -- no new runs). Full numbers:
`results/scenario_tests/posthoc/alert_fix_eval_dev.json`.

## Dev-seed results (seeds 42-44)

| candidate | should_catch detected | false alerts / 100 patient-days (quiet group) | mean lead time |
|---|---|---|---|
| baseline (unsmoothed `risk_bucket=="HIGH"`) | 3/5 | 17.99 | -3.33 |
| C1 (persistence, 3 consecutive days >= 0.65) | 3/5 | 13.76 | -1.00 |
| C2 (two-level: HIGH unchanged + sustained-MODERATE watch) | 3/5 | 17.99 | -3.33 |
| **C3 (component guard: downgrade sustained baseline-only HIGH)** | **3/5** | **5.82** | -3.33 |

All four give the *identical* set of 3 detections -- {P06, P07, P10} -- confirmed per-patient, not
just by count (`should_catch_detail` in the JSON). P04 and P05 are missed by every candidate, as
the diagnosis predicted (§ `scorer_diagnosis.md`): neither ever has a nonzero signal for any
alert-side rule to act on, in any candidate. **C2 is exactly neutral**, as diagnosed (it only adds
a secondary "watch" tier, never changes the `HIGH` gate). **C1 reproduces the prior post-hoc
round's R2 result exactly** (13.76), as expected -- same rule, re-evaluated here as the persistence
comparator.

**C3 beats the plan's own prediction.** `alert_fix_plan.md` flagged a real risk that C3 would
suppress P04's true detections too, since P04 and P08 both show long `baseline_deficit`-dominant
runs with near-zero acute components. Checked empirically, not assumed: **P04's seeds 43/44 do
cross `instability_flag==1` (actual MAP<65 shock-range) at points within their `HIGH` streaks**
(e.g. seed 43 days 9-21, intermittently), so C3's guard never fires for P04. **P08's sustained
`HIGH` streak never crosses `instability_flag==1` in any seed** -- its elevated-but-not-shock-range
baseline deficit is exactly what C3 is built to catch, and the empirical difference between the
two patients turned out to be real, not illusory.

## Selection (per the pre-written rule in `alert_fix_plan.md`)

1. All four candidates preserve every baseline detection (P06, P07, P10) -- none eliminated.
2. Among those, **C3 has the fewest false alerts per 100 patient-days (5.82)** -- clearly ahead of
   C1 (13.76) and C2/baseline (17.99 each). No tiebreak needed.

**Chosen: C3.** It cuts the quiet-group false-alert rate by ~68% relative to the unsmoothed
system definition (17.99 -> 5.82 per 100 patient-days) -- more than double C1's improvement --
without costing any should_catch detection, and it is the only candidate of the three that
directly targets the diagnosed P08 mechanism (sustained `baseline_deficit` with no corroborating
acute/instability signal) rather than acting as a generic smoothing filter. It still does not
address P04-seed42 or P05 (no signal to act on, as diagnosed) -- those remain genuine misses this
alert-side fix cannot reach.

## Next: held-out confirmation (seeds 45-47)

Per instruction, C3 is evaluated once on fresh seeds 45-47 once that run completes --
`results/scenario_tests/alert_fix_results_heldout.md`, reported separately, development and
held-out numbers never blended.
