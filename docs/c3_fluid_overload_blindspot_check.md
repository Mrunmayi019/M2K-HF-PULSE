# C3 vs. the fluid_overload blind spot -- checked before implementing decide_alert()

Per instruction: before implementing C3 in `decide_alert()`, verify it doesn't suppress genuine
fluid_overload detections (the exact case `baseline_deficit_score` exists to catch,
`docs/methodology.md` Sec 6.1). Read-only, offline, no scorer/pipeline changes. Script:
`src/evaluation/scenario_tests/c3_blindspot_check.py`.

**Result: C3 does not suppress a single genuine fluid_overload alert day in either check below.
Clear to proceed.**

## Check 1: P04 (scenario-test cohort), seeds 42-44, per-day

Every `HIGH` day across all three seeds was individually classified as `instability-driven`
(`instability_flag==1` that day) or `baseline-only` (`instability_flag==0`, `dominant_mechanism==
"baseline"`), and checked against C3's actual per-day suppression decision (not just "was the
first alert day lost" -- every day).

- **Seed 42: never reaches `HIGH` at all** (the diagnosed miss, `scorer_diagnosis.md` --
  unaffected by C3 either way, since C3 only acts on `HIGH`).
- **Seed 43: `HIGH` days 8-21.** Day 8 is `baseline-only` (streak length 1 -- C3's `>3 consecutive
  days` condition can't fire yet). Day 9 is `instability-driven` -- `instability_flag==1` is seen
  within the streak from here on, which permanently satisfies C3's guard for the rest of this
  streak. Days 16 and 19 are individually `baseline-only` again later in the same streak, but
  because instability was already seen earlier in the SAME uninterrupted streak, C3 never
  downgrades them either. **Zero days suppressed.**
- **Seed 44: `HIGH` days 10-21.** Days 10-11 are `baseline-only` (streak lengths 1-2, still under
  the >3 threshold). Day 12 is `instability-driven`, which again permanently satisfies the guard
  for the rest of the streak -- days 15 and 17 (`baseline-only` again later) are protected the
  same way. **Zero days suppressed.**

No `C3 WOULD SUPPRESS THIS DAY` flag fired on any of the 63 patient-days checked (full log:
re-run `c3_blindspot_check.py` to reproduce). The mechanism holds exactly as `alert_fix_results.md`
found empirically at the first-alert-day level -- confirmed here at the full per-day level too.

## Check 2: the original fluid_overload blind-spot dataset (`docs/methodology.md` Sec 6.1)

`data/simulation_runs/features_dataset.csv` -- the actual 30-run dataset that motivated
`baseline_deficit_score` -- was fed through the real `compute_risk_score()` directly (not
reimplemented): **29/30 `MODERATE`, 1/30 `LOW`, 0/30 `HIGH`.** C3 only ever acts on `risk_bucket==
"HIGH"`; since none of these 30 original cases reach `HIGH` at all (matching `methodology.md`'s
own documented post-fix finding, "30/30 LOW to 29/30 MODERATE"), **C3 is structurally inapplicable
to this dataset regardless of the streak-length question.**

A second, independent reason this dataset can't even test C3's persistence condition: it's
**cross-sectional -- one row per patient, a single Pulse encounter, no day dimension at all.**
C3 requires a streak of **more than 3 consecutive days**; a single isolated encounter can never
accumulate a streak longer than 1, so C3 could not suppress it even if it had reached `HIGH`.

## Conclusion

Both checks are clean. C3 does not suppress any genuine fluid_overload detection in either the
scenario-test cohort (checked per-day, all 3 dev seeds) or the original validation dataset the
blind-spot fix was built from. Proceeding to the held-out evaluation (seeds 45-47, once that run
completes) and then, on your go-ahead, implementing `decide_alert()`.
