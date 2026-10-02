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
shifted to `fluid_overload` at a similar severity, which doesn't crash. See §10 for the full-cohort
pattern this previews.

<!-- SECTIONS BELOW FILLED IN FROM analyze.py's OUTPUT, AFTER THE FULL BATCH COMPLETES -->
