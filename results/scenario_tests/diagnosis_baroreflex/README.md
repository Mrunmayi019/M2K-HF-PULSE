# Why HIGH-risk days persist after exertion (exploratory, 13 Oct 2026)

This analysis is post hoc. It was run after Experiments 1 and 2 and is not pre-registered. Experiment 3 (an
exercise-stop flag) was started and then abandoned after its smoke test; see branch `exp3-abandoned`.

## Finding

Pulse 4.3.1's baroreflex resets its MAP set point when MAP stays more than 5% off it for 420 s. Each reset moves the
set point 35% of the way toward the current MAP (`NervousModel.cpp`, `BaroreceptorFeedback`, release REL_4_3_1). The set
point is stored in `CurrentPatient.MeanArterialPressureBaseline`, which the continuous mode saves and reloads every day.
Simulated exertion under the disease modifiers holds MAP far below the set point. The set point therefore ratchets down
(P08, Exp 2, seed 48: from 95.4 to 65.1 mmHg over days 9–11), and the reflex then holds MAP near 65 mmHg with HR near 45 bpm.

## Evidence

| File | What it shows |
|---|---|
| `baseline_scan.txt` (`baseline_scan.py`) | Set point at the start of each day, read from the saved states. HIGH days: median 63.6–63.7 mmHg, and 98.3% (Exp 1 held-out seeds, the only Exp 1 seeds with saved states) and 99.4% (Exp 2) are below 85. Other days: median 95.2. |
| `E_exertion_from_day8_events.txt` | Replaying day 9's exertion from the saved day-8 state for 1800 s gives resets of 80.6, 72.4, 68.1 and 65.6 mmHg. |
| `A_stuck_asis_events.txt` | The saved day-13 state, advanced 1200 s as-is, stays at HR 45 and MAP 67. |
| `F_exercise_deleted_from_state_events.txt` (`diag_f.py`) | The `Exercise` action deleted from the saved state: MAP stays at 67 mmHg and HR falls to 37 bpm. |
| `C_baseline_restored_events.txt` | Set point restored to 95.4: the reflex saturates (it does so at MAP about 2.6% below the set point, with ResponseSlope 12). HR then falls to 20 bpm and MAP to 53 mmHg within 1200 s, and the set point resets to 84.6, then 76.0. |
| `run_summary.txt` | HR, MAP, CO and SV at +0, 300, 600, 1200 and 1800 s for every run. |

**Runs B and D are not valid "exercise off" tests.** `scenario_file._exercise_action(0.0)` clips intensity to 0.1, so
they applied Exercise at 0.1. Run F replaces them.

## Rerun

States come from `results/scenario_tests/exp2/dbs/P08_seed48.db`, `pulse_states` ids 9 (end of day 8) and 14 (end of day 13),
exported as `P08s48_state9.json` and `P08s48_state14.json` into an `out/` folder. Then:

    docker run --rm --platform linux/amd64 -v <repo>:/workspace:ro -v <out>:/out \
      --entrypoint python m2k-hf-pulse-main-pulse-backend /out/diag_runs.py

The driver exits 1 on resumed runs because of its end-time check (a known issue); the results are complete.
`summ.py <out>` summarises the outputs in that folder.

The state databases (`results/scenario_tests/dbs/` for Exp 1, `results/scenario_tests/exp2/dbs/` for Exp 2) are not
in git because of their size, so `baseline_scan.py` and the reruns need a local copy of them.
