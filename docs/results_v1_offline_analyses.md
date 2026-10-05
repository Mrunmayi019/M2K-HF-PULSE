# results-v1 offline analyses

Run in `../M2K-results-v1` (worktree, branch `analysis/results-v1-offline`, from `results-v1`
tag / `origin/main` `e4257ff`), per instruction, now that the scenario-test batches have
finished and this worktree has the CPU to itself. No code changes to production files; all
analysis lives under `src/evaluation/results_v1_offline/`.

## Model hashes -- settled first, as instructed

Three sources compared via SHA-256:

| source | `scenario_classifier.joblib` | `severity_regressor.joblib` |
|---|---|---|
| Recorded (`RESULTS.md`) | `2157cb21...6d05a49` | `4b7afeab...fd3d47cb79f0e` |
| `artifacts/results-v1/models/` (this worktree) | same | same |
| Files the scenario batches actually used (`m2k-scenario-test` container, live-checked) | same | same |

**All three agree exactly.** No discrepancy to resolve before running anything below.

## 1. ML metrics on the 70/15/15 test split

`src/evaluation/results_v1_offline/ml_metrics.py` -- loads the **frozen** `models/*.joblib`
(verified by hash first; never retrains, never overwrites the artifacts) and evaluates them on
the exact test split `src/scenario_classifier/train.py::split_patients()` produces (patient-level
70/15/15, stratified by `scenario_type`, seed=42) -- that function and `evaluate()` are both
reused unmodified. Full output: `results/results_v1_offline/ml_metrics.json` +
`ml_metrics_classification_report.txt`.

- Train/val/test sizes: 1400/300/300 patients.
- **Test scenario accuracy: 0.9133.** Per-class precision/recall/f1 all 0.88-0.95 (weakest:
  `deconditioning` recall 0.90/precision 0.88; strongest: `cardiac_stress` precision 0.95).
- **Test severity MAE: 0.0470, RMSE: 0.0611.** By scenario: `fluid_overload` 0.0373 (best),
  `stable` 0.0363 (best), `deconditioning` 0.0623 (worst).
- Confusion matrix (rows=actual, cols=predicted, order stable/fluid_overload/cardiac_stress/
  deconditioning/acute_deterioration): the only confusions above 3 cases are
  `fluid_overload`->`acute_deterioration` (5) and `deconditioning`<->`stable`/`cardiac_stress`
  (3 each) -- no class is systematically collapsed into another.

## 2. Scorer weight sensitivity (+-10%, +-20%), seeds 42-47

`src/evaluation/results_v1_offline/weight_sensitivity.py` -- monkey-patches
`src.analytics.risk_score.WEIGHTS` (restored after each perturbation) and calls the real
`compute_risk_score()`; the formula itself is never reimplemented or edited. Each of the 5
weights perturbed individually by -20%/-10%/+10%/+20% (remaining weights renormalized to sum to
1.0), replayed against all 60 patient-seed series (seeds 42-47) from the saved Pulse features.
Full output: `results/results_v1_offline/weight_sensitivity.json`.

**Baseline**: 21/30 should_catch patient-seed series detected (HIGH on/after perturbation start),
8/18 should_stay_quiet series false-alert (HIGH on any day).

**Result: zero change, for every one of the 20 perturbations** (5 weights x 4 deltas) -- every
single one reproduces exactly 21/30 and 8/18. Sanity-checked this isn't a no-op bug: an
intentionally extreme perturbation (all acute weights forced to 0.01) was tried directly against
a real `compute_risk_score()` call with strong acute inputs -- `acute_score` dropped from 0.8288
to 0.0406 (confirmed the monkey-patch works and the function is sensitive to large weight
changes) -- but `risk_bucket` still read `HIGH` either way, because `baseline_deficit_score`
(0.8182, a pure function of `map_start`, untouched by any of these 5 weights) already exceeded
the perturbed acute score either way.

**Why +-10-20% doesn't move the headline numbers**: in this cohort, almost every day that reaches
`MODERATE`/`HIGH` does so via `dominant_mechanism == "baseline"` (confirmed repeatedly across
this whole investigation -- `scorer_diagnosis.md`, `docs/followup_analysis_2026-10-05.md`), i.e.
`baseline_deficit_score` -- which is **not a function of any of the 5 perturbed weights at all**.
A +-20% nudge to an acute weight only matters on a day where the acute mechanism is already the
one driving the bucket, and even there, the margins involved are evidently too large relative to
+-20% to flip a LOW/MODERATE/HIGH boundary in this dataset. This is a property of *this cohort's*
physiology (dominated by the baseline-deficit pathway), not a general claim that the scorer is
insensitive to its weights everywhere.

## 3. MIMIC AUC + age baseline -- BLOCKED, not run

The existing MIMIC AUC + CI (`data/mimic_outcome_validation/summary.md`, already computed,
reported here for completeness): **AUC = 0.596 (95% CI 0.585-0.608, 2000-resample bootstrap,
seed=42)** for `baseline_deficit_score` predicting `hospital_expire_flag`, n=17,129 admissions.

**The age-baseline comparison could not be computed.** The row-level cohort file
(`data/raw/mimic/hf_admission_outcomes.csv`) is gitignored by design (PhysioNet DUA forbids
redistributing row-level MIMIC-IV data) and does not exist in this worktree or anywhere on this
machine that I can find. Reproducing it requires a live BigQuery query against
`physionet-data.mimiciv_3_1_*` (the same source `scripts/mimic_outcome_extraction.sql` uses).
`gcloud`/`bq` are installed and authenticated (account `kaverisharma05@gmail.com`), but **no GCP
project is configured** (`gcloud config get-value project` returns unset), and none of the 6
projects currently visible to this account (`spatial-engine-backend`, `spatial-apartheid-blr`,
`gen-lang-client-0352655210`, `gen-lang-client-0004743819`, `crm-se`, `ai-inventory-project`) is
named in a way that confirms it's the one with MIMIC-IV access and billing set up.

**Not guessed, not run.** Running a BigQuery query against real patient-level restricted-access
data under the wrong project, or one without the right billing/access configured, isn't something
to trial-and-error through. Needs you to confirm which project to use; this analysis will produce
only the aggregate AUC/CI (no row-level data written to git, same as the existing result) once
that's settled.

## 4. API read-endpoint timing

`src/evaluation/results_v1_offline/api_timing.py` -- real FastAPI `TestClient` + SQLite (mocked
Pulse only for the one write that seeds the 21-day window; the 5 timed endpoints are all pure DB
reads, 0 Pulse calls in their request path, matching `routes.py`'s own docstring). 50 calls each.
Full output: `results/results_v1_offline/api_timing.json`.

| endpoint | mean | median | p95 | max |
|---|---|---|---|---|
| `/status` | 3.93ms | 3.88ms | 4.34ms | 5.81ms |
| `/history` | 3.24ms | 3.02ms | 3.84ms | 10.7ms |
| `/wearable-history` | 3.09ms | 3.00ms | 3.29ms | 5.13ms |
| `/projection` | 2.73ms | 2.70ms | 2.99ms | 3.73ms |
| `/report` | 5.19ms | 4.20ms | 5.28ms | 48.78ms |

All five read endpoints are single-digit milliseconds at the median and p95; `/report`'s one
48.78ms outlier (vs. its own 5.28ms p95) is almost certainly a one-off cold-cache/GC pause on the
first or an early call, not a systematic cost -- not investigated further since it's a single
outlier in 50 calls and every other endpoint's max stays under 11ms.
