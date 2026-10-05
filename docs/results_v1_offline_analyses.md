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

**Result: the 5 acute weights are INACTIVE in this cohort -- not evidence the scorer is robust
to weight changes.** "Robust" would mean the outcome holds despite the weights mattering; here
they don't move the outcome because they mostly aren't the term deciding it in this specific
data (see "why" below) -- a narrower, weaker claim, true only for the physiology this cohort
happens to produce. Zero change across all 20 perturbations (5 weights x 4 deltas) -- every
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

## 3. MIMIC AUC + age baseline

**Correction (2026-10-06): the row-level cohort file does exist** -- at
`M2K-HF-PULSE-main/data/raw/mimic/hf_admission_outcomes.csv` (dated 17 Aug, predating this
session). It's gitignored by design (PhysioNet DUA forbids redistributing row-level MIMIC-IV
data), which is exactly why the earlier check of this worktree's own (separate, gitignored)
`data/raw/mimic/` came up empty -- each git worktree has its own independent untracked files on
disk; I had only checked this one. No GCP project was needed or used; copied the existing file in
(never committed, still gitignored here) and ran the age baseline directly against it.
`src/evaluation/results_v1_offline/mimic_age_baseline.py` -- reuses `scripts/mimic_outcome_
validation.py`'s own `bootstrap_auc_ci()` verbatim (same percentile-bootstrap methodology, same
seed) for a directly comparable CI; does not modify that script. Full output:
`results/results_v1_offline/mimic_age_baseline.json`.

| | AUC | 95% CI |
|---|---|---|
| `baseline_deficit_score` (existing, `data/mimic_outcome_validation/summary.md`) | 0.596 | 0.585-0.608 |
| **age alone (new)** | **0.591** | **0.579-0.602** |

n=17,129 admissions, 13,047 unique patients, 14.19% mortality -- identical cohort both rows.
**The two CIs overlap almost entirely.** Age alone discriminates in-hospital mortality about as
well as `baseline_deficit_score` does in this cohort -- `baseline_deficit_score`'s modest
discrimination (already described as modest in the existing writeup) is not clearly distinguishable
from what age alone would give you on this same population. Reported as found; no claim about
*why* (e.g. whether `map_start` and age are themselves correlated in this cohort) is made here --
that would need a joint/adjusted model, not run.

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
