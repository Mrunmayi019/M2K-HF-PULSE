# Alert fix: held-out evaluation (seeds 45-47)

Post-hoc. Same frozen harness (unmodified `run_patient_seed.py`/`cohort.yaml`), evaluated once on
fresh seeds 45-47 (launched via the new `run_batch_heldout.py` orchestrator, 30 jobs, N=6, all
exited cleanly). C3 was selected on dev seeds 42-44 (`alert_fix_results.md`) BEFORE this batch was
run; this evaluation was not used to pick anything -- it's a check of whether the dev-seed choice
holds.

## Development vs. held-out, side by side

| candidate | dev (42-44): should_catch | dev: false alerts/100pd | held-out (45-47): should_catch | held-out: false alerts/100pd |
|---|---|---|---|---|
| baseline | 3/5 | 17.99 | 3/5 | 30.16 |
| C1 | 3/5 | 13.76 | 3/5 | 25.40 |
| C2 | 3/5 | 17.99 | 3/5 | 30.16 |
| **C3** | **3/5** | **5.82** | **3/5** | **11.64** |

**The held-out baseline false-alert rate is itself higher than dev's** (30.16 vs. 17.99) -- these
are different noise realizations, not the same numbers reproduced; the comparison that matters is
each candidate's *relative* improvement over its own baseline, not the absolute numbers matching
across seed sets.

**C3 holds.** Same exact set of should_catch detections in both seed sets -- {P06, P07, P10},
confirmed per-patient (`results/scenario_tests/posthoc/alert_fix_eval_heldout.json`), P04 and P05
missed in both (P04: missed in all 3 held-out seeds too, vs. 1-of-3 missed in dev -- consistent
with the diagnosis that this is seed-dependent Pulse physiology, not something that should be
expected to reproduce identically). C3 cuts false alerts by 67.6% relative to baseline on dev
(17.99 -> 5.82) and by 61.4% on held-out (30.16 -> 11.64) -- the same mechanism, a comparable
relative improvement, on data it was never selected on.

## Step-3 check (fluid_overload blind spot), reproduced on held-out seeds

The per-day P04 check from `docs/c3_fluid_overload_blindspot_check.md` (fix/unified-alert-decision
branch) was re-run on seeds 45-47: **P04 never reaches `risk_bucket=="HIGH"` in any of the 3
held-out seeds at all** (vs. 2-of-3 dev seeds), so there is nothing for C3 to suppress or not --
confirmed vacuously true (`suppressed_any = False` in all three). Combined with the dev-seed and
original-validation-dataset checks (zero suppression in either), **C3 shows no evidence of
suppressing a genuine fluid_overload detection across any of the three checks run.**

## Conclusion

C3's false-alert reduction and should_catch preservation both hold on seeds it wasn't selected
on. P04's miss got worse on held-out (0/3 vs. 1/3 on dev) and P05 remains missed in all 6 seeds
across both batches -- both fully consistent with `scorer_diagnosis.md`'s structural-limit finding
(no signal for any alert-side rule, this one included), not a new problem C3 introduced.
