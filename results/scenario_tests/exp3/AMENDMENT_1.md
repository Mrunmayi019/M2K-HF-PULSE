# Experiment 3, amendment 1 (2026-10-26): ramped refresh

**Made after the development smoke test and before any Experiment 3 cohort run.** No evaluation
seed (48–53) had been run with the flag when this amendment was committed. The pre-registration
(commit `9a6b290`) is unchanged except for a pointer to this file.

## What the smoke test showed

The pre-registered smoke test ran one development job (P06, seed 42, never an evaluation seed)
with the flag as committed in `0a1a1d5`. That version's refresh started the fresh twin with one
initial run directly at the day's severity. Output: `results/scenario_tests/exp3_smoke_v1_jump/`.

After the day-14 refresh (severity 0.78), the fresh twin collapsed with no Exercise: end HR
48 → 30 → 14 → 8 bpm and MAP 87 → 78 → 56 → 42 mmHg over days 15–18, and it stayed there to day
21. That gives 5 days with HR < 30 or MAP < 50. None was flagged as a failed run. In Experiment 2,
16 of 1,257 completed days were this low, all in one P10 series.

## Development check: jump vs ramp

Run outside the harness, with P06's demographics and EF (63%) and 600 s encounters, no Exercise.
Script and logs: `dev_diagnosis/`.

| Run | Severity path | Result |
|---|---|---|
| A | initial at 0.78, then 0.75 × 6 | HR 62 → 48 → 30 → 14 → 8 bpm, MAP 90 → 42 mmHg: collapse (matches the smoke test) |
| B | initial at 0.06, then 0.2, 0.4, 0.6, 0.78, then 0.75 × 6 | HR 72–76, MAP 94.6–96.0 throughout |
| C | 0.06 × 7 | HR 69–72, MAP 94.6–95.4 |

The collapse comes from the jump, not from the severity. At EF 63%, severities up to about 0.16
give the same modifiers as severity 0 (`ef_to_cardiovascular_modifiers`: `max(ef_deficit, 0.8 ×
severity)`), so B's start equals a start at severity 0.

## Change

The refresh now rebuilds the twin the way B does: an initial run at **severity 0**, then resumed
encounters at 0.2, 0.4, … and finally the day's severity (`REFRESH_RAMP_STEP = 0.2`,
`refresh_ramp()` in `continuous_state_pipeline.py`), each 600 s, with no Exercise. The drift's
fresh side is the end of the last ramp encounter, at the day's severity. The new chain's baseline
is still the first sample of its initial run. A failure at any step is recorded as a refresh error
and keeps the resumed state, as before. The tests cover the ramp (`tests/test_baseline_anchor.py`,
376 tests pass).

Nothing else changes: same cohort, seeds, flags (`required_flags`), outcomes, predictions and
scoring definitions.

## Smoke test again, with the change

Same job (P06, seed 42). Output: `results/scenario_tests/exp3_smoke/`.

- Days 1–7 are bit-for-bit identical to the first smoke run: HR, MAP and risk score on every day.
- After each refresh the twin stays at HR 71–76 and MAP 94–96 until a new exertion label. There
  are 0 days with HR < 30 or MAP < 50 (5 before the change).
- Drift: day 7 −21.6 bpm / −23.5 mmHg, and day 14 −28.7 / −30.2 (both after exertion in the
  chain). Day 21: −1.1 / +0.1 (no exertion since the day-14 refresh).

These smoke values were seen before the batch. They fit the predictions, and the predictions are
**not** changed. The predictions assumed that a refresh leaves a healthy fresh twin, which is what
the ramp now gives.

## Added secondary outcome

- **Collapse days:** completed days with end HR < 30 bpm or end MAP < 50 mmHg, and the number of
  series with any. Experiment 2: 16 days in 1 series (P10). **Predicted, Experiment 3: ≤ 16 days.**
  The refresh should not add collapses, and it may clear Experiment 2's.

## Run time

Each refresh now costs 1 + ⌈severity / 0.2⌉ Pulse runs. Experiment 2's severities on days 7, 14
and 21 give about 670 refresh runs, or roughly 1,990 Pulse runs in total. At 2 jobs at a time,
that is about 14 hours, not the ~10 estimated in §7. The commands in §7 are unchanged.
