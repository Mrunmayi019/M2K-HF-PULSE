# Pre-implementation analysis (a, b, c) -- before `decide_alert()`

Read-only, from already-saved outputs. No new Pulse runs, no scorer changes.

## (a) P04 "seed-dependent": is it noise -> ML -> Pulse, or something else?

Confirmed: **noise -> ML -> Pulse, exactly, with no other mechanism involved.** Per-day
`predicted_scenario`/`predicted_severity` (ML) alongside `pulse_map_start` (Pulse), all 6 seeds:

| seed | ever predicts `cardiac_stress`/`acute_deterioration`? | `map_start` ever drops from ~95mmHg? | peak `risk_bucket` |
|---|---|---|---|
| 42 | No (only `deconditioning`/`fluid_overload`) | No -- flat 94.7-96.2mmHg all 21 days | LOW |
| 43 | Yes -- `cardiac_stress` days 6-10 | Yes -- drops to 76.2mmHg the day *after* the first `cardiac_stress` day, settles ~65mmHg from day 11 on | HIGH |
| 44 | Yes -- `cardiac_stress` day 9 | Yes -- drops to 68.4mmHg the day after, settles ~65mmHg | HIGH |
| 45 | No (always `deconditioning`) | No -- flat ~95mmHg all 21 days | LOW |
| 46 | No (always `deconditioning`) | No -- flat ~95mmHg all 21 days | LOW |
| 47 | Yes -- `cardiac_stress` days 1-2, 4-5 | Yes -- drops to 80.4mmHg by day 3, settles ~75-81mmHg (shallower than 43/44) | MODERATE |

**Mechanism, confirmed against source**: `EXERCISE_SCENARIO_INTENSITY_FACTOR` (`src/pulse_runner/
cli_state_scenario.py`/`sdk_runner.py`) is `{"cardiac_stress": 1.0, "acute_deterioration": 0.6}`
-- **these are the only two scenario types that trigger Pulse's Exercise action at all.**
`deconditioning` and `fluid_overload` never do, regardless of severity. Since the seed only
perturbs wearable noise, and the classifier's day-to-day scenario prediction is sensitive to that
noise, **whether a given seed's noise ever happens to push the classifier into predicting
`cardiac_stress`/`acute_deterioration` on any day is what determines whether Pulse's Exercise
action ever fires at all for that seed** -- and once it fires, `map_start` drops and (per the
P08 mechanism already diagnosed) never recovers for the rest of the run, regardless of what the
classifier predicts afterward (seeds 43/44/47 all keep predicting mostly `deconditioning` after
the initial `cardiac_stress` day(s), but `map_start` stays down). Seeds 42/45/46 simply never roll
a `cardiac_stress`/`acute_deterioration` day for this patient, so Pulse's hemodynamics never move
and `risk_bucket` stays `LOW` for all 21 days.

This is the same "transient trigger, no decay" mechanism as P08 (`scorer_diagnosis.md`), now also
explaining P04's seed-to-seed variance: it isn't Pulse behaving differently on "the same" input --
it's the ML classifier's own day-to-day noise-sensitivity deciding whether the Exercise-triggering
condition is ever met at all.

## (b) Status of `analysis/results-v1-offline` (ML metrics, weight sensitivity, MIMIC + age baseline, API timing)

**This branch does not exist** -- checked `git branch -a` (local + all remotes) and
`gh api repos/.../branches` directly against GitHub: no `analysis/results-v1-offline` anywhere,
on this machine or on origin. Also checked every other branch's tree for files matching "weight
sensitivity", "age baseline", "API timing", or "ML metrics" by name -- nothing found under those
names on any branch. (`data/mimic_outcome_validation/summary.md` exists and is already merged
into `main`, but that's the MIMIC piece specifically, not under this branch, and I haven't
re-verified its contents against this request since it predates this session.)

**I'm not summarizing results for work I can't locate** -- that would mean presenting numbers I
made up. Please point me at the actual location (a different branch name, a different machine, a
PR number, or a local path) and I'll check it properly.

## (c) MODERATE counts

- **Original `methodology.md` Sec 6.1 fluid_overload dataset** (`data/simulation_runs/
  features_dataset.csv`, 30 runs, via the real `compute_risk_score()`): **29/30 reach `MODERATE`**
  (1/30 stays `LOW`; 0/30 reach `HIGH` -- matches `methodology.md`'s own documented post-fix
  finding).
- **P04, scenario-test cohort, seeds 42-47** (126 patient-days total): **23/126 reach `MODERATE`**
  (77/126 `LOW`, 26/126 `HIGH`). Concentrated almost entirely in seed 47 (20/21 of that seed's
  days are `MODERATE` -- the shallower, non-`HIGH` congestion case from (a) above). This is
  directly relevant to the WATCH tier below: seed 47's entire trajectory, which never reaches
  `ALERT` under either existing definition, would surface as `WATCH` under the new design.
