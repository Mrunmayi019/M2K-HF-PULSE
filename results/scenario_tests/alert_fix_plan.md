# Alert fix plan

**Written and committed BEFORE computing any candidate's result**, per instruction. Based only on
the diagnosis in `results/scenario_tests/scorer_diagnosis.md` (committed alongside this file).
Post-hoc, analysis-only: no pipeline, scorer, or harness changes; no new simulation runs for this
plan's dev-seed evaluation (seeds 42-44, already-saved CSVs). A confirmation run on held-out seeds
45-47 is proposed separately once a candidate is chosen (§4).

## What the diagnosis actually supports

`compute_risk_score()` (`src/analytics/risk_score.py`) takes no `scenario_type` input at all --
it is five scenario-agnostic hemodynamic features (`hr_rise`, `map_drop`, `co_drop_pct`,
`compensation_flag`, `instability_flag`) plus a sixth, `map_start`-derived `baseline_deficit_score`
(`risk_score = max(acute_score, baseline_deficit_score)`). There is no code or comment anywhere
that down-weights "deconditioning" specifically -- it cannot, because the function never sees the
scenario label. The diagnosis instead shows two structurally different problems:

1. **P05 (deconditioning, missed in all 3 seeds): every single component is ~0.000 on every one
   of the 63 patient-days** -- `hr_rise`, `map_drop`, `co_drop_pct`, `instability_flag`,
   `compensation_flag`, AND `map_start` (never drops from its healthy baseline). Deconditioning's
   physiological signature (reduced activity) simply never produces an acute hemodynamic stress
   response or a baseline MAP deficit in Pulse's own simulated output -- there is no signal for
   any alert-side rule to act on. **No rule that only recombines/persists/gates the existing
   `risk_score` can create a detection where the underlying score is uniformly ~0** -- that would
   require a new Pulse-simulated signal or a new scorer component/weight, both out of scope here.

2. **P04 (fluid overload, missed in seed 42 only): `map_start` stays pinned at 94.7-96.2mmHg --
   above the healthy 92.5mmHg anchor -- for all 21 days**, while seeds 43/44 show `map_start`
   collapsing into the 70s-80s mmHg congested range by day 6-10, saturating
   `baseline_deficit_score` near 1.0 from then on. This is a genuine seed-dependent Pulse
   simulation outcome (the physiological trajectory itself never congests in this run) -- not a
   scorer-weighting problem, and not fixable by any alert-side rule for the same reason as (1): no
   signal to re-gate.

3. **P08 (stressful fortnight, should_stay_quiet, false-alerts continuously through day 21 in all
   3 seeds): a transient acute stress episode (`hr_rise`+`map_drop`+`compensation_flag` all
   nonzero, around days 5-11, matching the story's own stress episodes) pushes `map_start` down;
   `baseline_deficit_score` then saturates near 1.0 and **never decays back down for the rest of
   the 21-day window, in any seed**, even though the "stressful fortnight" story itself ends and
   its wearable inputs return to baseline. The continuous-state pipeline carries `map_start`
   forward day to day with nothing in this scorer that reduces `baseline_deficit_score` once
   triggered.

**Critical finding that limits every candidate below**: P08's sustained false `HIGH` and P04's
seeds-43/44 sustained TRUE `HIGH` are **indistinguishable in the scorer's own component space**
once `baseline_deficit_score` saturates -- both show `dominant_mechanism="baseline"` with every
acute component at ~0 for the rest of the run. Any rule that suppresses one will suppress the
other; this is checked empirically in §3, not assumed.

## Candidate fixes (each tied to a diagnosed cause above; no new threshold numbers)

- **C1 -- persistence (R2-style): alert only after risk_score >= 0.65 for 3 consecutive days.**
  Reuses the exact rule already selected in the prior post-hoc round
  (`results/scenario_tests/posthoc_plan.md`/`posthoc_followup.md`) as the baseline comparator
  here, since it's the one already-validated, zero-new-numbers persistence rule available.
  Targets short noise-driven flickers; **diagnosis predicts it does nothing for P08** (continuously
  `HIGH`, not flickering) **and nothing for P04-seed42/P05** (never crosses threshold at all).
- **C2 -- two-level alert using only existing buckets: `HIGH` = urgent alert (unchanged);
  `MODERATE` sustained >=3 consecutive days = a separate, lower-urgency "watch" alert.** Tied to
  the diagnosis observation that both P04 and P08 pass through `MODERATE` en route to `HIGH`.
  **Diagnosis predicts this adds a secondary signal without changing the top-level `HIGH` gate at
  all** -- it cannot fix P05 (never leaves `LOW`) or P04-seed42 (never leaves `LOW`), and does not
  change P08's `HIGH` classification once it's there. Evaluated anyway since it's cheap and might
  surface something in the broader cohort (P02/P03 edge cases) worth reporting, even though it is
  not expected to move any of the three diagnosed patients.
- **C3 -- component guard on `baseline_deficit`-driven `HIGH`: once `dominant_mechanism ==
  "baseline"` has been the sole driver (all acute components ~0) for more than 3 consecutive
  days, downgrade to the `MODERATE`/"watch" tier unless `instability_flag == 1` (actual MAP<65
  shock-range, not just the softer baseline-deficit ramp) at least once in that window.** Directly
  targets P08's diagnosed mechanism (sustained `baseline`-dominant `HIGH` with no corroborating
  acute signal). **Diagnosis flags the risk this breaks P04's seeds 43/44 true detections**, since
  those also show long `dominant_mechanism="baseline"` runs with acute components at ~0 --
  evaluated empirically in §3; expected to fail criterion 1 below, reported honestly either way.

No fourth candidate was invented to patch whatever C1-C3 can't reach; P05's and P04-seed42's
misses are reported as out of scope for this plan (§3, final note) if none of C1-C3 can do
better than the baseline on them -- expected, per the diagnosis above.

## Selection rule (written before computing any candidate's result)

Same priority order as the prior post-hoc round:

1. **Preserve every should_catch detection the baseline (unsmoothed `risk_bucket=="HIGH"`)
   achieves** -- a candidate that costs a real detection (e.g. suppressing P04's seeds 43/44) is
   rejected outright, regardless of its false-alert number.
2. Among candidates satisfying (1), pick the one with the **fewest false alerts per 100
   patient-days** in the should_stay_quiet group.
3. Ties broken by **shorter mean lead time** across detected should_catch patients.

If no candidate improves on the unsmoothed baseline without cost, that is reported as the result
-- not grounds to invent a new rule outside C1-C3.

## Confirmation run (proposed once a candidate is chosen, not run as part of this plan)

Same as the prior post-hoc proposal: fresh seeds 45, 46, 47, same frozen harness, all 10
patients, ~2.5-3h estimated. Reported separately once §3 has picked a winner.
