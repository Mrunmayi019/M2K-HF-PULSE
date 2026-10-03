# Scenario test results

**These tests check that the pipeline responds as designed to controlled synthetic patient
stories; they are not clinical validation.** No claim of heart-failure detection or diagnosis is
made anywhere in this document.

## 1. Setup

- **Branch:** `feature/scenario-testing`, created from tag `results-rc1` (commit `63ba6b4`) --
  **provisional, unreviewed**: PR #4 was still open at the time these results were produced. Per
  explicit instruction, `results-v1` will be created once PR #4 merges, either by re-tagging the
  merged `main` commit (if `git diff --stat results-rc1 main` shows no code/config/requirements
  differences, no rerun needed) or by rerunning against whatever differences are found.
- **Model provenance:** `models/scenario_classifier.joblib` (sha256
  `2157cb21991390e6b2417ff8793c2b62a32eeef7467963b94d5058cc37d05a49`) and
  `models/severity_regressor.joblib` (sha256
  `4b7afeab6210464b2e3730bf54248362db0ecc83ed58626a488fd3d47cb79f0e`), matching
  `artifacts/results-v1/models/` exactly -- verified by SHA-256 before every single patient-seed
  run (`src/evaluation/scenario_tests/run_patient_seed.py`'s `verify_model_hashes()`, which refuses
  to start on any mismatch). Trained by `src/scenario_classifier/train.py`'s `run()`,
  `seed=42`, on `data/synthetic/patients.csv` + `data/synthetic/wearable_trends.csv`, under
  scikit-learn 1.9.0.
- **Environment:** `m2k-hf-pulse-backend` Docker image (`backend/Dockerfile`, Python 3.11.17,
  pinned `scikit-learn==1.9.0`/`numpy==2.4.6`/`pandas==3.0.6`/`xgboost==3.2.0`) -- NOT the raw
  `kitware/pulse:4.3.1` image, per `docs/integration_pre_results.md` §10.5's recommendation.
  Confirmed running under amd64 emulation on this (arm64) Mac, same as every other Docker
  verification in this project.
- **Pulse acute-stress action:** confirmed working live before this run (`cardiac_stress` resume
  with the Exercise action: HR 72.3 → 101.7 bpm across a real `resume_and_advance()` call, no
  crash). Only wired to `cardiac_stress`/`acute_deterioration` scenario types
  (`EXERCISE_SCENARIO_INTENSITY_FACTOR`) -- confirmed, not assumed.
- **`compute_projection=False`** throughout (`run_daily_continuous_pipeline()`'s opt-out,
  `docs/integration_pre_results.md` §11/§12 -- confirmed by both a unit test and an independent
  live 14-day run to produce identical risk_score/NYHA/alert decisions to the default path).
- **Concurrency:** one process per patient-seed (`subprocess.Popen`, never threads or
  `multiprocessing`'s fork start method), up to 6 concurrent (`src/evaluation/scenario_tests/
  run_batch.py`), matching the N=6 throughput benchmark in `docs/integration_pre_results.md` §13.
- **Patient profiles:** see `config/scenario_tests/cohort.yaml`'s `meta.demographic_ranges_used`
  for the exact generator ranges each of the 10 patients' demographics was drawn from (age 45-82,
  both sexes, weight 60-100kg, EF 25-66% spanning healthy/HFpEF/HFrEF profiles) -- no range
  invented beyond `src/data_synthesis/reference_stats.yaml`.

## 2. Pre-registered expectations

See `results/scenario_tests/expected_outcomes.md` (committed before any simulation ran). Groups:
should-catch (P04, P05, P06, P07, P10), should-stay-quiet (P01, P08, P09), edge cases (P02, P03).
A patient counts as alerted only if it alerts in all 3 seeds (42, 43, 44).

## 3. Pilot (P10, seed 42)

Run first, in isolation, before the full batch. **21/21 days processed, 8 failed (days 9-16),
fully recovered from day 17.** Total wall time 721.5s (~12.0 min); 47-48s/completed day, 84.5s for
day 1 (includes stabilization), 8.2-8.7s/failed day (fails fast). `simulation_time_s` stepped
exactly +600s per *completed* day throughout, including across the 8-day failure gap (4860 ->
5460, not +4800) -- confirming the "one encounter behind, never catches up" design
(`docs/integration_pre_results.md` §8) holds under a real multi-day failure streak, not just an
isolated test. `alert_source` was `scorer` on every completed day and `unstable_fallback` on every
failed day, exactly as designed.

**Pilot finding, not a bug:** the classifier predicted severity 0.81-0.90 from day 2 onward --
far above the story's injected target (0.20->0.45 ramp) -- for this patient's EF=25%/BNP=900
baseline. This pushed 8 consecutive days into the documented Pulse crash zone
(`acute_deterioration`/`deconditioning` at high severity); recovery came once the predicted label
shifted to `fluid_overload` at a similar severity, which doesn't crash. See §6 for the full-cohort
pattern this previews.

**What happened between this pilot and the full batch** (full reasoning, evidence, and diffs in
`results/scenario_tests/protocol_amendments.md`, timestamped): the pilot's EF=25%/BNP=900 baseline
turned out to be a genuine design confound (EF/BNP was matched to each story's *severity*, not
drawn independently), so the cohort was rebuilt with (A) a neutral EF/BNP band (48-57%/200-290
pg/mL) across all 10 patients and (B) smoother multi-day transitions for chronic/lifestyle changes
that had been single-day cliffs (genuinely acute events were deliberately left sudden -- see §7).
Investigating the amended pilot's own residual pre-story alerting (days 2-3, before P10's story
starts on day 4) surfaced two scenario-test-runner bugs, both fixed, neither touching the
pipeline: (1) the harness's day-to-day wearable noise SD was `current_value * 0.15` instead of
`population_sd * 0.15` (2.7x oversized on `steps_per_day`, ~2x on `hrv_rmssd_ms` -- precisely the
regressor's two highest-importance features, see §6); (2) the per-(patient, seed) RNG seed was
derived from Python's built-in `hash()`, which CPython salts per-process by default, so "seed=42"
silently produced a different noise realization on every separate run. After both fixes, a final
pilot rerun showed 21/21 days complete, 0 failures, and the residual pre-story alerting fully
resolved (days 1-3 severity 0.053/0.102/0.130, all below the 0.15 alert threshold; the alert begins
exactly on day 4, scorer-driven, when the story itself starts). The harness, cohort, and schedules
were frozen at that point (commit `785bd11`): from there on, only a mismatch between the harness
and the documented system/generator conventions counts as a bug -- any other outcome, including
the findings below, is reported as observed, not adjusted for.

## 4. Full batch: reliability

30 jobs (10 patients x 3 seeds), N=6 concurrent, one process per patient-seed, all processing
their full 21-day schedule. **29/30 jobs had zero failed days; 1 job (P02, seed=44) ended 3 days
behind** after three
consecutive real Pulse engine failures on days 19-21 (`PulseExecutionError: PulseScenarioDriver
exited 1`) that the run never recovered from before the window closed -- handled exactly per the
hard rule (each failure recorded via the real failed `SimulationRun` row, the run resumed one
encounter behind, nothing silently dropped). Every other patient-seed had 0 failed days. Mean wall
time per completed day: 86-90s under N=6 contention (vs. ~47-85s solo in the pilots). Full detail:
`results/scenario_tests/reliability.csv`.

This is a real-pipeline finding (Pulse's own documented instability under certain physiological
trajectories, `docs/synthetic_deterioration_stress_test.md`), not a harness bug -- nothing changed.

## 5. Main results (per-patient)

Primary window (21 days) and secondary snapshot (day 14, same runs, not re-simulated):
`results/scenario_tests/main_table_day21.csv` / `main_table_day14.csv`. A patient counts as
alerted only if alerted in all 3 seeds (pre-registered).

| patient | story | group | alerted (all seeds) | first alert day by seed | dominant predicted label |
|---|---|---|---|---|---|
| P01 | Stable, ordinary life | should_stay_quiet | **True** | [7, 7, 14] | deconditioning |
| P02 | Salty weekend | edge_case | True | [10, 7, 13] | deconditioning |
| P03 | Slow, quiet weight gain | edge_case | False | [10, None, 7] | deconditioning |
| P04 | Fluid overload building | should_catch | True | [6, 7, 5] | deconditioning |
| P05 | Gradual deconditioning | should_catch | True | [5, 5, 7] | deconditioning |
| P06 | Cardiac stress | should_catch | True | [3, 3, 2] | deconditioning |
| P07 | Sudden deterioration | should_catch | True | [2, 2, 4] | deconditioning |
| P08 | Stressful fortnight, healthy heart | should_stay_quiet | **True** | [7, 6, 8] | cardiac_stress |
| P09 | Active, stable patient | should_stay_quiet | **True** | [2, 1, 1] | deconditioning |
| P10 | Everything goes wrong | should_catch | True | [4, 4, 1] | deconditioning |

Day-14 snapshot: identical group-level pattern (same alerted-in-all-seeds status for every
patient; only P07/P10's *dominant* predicted label differs between day 14 (`cardiac_stress`) and
day 21 (`deconditioning`) -- `results/scenario_tests/day14_vs_day21_diffs.csv`, §10).

## 6. Group results, false-alert rate, and why: feature importances

**Pre-registered discrimination check, reported as observed (no re-tuning):**

- **should_catch (5/5):** all caught, in all seeds -- P04, P05, P06, P07, P10 all alert.
- **should_stay_quiet (0/3 stayed quiet -- all 3 false-alerted in all seeds):** P01, P08, P09 all
  alert in every seed. This is the test failing to discriminate as designed, per the
  pre-registered risk in `expected_outcomes.md`, reported exactly as that document said it would
  be if it happened: **not re-tuned away.**
- **Cohort-wide false-alert rate (should_stay_quiet group, 21-day window): 111/189 patient-days,
  58.73 per 100 patient-days** (57.14 at the day-14 snapshot) -- `false_alert_rate()`,
  `results/scenario_tests/analysis_summary.json`.
- **alert_source breakdown, whole cohort, 21-day window:** `scorer` 402, `unstable_completed` 1
  (the pilot's crash-zone-but-completed case, reproduced once more in the batch), `failed_fallback`
  0 (P02 seed=44's three Pulse failures all happened without a live alert evaluation on those
  days, so none fell into this bucket).
- **Edge cases, described not scored:** P02 alerted in all 3 seeds (first-alert days 7-13) --
  see §7 for why this looks delayed/unrelated to its own story. P03 did not alert in one of three
  seeds (`alerted_all_seeds=False`) -- the only patient in the cohort that didn't converge to a
  consistent alert outcome across seeds.

**Why: the regressor and classifier barely look at the clinical features this cohort actually
varies.** Top-10 feature importances (`results/scenario_tests/feature_importances.csv`,
`feature_importances()`):

| rank | scenario_classifier | importance | severity_regressor | importance |
|---|---|---|---|---|
| 1 | ejection_fraction_pct | 0.1567 | resting_hr_bpm_delta | 0.3179 |
| 2 | weight_kg_slope | 0.0838 | resting_hr_bpm_slope | 0.3144 |
| 3 | spo2_pct_delta | 0.0764 | steps_per_day_slope | 0.1918 |
| 4 | spo2_pct_slope | 0.0763 | steps_per_day_delta | 0.0801 |
| 5 | resting_hr_bpm_slope | 0.0737 | weight_kg_slope | 0.0282 |
| ... | | | | |
| 10 | hrv_rmssd_ms_slope | 0.0410 | **ejection_fraction_pct** | **0.0062** |

`nt_probnp_pg_ml` doesn't appear in either top-10 at all. **The severity regressor's two
highest-importance features, `resting_hr_bpm` delta+slope (63.2% combined) and `steps_per_day`
slope+delta (27.2% combined), are exactly the two wearable trends that ordinary day-to-day noise
moves most** -- and `ejection_fraction_pct`, the feature amendment A deliberately neutralized to a
48-57% band for every patient (§3), ranks 10th for the regressor at 0.6% importance, well below
where it could anchor a "this patient is clinically healthy" prior against noisy trend features.
The classifier leans on EF more (rank 1, 15.7%) but still gives `weight_kg`/`spo2_pct`/HR trend
features a combined 36.5% in its own top 5. §9's offline noise-robustness check quantifies this
sensitivity directly for P01.

## 7. Sudden-event handling (P02, P07, P08)

Per-day detail: `results/scenario_tests/daily_results_{P02,P07,P08}_seed42.csv`; full timelines in
`results/scenario_tests/figures/timeline_{P02,P07,P08}.png`.

- **P02 (salty weekend, edge case):** the designed wearable-only weight bump (days 5-9, +2.8kg
  peak) is tracked correctly and promptly -- `predicted_scenario` flips to `fluid_overload` for
  days 7-9, exactly while the bump is active, with **no alert during the bump itself** (severity
  stays <=0.12). The alert that eventually fires (day 10 onward, `scorer`-sourced, climbing to
  0.42 by day 14) starts *after* the weight has already returned to baseline and tracks the same
  background HR/steps drift seen across the rest of the cohort (§6) -- not a response to the
  salty-weekend event. The system responded correctly to the designed sudden event; the alert it's
  ultimately credited with is unrelated to it.
- **P07 (sudden deterioration, should_catch, onset compressed to days 10-13):** already alerting
  from day 2 for the same background reason as the rest of the cohort, but the onset itself
  produces a clear, correctly-timed step change on top of that background: severity rises from
  0.42 (day 10) to 0.88 (day 13) and holds near 0.90 (days 14-16), syncing tightly with the
  designed days 10-13 ramp.
  `predicted_scenario` shifts to `deconditioning` during the held phase rather than the expected
  `acute_deterioration` label -- the system detects *that* something acute is happening at the
  right time, but doesn't reproduce the exact pre-registered label.
- **P08 (stressful fortnight, healthy heart, should_stay_quiet, acute stress + poor sleep days
  5-16):** alerts from day 7, `predicted_scenario` shifts to `cardiac_stress`, severity peaks at
  0.58-0.59 around days 13-14 while the fortnight is active, and `risk_score` keeps climbing to
  ~0.98 through days 15-18 even as severity is already declining. **Recovers on its own** --
  severity drops below the 0.15 alert threshold by day 20 and `alert_flag` clears there too
  (despite `risk_score` still reading ~0.98 that same day, confirming the alert gate is severity-
  threshold-driven, not risk-score-driven), 4 days after the stressful fortnight ends. Under the
  pre-registered "alerted in all 3 seeds" rule this still counts as a false alert for the
  should_stay_quiet group (§6), but the per-day trace shows the system tracking the designed
  stress episodes proportionally and recovering once they stop, rather than staying pinned high
  for the rest of the window.

## 8. Per-patient timelines

300dpi, colorblind-safe (`#2a78d6`/`#e34948`/`#52514e`/`#eb6834`) timeline figures for all 10
patients: `results/scenario_tests/figures/timeline_P01.png` through `timeline_P10.png`.

## 9. P10 signal ablation (offline, no new Pulse runs)

Re-running the real severity regressor on P10 seed=42's saved 21-day wearable window with one
signal held flat at its day-1 value at a time (`results/scenario_tests/p10_ablation.csv`):

| ablation | peak predicted severity | delta vs. full | first day > 0.20 |
|---|---|---|---|
| none (full signal) | 0.8483 | -- | day 2 |
| weight_kg held flat | 0.9151 | +0.067 | day 2 |
| steps_per_day held flat | 0.6743 | **-0.174** | day 2 |
| hrv_rmssd_ms held flat | 0.8410 | -0.007 | day 2 |

Removing `steps_per_day`'s trend has by far the largest effect (-0.174 peak severity), consistent
with it being the regressor's 3rd/4th-ranked feature (§6); `hrv_rmssd_ms` has almost none, matching
its low rank. None of the three ablations changes which day severity first crosses 0.20 -- for this
patient, the crossing happens immediately regardless of which single signal is held flat.

## 10. Noise-robustness check (offline, no new Pulse runs)

Feeding the real classifier/regressor P01's and P10's saved seed-42 wearable windows with EXTRA
Gaussian noise layered on top at 1x/1.5x/2x the population SD (`results/scenario_tests/
noise_robustness.csv`) -- noisier than any real-world data this test suite otherwise exercises
(the harness's own day-to-day noise is population_sd * 0.15):

| patient | extra noise (x population SD) | predicted severity | severity band |
|---|---|---|---|
| P01 | 0 (none) | 0.1145 | within_stable_range |
| P01 | 1.0x | 0.4277 | **exceeds_stable_range** |
| P01 | 1.5x | 0.5440 | exceeds_stable_range |
| P01 | 2.0x | 0.5596 | exceeds_stable_range |
| P10 | 0 (none) | 0.7768 | exceeds_stable_range |
| P10 | 1.0x | 0.5700 | exceeds_stable_range |
| P10 | 1.5x | 0.6217 | exceeds_stable_range (label flips to fluid_overload) |
| P10 | 2.0x | 0.8501 | exceeds_stable_range |

**P01 (should_stay_quiet, EF/BNP in the neutral healthy band) flips from within-range to
exceeds-range at just 1x additional population-SD noise** -- directly demonstrating the mechanism
behind §6's false-alert finding: these models are sensitive enough to ordinary wearable-sensor
noise alone, without any real physiological change, that noise at a level real consumer wearables
can plausibly produce is enough to cross the alert threshold. P10 (already unwell) shows the
opposite problem -- severity moves non-monotonically with added noise (0.78 -> 0.57 -> 0.62 -> 0.85)
and the predicted label itself briefly changes category (to `fluid_overload`) at 1.5x, showing the
model's output surface isn't smooth or well-behaved for an already-sick patient either. **Reported
as classifier/regressor sensitivity only** -- this offline check doesn't run Pulse and therefore
doesn't reflect the real alert decision's risk-score/confidence path, only the
scenario/severity/severity_band inputs to it.

## 11. Weight-rule baseline comparison

A trivial rule (>=2kg weight gain within any 3-day window) vs. the real pipeline's alert decision,
both evaluated on the same 21-day data (`results/scenario_tests/weight_rule_baseline_day21.csv`):

| patient | weight-rule triggers | pipeline alerts (all seeds) |
|---|---|---|
| P01, P03, P05, P06, P07, P08, P09, P10 | No | Yes (all except P03) |
| P02 | Yes (day 5) | Yes |
| P04 | Yes (day 19) | Yes |

**The trivial weight rule triggers for only 2 of 10 patients; the real pipeline alerts for 9 of
10** (everyone except P03). The two rules agree only on P02 and P04. This is the starkest way to
see §6's finding: the pipeline's alert is, for most of this cohort, essentially decoupled from the
one signal (rapid weight gain) that a simple, well-understood clinical heuristic would flag.

## 12. Day 14 vs. day 21 (same runs, not re-simulated)

Only two patients show any difference between the two snapshots, and only in the *dominant
predicted label*, not in alert status (`results/scenario_tests/day14_vs_day21_diffs.csv`):

| patient | label @ day 14 | label @ day 21 | alerted (all seeds) @ 14 | @ 21 |
|---|---|---|---|---|
| P07 | cardiac_stress | deconditioning | True | True |
| P10 | cardiac_stress | deconditioning | True | True |

Every other patient's dominant label and alert status is identical at both snapshots. Combined
with §5's table, the day-14 secondary analysis would have reported the same group-level
discrimination failure (§6) as the day-21 primary analysis.

## 13. Summary

- **should_catch: 5/5 caught, in all seeds.** The pipeline does respond to every should-catch
  story's designed deterioration.
- **should_stay_quiet: 0/3 stayed quiet.** P01, P08, P09 all false-alert in all 3 seeds; cohort-wide
  false-alert rate in this group is ~58 per 100 patient-days. This is the test failing to
  discriminate exactly the way `expected_outcomes.md` said it could, reported as pre-registered,
  not re-tuned.
- **Root cause, evidenced not assumed:** the severity regressor's top two features (HR and steps
  trend, 90%+ combined importance) are the two wearable signals ordinary sensor noise moves most;
  the classifier leans more on EF but amendment A deliberately neutralized EF/BNP to a narrow
  healthy-range band for every patient, removing the one clinical anchor that could have overridden
  noisy trend features for a truly healthy patient. §10's offline check shows P01 crossing the
  alert threshold from noise alone, at a noise level smaller than real wearables can produce.
- **Sudden-event handling is directionally correct** (P02's weight bump, P07's compressed onset,
  P08's fortnight and its own recovery, §7) even where the headline alert/no-alert outcome is wrong
  -- the pipeline tracks the right signal at the right time, it just doesn't gate the final alert
  decision on it tightly enough relative to background noise.
- **One real Pulse engine reliability finding** (§4, P02 seed=44, three consecutive crash-zone
  failures, unrecovered within the window) and **one real "unstable but completed" labelling case**
  reproduced again in the full batch (§6), both expected/documented pipeline behavior, neither
  changed.
- Full amendment history, every bug found and fixed in the test harness (never the pipeline), and
  the exact freeze point: `results/scenario_tests/protocol_amendments.md`.
