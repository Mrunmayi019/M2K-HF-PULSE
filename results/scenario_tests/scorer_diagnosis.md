# Risk-scorer diagnosis: P05 miss, P04 seed-dependent miss, P08 sustained false alarm

Post-hoc, read-only. Recomputes `src.analytics.risk_score.compute_risk_score()` (the real
function, not reimplemented) from the Pulse start/end features already saved in
`daily_results_*.csv` (`pulse_hr_start/end`, `pulse_map_start/end`, `pulse_co_start/end`,
`pulse_compensation_flag`, `pulse_instability_flag`) -- script:
`src/evaluation/scenario_tests/scorer_diagnosis.py`. No new Pulse runs, no scorer/harness changes.

## Is "deconditioning" weighted lower by design?

**No. `compute_risk_score()` takes no `scenario_type` argument at all** -- its signature is
`compute_risk_score(hr_rise, map_drop, co_drop_pct, compensation_flag, instability_flag,
map_start)`. There is no branch, weight, or comment anywhere in `src/analytics/risk_score.py` that
references scenario type. The weights (clinically motivated, per the module's own docstring, not
scenario-aware):

```python
WEIGHTS = {
    "instability_flag": 0.30,
    "map_drop": 0.20,
    "co_drop_pct": 0.20,
    "hr_rise": 0.15,
    "compensation_flag": 0.15,
}
```

plus `baseline_deficit_score` (from `map_start` alone, the fluid_overload blind-spot fix), with
`risk_score = max(acute_score, baseline_deficit_score)`. The function cannot "know" it's scoring
a deconditioning patient, so it cannot deprioritize one by design.

## P05 (deconditioning, missed in all 3 seeds): zero signal, not low weight

Every one of the 5 acute components, AND `baseline_deficit_score`, is ~0.000 on every single one
of the 63 patient-days (3 seeds x 21 days) -- `risk_score` never exceeds 0.0121 the entire run, in
any seed (vs. `MODERATE` at 0.35). Representative days (seed 42, pattern identical in 43/44):

| day | risk_score | instability | map_drop | co_drop_pct | hr_rise | compensation | baseline_deficit |
|---|---|---|---|---|---|---|---|
| 1 | 0.0006 | 0.000 | 0.001 | 0.000 | 0.000 | 0.000 | 0.000 |
| 10 | 0.0036 | 0.000 | 0.004 | 0.000 | 0.000 | 0.000 | 0.000 |
| 21 | 0.0050 | 0.000 | 0.000 | 0.005 | 0.000 | 0.000 | 0.000 |

`map_start` never drops from its healthy baseline either (`baseline_deficit_score` would be
nonzero if it had). **Deconditioning's physiological signature (reduced activity, not an acute
cardiovascular stressor) simply doesn't move any of the five hemodynamic features this scorer
reads, and doesn't congest the resting baseline either.** This is a blind spot in what the scorer
can see, not a weighting choice -- there is no reachable risk_score path from a deconditioning
story's physiology to a nonzero component under the current five-feature design.

## P04 (fluid overload): how close does the missed seed get, and what differs?

**Seed 42 (missed): `map_start` stays at 94.7-96.2mmHg -- above the healthy 92.5mmHg anchor --
for all 21 days.** `risk_score` never exceeds 0.0078 (`LOW`) the entire run. It isn't "close and
just under 0.65" -- the underlying physiology never congests at all in this run.

**Seeds 43/44 (alerted): `map_start` collapses into the low-70s-to-80s mmHg range by day 6-10**
(seed 43 day 7: `baseline_deficit_score=0.592`, dominant mechanism flips from `acute` to
`baseline`; day 10 onward: `baseline_deficit_score` saturates at 1.0, `risk_score=1.0`). The
component that differs is **`baseline_deficit_score` (via `map_start`) -- it's the only one that
ever moves for this patient; the other four stay near 0 in every seed, alerting or not.**

**This is a seed-dependent Pulse simulation outcome, not a scorer or weighting issue**: the same
story/severity schedule produces a congesting trajectory in 2 of 3 seeds and a non-congesting one
in the third.

## P08 (stressful fortnight, should_stay_quiet): what keeps risk HIGH through day 21?

A transient acute stress episode (matching the story's own designed stress episodes, around days
5-11) briefly lights up `hr_rise`, `map_drop`, and `compensation_flag` together (e.g. seed 42,
day 11: `map_drop=0.199`, `hr_rise=0.150`, `compensation_flag=0.150`, `risk_score=0.4991`,
`MODERATE`). The day after, `map_start` has shifted down enough that `baseline_deficit_score`
takes over (`dominant_mechanism` flips to `baseline`) and **saturates near 1.0 for the rest of the
21-day window, in all 3 seeds** -- days 12-21 (seed 42) show every acute component back at ~0
while `baseline_deficit_score` stays 0.75-0.98. **`baseline_deficit_score` has no decay: once a
transient episode shifts `map_start` down, the continuous-state pipeline carries that forward day
to day with nothing in this scorer that lets it recover**, even though the story's own stress
episodes and poor-sleep period have ended by day 16 and the wearable inputs return to baseline.

**This is structurally the same mechanism as P04's true detection** (`baseline_deficit`-dominant,
acute components at ~0) -- see `alert_fix_plan.md` for why this limits every candidate fix.
