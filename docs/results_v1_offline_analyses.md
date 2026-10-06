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
8/18 should_stay_quiet series false-alert (HIGH on any day). **Clarification (2026-10-07): this
21/30 is the "any ALERT on/after perturbation start" measure, not "story-driven" in the stricter
sense (the series' own first-ever ALERT occurring on/after perturbation start) -- this script
never computed that stricter condition. The stricter count, computed separately
(`docs/followup_analysis_2026-10-07.md`, `fix/unified-alert-decision`), is 14/30. Both numbers
describe the UNPERTURBED baseline; this section's actual subject (weight sensitivity) is
unaffected either way, since the finding is that none of the 20 perturbations change the 21/30
or 8/18 counts at all, regardless of which detection definition is used.**

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

## 5. PerHeart cohort table and flow diagram

Script: `src/evaluation/results_v1_offline/cohort_plausibility_projection.py` (offline, no Pulse).
Outputs: `results/results_v1_offline/perheart_cohort_table.csv` (all 27 patients) and
`figures/perheart_flow.png`.

**27 in → 16 eligible and replayed → 13 completed.**

- **Eligibility:** the only rule is ≥21 overlapping real HR+SpO2+weight days.
  `docs/real_world_data_integration.md` §5 records the rule and the 16 eligible `user_id`s (1, 2, 4,
  5, 6, 15, 16, 17, 18, 19, 21, 22, 23, 24, 25, 27).
- **Excluded (11):** `user_id` 3, 7, 8, 9, 10, 11, 12, 13, 14, 20, 26, for having fewer than 21
  overlapping days. Their **per-patient day counts, ages and sex were never recorded** (the raw
  PerHeart files are gitignored and were not re-read), so they appear as "not recorded" in the table.
- **Failed (3):** `user_id` 6, 18, 22, in the latest replay (`data/real_world_validation/20260817_141634`).
  `PulseScenarioDriver exited 1` on both attempts. The root cause is **not recorded**: §8.4 gives a
  severity-shift hypothesis only.
- **Completed (13):** 9 cardiac_stress, 3 stable, 1 fluid_overload. Risk buckets: 5 HIGH, 4 MODERATE,
  4 LOW.

## 6. Physiological plausibility of the saved Pulse batch

Output: `plausibility_by_scenario.csv`. Data: `data/simulation_runs/features_dataset.csv`
(117 completed runs; the 33 rows in `failed_runs.csv` have no outputs).

**Ranges used.** These are the only ones `src/data_synthesis/reference_stats.yaml` defines for any of
MAP, cardiac output, stroke volume or heart rate. Both are heart-rate entries, taken as mean ± 2 SD:

- `wearable_baseline.resting_hr_bpm`: 70 ± 8, so **54–86 bpm**. Status `assumed_default`, `source: null`.
- `wearable_baseline.decompensated_hr_reference`: 84.75 ± 15.06, so **54.6–114.9 bpm**. Source
  `mimic_bigquery_extract` (MIMIC-IV inpatient HR); labelled "sanity ceiling" in the YAML.

**MAP, cardiac output and stroke volume: not computed.** `reference_stats.yaml` has no range for
them, and none was invented.

| Scenario | n | HR at start inside 54–86 / 54.6–114.9 | HR at end inside 54–86 / 54.6–114.9 |
|---|---|---|---|
| stable | 30 | 100% / 100% | 100% / 100% |
| deconditioning | 30 | 100% / 100% | 100% / 100% |
| fluid_overload | 30 | 100% / 100% | 100% / 100% |
| cardiac_stress | 15 | 100% / 100% | **0% / 0%** |
| acute_deterioration | 12 | 100% / 100% | **0% / 25%** |
| all | 117 | 100% / 100% | 76.9% / 79.5% |

Every run starts inside both HR ranges. The end-of-run values outside them all come from the two
scenarios that add an `Exercise` action (`scenario_file.py`). Both ranges are **resting** references,
so an exertion heart rate above them is expected rather than evidence of implausibility. These
ranges can't judge exercise-phase values.

## 7. Dose response: severity vs Pulse outputs, by scenario and EF group

Output: `dose_response_by_scenario_ef.csv`. Spearman ρ between classifier severity and end-of-run
values; groups with n < 5 are not computed.

| Scenario | EF group | n | MAP | Cardiac output | Stroke volume | Heart rate |
|---|---|---|---|---|---|---|
| stable | EF > 40 | 30 | 0.03 (p 0.87) | −0.12 (0.53) | −0.08 (0.66) | −0.05 (0.79) |
| deconditioning | EF > 40 | 26 | **−0.83** (<0.001) | 0.10 (0.61) | **0.58** (0.002) | **−0.79** (<0.001) |
| deconditioning | EF ≤ 40 | 4 | not computed | | | |
| fluid_overload | EF ≤ 40 | 29 | 0.15 (0.44) | **0.49** (0.007) | **0.46** (0.012) | **0.84** (<0.001) |
| fluid_overload | EF > 40 | 1 | not computed | | | |
| cardiac_stress | EF > 40 | 14 | **−0.73** (0.003) | **0.81** (<0.001) | −0.07 (0.80) | **0.92** (<0.001) |
| cardiac_stress | EF ≤ 40 | 1 | not computed | | | |
| acute_deterioration | EF ≤ 40 | 12 | −0.32 (0.31) | **0.92** (<0.001) | −0.26 (0.42) | **0.89** (<0.001) |
| acute_deterioration | EF > 40 | 0 | not computed | | | |

**Caveat:** in this batch, scenario and EF group are almost confounded. Synthetic acute_deterioration
patients all have EF ≤ 40 and stable patients all have EF > 40. So **no scenario supports an EF ≤ 40
vs EF > 40 comparison**: each one has fewer than 5 patients in one of the two groups.

**Findings:**
- **Stable** shows no dose response, as intended.
- **The two Exercise scenarios** show strong severity → HR and severity → cardiac output responses,
  driven by exercise intensity scaling with severity.
- **cardiac_stress** also shows a severity → MAP fall.
- **Deconditioning:** higher severity *lowers* HR (ρ −0.79) and MAP.
- **fluid_overload:** severity barely moves MAP (ρ 0.15). That's consistent with the documented lack
  of a volume-loading mechanism (methodology §8).

## 8. Forward projections for the three live-test patients

Output: `live_projections.csv`; inputs saved in `live_projection_inputs.json`. These are real Pulse
projection runs from `docs/app_integration_audit.md` §3b. The projection, risk, feature, builder,
runner and classifier code there is identical to `results-v1` (verified by `git diff`), with the
same frozen models.

| Patient | EF | Scenario | Risk now | +7 d | +14 d | +30 d | Bucket | Severity now → +30 d | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| P1 | 30 (measured) | deconditioning | 0.4874 | 0.4874 | 0.4874 | 0.4874 | MODERATE throughout | 0.587 → 0.668 | **Flat** |
| P2 | blank (62% default) | deconditioning | 0.0654 | 0.0645 | 0.0679 | 0.0721 | LOW throughout | 0.727 → 0.814 | **Near-flat** (Δ 0.008) |
| P3 | blank (62% default) | fluid_overload | 0.0000 | 0.0000 | 0.0000 | 0.0000 | LOW throughout | 0.665 → 0.808 | **Flat** |

**Projected risk is flat for all three, even though projected severity rises 0.08–0.14.**

- **P1:** the risk is the EF-driven `baseline_deficit_score` (0.4874), which no projected severity
  changes.
- **P2 and P3:** the defaulted EF gives a structurally normal simulated heart, and neither scenario
  adds Exercise, so nothing pushes MAP down at any horizon.

The dashboard's per-horizon risk bucket therefore never changes for these patients. Only the
projected severity line moves.
