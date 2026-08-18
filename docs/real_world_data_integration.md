# Real-World Data Integration — PerHeart Dataset Validation

Status: done. This document records the real-world validation pass requested for the research
paper: replaying real heart-failure patient physiological data through the actual production
pipeline (ML classification → Pulse → risk scoring → staging → projection), in place of this
project's own synthetic input data. Same evidence-first convention as `methodology.md` §7/§8/§11
and `docs/frontend_extension_validation.md` — every claim below is backed by a file actually
downloaded and inspected, or a command actually run, not asserted from a dataset's description.

## 1. Why this exists

Every prior validation of this pipeline (`methodology.md` §7, §8) used either fully synthetic
patients (`src/data_synthesis/`) or hand-typed demo values (the Simulation Lab wizard,
`docs/frontend_extension_validation.md`). Neither establishes that the pipeline behaves sensibly
on *real* physiological measurements from *real* heart-failure patients. This document adds that
pass, using a real, published, ethics-approved dataset — not a live device integration (a
separate, larger undertaking scoped out in favor of this, since it gives real data without the
engineering cost of an OAuth device connector).

## 2. Dataset

**PerHeart Pilot Dataset: Wrist-worn Inertial Sensor and Physiological Data from Older Adults with
Heart Failure.** Kolakowski, M., Djaja-Josko, V., Kolakowski, J., Mocanu, I., Cramariuc, O.,
Gasowski, J., Piotrowicz, K. Published in *Data* (MDPI), 2026, 11(5), 106.
DOI: [10.3390/data11050106](https://doi.org/10.3390/data11050106). Dataset hosted on Zenodo:
[10.5281/zenodo.17143199](https://doi.org/10.5281/zenodo.17143199) (concept DOI; the specific
version pulled for this work resolves to record `17459937`).

- **Population:** 27 older adults with a history of heart failure, ages 67–94 (verified directly
  from `personal_questionnaires.csv`), recruited as patients of University Hospital in Cracow,
  Poland.
- **Collection:** one-month in-home trials, each participant supplied with a digital bathroom
  scale (A&D UC-352BLE), a digital pulse oximeter (Jumper JPD-500F BLE), a digital blood pressure
  meter (A&D UA-651BLE or Beurer BM95), a digital thermometer, and (selected users) a glucometer.
  A tablet relayed raw device readings to the PerHeart database with no processing applied.
- **Ethics:** approved by the Jagiellonian University Ethics Committee (ref. `1072.6120.17.2023`,
  15/02/2023); written informed consent obtained from all participants.
- **Funding:** Polish National Centre for Research and Development, grant
  `PerMed/II/34/PerHeart/2022`.

This project also considered and set aside the **Kaggle "FitBit Fitness Tracker Data"** dataset
(`arashnic/fitbit`, CC0, 30 users, daily activity/HR/sleep, Amazon Mechanical Turk respondents,
03–05.2016). Rejected for this purpose: general healthy-population consumer fitness data, not
heart-failure patients, and it doesn't measure SpO2 or HRV at all — weaker fit than PerHeart on
both the clinical-relevance and field-coverage axes. Recorded here in the same
"considered-and-skipped" convention `docs/data_provenance.md` already uses for `PMData`.

### 2.1 License — a discrepancy found, not silently resolved

Zenodo's structured record metadata (`GET /api/records/17143199`, `metadata.license.id`) declares
**`cc-by-4.0`**. The dataset's own bundled `load_dataset.py` — first-party, written by the
dataset's authors — has a footer comment stating: *"The dataset is distributed under the terms and
conditions of the Attribution NonCommercial ShareAlike (CC BY-NC-SA) license."* These two
statements disagree and were not reconciled with the authors before this work. Treating the more
restrictive reading as binding (consistent with this project's existing "never real patient data
in git" discipline, `docs/data_provenance.md` line 7):

- Raw PerHeart files are downloaded to `data/raw/perheart/` (gitignored — matches the existing
  `mimic`/`kaggle` raw-data folders), never committed.
- Derived model outputs (`data/real_world_validation/<run>/results.csv`, keyed only to the
  dataset's own existing pseudonymous `user_id` 1–27 — no new identifying information) are
  committed for paper reproducibility, each run carrying its own `LICENSE_NOTE.md` declaring
  CC BY-NC-SA 4.0 attribution, satisfying ShareAlike under either license reading.
- Non-commercial academic/research use (this paper) is permitted under both readings.

## 3. What's actually in the dataset (verified by direct download)

`medical.zip` (32,561 bytes) extracts to 5 CSVs. Verified column-by-column against real file
contents, not the paper's prose description:

| File | Rows | Real users | Columns |
|---|---|---|---|
| `oxidation.csv` (pulse oximeter) | 874 | 19 | `user_id, ts, hr, perf, sat` |
| `body_mass.csv` (bathroom scale) | 1,018 | 27 | `user_id, ts, value` |
| `blood_pressure.csv` (BP cuff) | 1,195 | 27 | `user_id, ts, device, bp_sys, bp_dia, hr, comm` |
| `glucose.csv` (glucometer, diabetic users only) | 180 | — | not used |
| `temperature.csv` (thermometer) | 914 | — | not used |
| `personal_questionnaires.csv` | 27 | 27 | `age, sex (1=M/2=F), mmse_total, barthel, ...` |

`wrist.zip` (4.6 GB — real wrist-worn IMU/step data, only 8 of 27 users, cumulative step counter
in raw parquet files) was deliberately **not used** in this pass — see §6.

## 4. Field mapping — real vs. imputed

This dataset does not measure everything `WearableReadingCreate`/`PatientCreate` need. Every gap
is filled with a value **already established elsewhere in this repo** — never a new number
invented for this script — and every substitution is explicit, matching how `src/api/services.py`
already flags `ef_is_fallback`/`bnp_is_fallback` rather than silently blending fallback values with
real ones.

| Field | Source | Real or imputed |
|---|---|---|
| `resting_hr_bpm` | `oxidation.csv` `hr`, daily mean | **Real** |
| `spo2_pct` | `oxidation.csv` `sat`, daily mean | **Real** |
| `weight_kg` | `body_mass.csv` `value`, daily mean | **Real** |
| `age` | `personal_questionnaires.csv` | **Real** |
| `sex` | `personal_questionnaires.csv` (1→Male, 2→Female) | **Real** |
| `height_cm` | Not measured by this dataset | Imputed — NHANES sex-mean already in `reference_stats.yaml` (male 174.32cm / female 160.46cm) |
| `sleep_hours` | Not measured | Imputed — existing `wearable_baseline.sleep_hours` mean (7.0h), held constant, no noise added |
| `hrv_rmssd_ms` | Not measured | Imputed — existing `wearable_baseline.hrv_rmssd_ms` mean (35ms), held constant |
| `steps_per_day` | Not measured (real step data exists only in the unused `wrist.zip`, §6) | Imputed — existing `wearable_baseline.steps_per_day` mean (6000), held constant |
| `ejection_fraction_pct` | Not measured — no clinical biomarkers in this dataset | Left `null` → API's existing Tier 1 fallback (`apply_tier1_fallback`) fires, `ef_is_fallback=true` |
| `nt_probnp_pg_ml` | Not measured | Left `null` → Tier 1 fallback, `bnp_is_fallback=true` |

**On `resting_hr_bpm`'s clinical meaning:** the pulse oximeter's `hr` reading is a spot-check
measurement taken whenever the participant used the device during the day, not a continuous
nocturnal/resting-state algorithm the way a consumer wearable computes "resting heart rate." The
daily mean of these spot-checks is used as this project's `resting_hr_bpm` proxy — a real
measurement, but not identical in method to how the rest of this project's schema field is
usually populated (synthetic data, `src/data_synthesis/generate_wearable_trends.py`). Flagged here
so it isn't overstated in the paper.

## 5. Coverage — which patients qualify, and how that was decided

A patient is eligible only if the *real* data itself spans a full 21-day window — no day is ever
fabricated or interpolated to fill a gap (only individual *fields* are imputed, per §4, never
whole *days*). Computed by inner-joining `oxidation.csv` and `body_mass.csv` on
`(user_id, calendar_date)` and counting distinct dates per user:

**16 of 27 real patients** (`user_id` 1, 2, 4, 5, 6, 15, 16, 17, 18, 19, 21, 22, 23, 24, 25, 27)
have ≥21 real overlapping days of HR+SpO2+weight coverage. This count is computed programmatically
by `scripts/perheart_real_data_replay.py` every run, not hardcoded — reproducible directly from
the source files.

## 6. Explicitly out of scope for this pass

- **`wrist.zip`'s real step-count data** (4.6 GB, 8 of 27 users, cumulative-counter parquet files
  needing delta computation + timezone-aware timestamp reconstruction) — real engineering cost for
  a field that would only help half the already-small eligible cohort. A legitimate next step for
  `steps_per_day` specifically, not attempted here. Consistent with how `methodology.md` §9 already
  scopes out similarly-costly extensions rather than silently skipping them.
- **Live wearable-device API integration** (Fitbit/Apple Health/etc.) — a separate, larger
  undertaking (OAuth, token refresh, a "connect your device" UI) discussed and deliberately
  deferred in favor of this dataset-replay approach, which gives real data without that
  engineering surface.

## 7. Implementation

`scripts/perheart_real_data_replay.py` (same family as `scripts/validate_phase8.py`, but against
a real external dataset instead of this project's own synthetic one):

1. Downloads `medical.zip` + `personal_questionnaires.csv` from Zenodo into `data/raw/perheart/`
   if not already present (idempotent; never touches `wrist.zip`).
2. Aggregates `oxidation.csv`/`body_mass.csv` to one row per `(user_id, date)`, inner-joined.
3. Filters to the ≥21-real-day cohort (§5).
4. Per eligible patient: `POST /patients` (real age/sex, imputed height, real mean weight) →
   `POST /clinical-report` (EF/BNP omitted, Tier 1 fallback fires) → 21× `POST /wearable-sync`
   replaying that patient's most recent real 21-day window against the **live running
   `docker compose` API** (same proven pattern as this session's earlier manual seeding, not
   `validate_phase8.py`'s in-container `TestClient` approach) → polls `/status` to completion.
5. Writes, per run, into `data/real_world_validation/<timestamp>/`: `results.csv` (checkpointed
   per patient, survives interruption), `mapped_readings/user_{id}.csv` (the exact daily rows
   sent, for reproducibility), `summary.md`, and `LICENSE_NOTE.md` (§2.1).

**A real, unavoidable consequence of this cohort's real ages, not a bug:** every eligible patient
is 67–94 years old — entirely outside Pulse's native 18–65 operating range
(`src/patient_builder/patient_file.py`, `PULSE_MIN_AGE_YR`/`PULSE_MAX_AGE_YR`, already documented
in `methodology.md` §4/§8 as a known limitation for exactly this kind of real, older-skewing HF
population). The existing `pulse_eligible_age`/`pulse_eligible_weight_kg` proxy-clamp — built for
this scenario, not new code — applies to the whole cohort. `results.csv` carries a
`pulse_age_capped`/`pulse_bmi_capped` column per patient so this is visible, not buried, and it is
the headline methodological caveat for any paper claim drawn from this section: **these results
show the pipeline's behavior on real patients' real clinical/wearable inputs, run through a
proxy-aged simulated body, not literally these patients' own physiology inside Pulse.**

## 8. Results

**Status: done, and re-run post-fix — 13/16 eligible real patients completed against the fixed
severity model.** Canonical file for citing post-fix severity/risk numbers:
`data/real_world_validation/20260812_162112/results.csv` (§8.4). The original pre-fix run,
`data/real_world_validation/20260802_234002/combined_results.csv` (merged across every run in this
section's history via `--resume-from`), is kept as historical record — its severity/risk-score
numbers are pre-fix and superseded, but its 16/16 completion rate and demographic/coverage
findings (§8.1) are unaffected by the fix and still stand. Full pipeline (ML classification →
Pulse → risk scoring → staging → projection) executed successfully, with zero mocking, on real
physiological data from 27 real heart-failure patients, 16 of whom had enough real daily coverage
to fill a genuine 21-day window (§5).

### 8.1 Aggregate results (pre-fix — completion rate/demographics still valid, severity/risk numbers superseded by §8.4)

| Metric | Value |
|---|---|
| Patients completed | **16/16 (100%)** |
| Age range (real) | 71–90, mean 79.75 |
| Sex | 11 Male, 5 Female |
| Required Pulse age proxy-clamp (§7) | **16/16** — every real patient is 67+, entirely above Pulse's 65-year ceiling |
| Required Pulse BMI proxy-clamp | 3/16 |
| `scenario_type` distribution | `cardiac_stress` 12, `stable` 4 |
| `risk_bucket` distribution | MODERATE 12, LOW 4 (**zero HIGH**) |
| `nyha_class` | **I, all 16** (see caveat below — likely an artifact, not a finding) |
| `deterioration_direction` | stable 15, worsening 1 |
| `severity` | mean 0.112, range 0.078–0.148 (tight) |
| `risk_score` | mean 0.321, range 0.005–0.500 |

Full per-patient breakdown is in `combined_results.csv`; the exact 21-day real-vs-imputed input
each patient's assessment was computed from is in `mapped_readings/user_{id}.csv` across the
constituent run directories.

### 8.2 Two things in these numbers that need explaining, not just reporting

**Severity is compressed into a narrow low band (0.078–0.148) for every single patient — and this
independently reproduces an already-documented bug, not a new finding about this cohort.**
`methodology.md` §7/§8 already diagnosed exactly this pattern in Phase 8's *synthetic* batch
validation: the live-inference feature builder (`build_inference_features()` in
`src/scenario_classifier/features.py`) always defaults `nyha_ordinal` to the most benign class
("I") because a brand-new patient's real NYHA class isn't known yet at prediction time — unlike
offline training, which used each patient's real, varied class. That gap was measured there as a
severity MAE of 0.271 vs. an offline benchmark of 0.048. This real-patient run shows the same
signature (severities clustered far below what the wide `cardiac_stress` classification and these
patients' real ages/comorbidity profile would suggest) — real, independent, cross-dataset
confirmation that this is a genuine pipeline limitation, not an artifact of one synthetic batch.
**Any paper claim drawn from these severity/risk-score numbers should cite this limitation
directly**, not present them as a clean population estimate.

**Update: fixed, and the full cohort has since been re-run against the fixed model.** This
independent reproduction on real PerHeart data was itself part of what motivated fixing the
underlying bug — `nyha_ordinal` was removed from the feature set entirely (not defaulted at
inference time) and both models retrained. Re-validated live against synthetic patients with known
ground-truth severity: MAE dropped from 0.271 to **0.008** (`docs/methodology.md` §9,
`models/model_card.md`). The severity numbers in §8.1 above are from the pre-fix model; see §8.4
for the post-fix re-run and its own numbers (severity is no longer compressed into a narrow low
band) and completion-rate finding.

**All 16 patients came back NYHA Class I — very likely a Tier 1 fallback artifact, not a genuine
clinical finding.** `staging.py`'s NYHA classifier gates on structural EF/BNP criteria (§6.3 of
`methodology.md`). This dataset never measured EF or NT-proBNP (§4), so every one of these 16
real patients' clinical reports used the *same* Tier 1 fallback values (EF 62%, BNP 100 pg/mL —
both deliberately "unremarkable/healthy" placeholders, `ef_is_fallback`/`bnp_is_fallback=true` on
every stored record). Feeding 16 different real patients the identical healthy-placeholder
EF/BNP and then finding they all clear the same structural gate is the expected mechanical
consequence of that fallback, not evidence that these real HF patients are uniformly Class I. A
paper should **not** cite "16/16 NYHA I" as a real-world finding about this cohort's clinical
status without this caveat attached.

### 8.3 Concurrency — what was tried, what actually worked, and why (a methods finding in its own right)

Getting to 16/16 took three concurrency levels, not one — worth reporting honestly since it's a
real characteristic of the deployed system, not just implementation trivia:

| Attempt | Workers | Basis | Outcome |
|---|---|---|---|
| 1 | 9 | `nproc`-derived (12 host CPUs − 3 reserved) | **Total failure.** 5/11 patients hit `httpx.ReadTimeout` on basic API calls; 6/11 hit the 180s Pulse timeout on *both* attempts. Root cause, confirmed from backend logs: `sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached` — `src/api/database.py`'s `create_engine()` sets no explicit pool size, so SQLAlchemy's defaults (5 + 10 overflow = 15 total connections) apply, and each patient's background pipeline holds one connection open for its *entire* multi-minute run (`services.run_assessment_pipeline`, opened once, closed at the end) — a pre-existing architectural characteristic already flagged in `methodology.md` §8 ("BackgroundTasks... not a real task queue"), now shown to bite in practice under concurrent real load. |
| 2 | 4 | `MAX_SAFE_WORKERS` cap, matching `batch_runner.py`'s independently-chosen default | **Partial.** The connection-pool failures vanished entirely (confirming that diagnosis), but 8/11 patients still hit the 180s Pulse timeout on both attempts — a *second*, independent bottleneck: genuine Pulse-level CPU contention. The Docker Desktop VM's reported 12 logical CPUs (`docker info`, `docker exec ... nproc`) do not translate into 12 truly independent execution lanes for this CPU-bound native binary under real concurrent load. |
| 3 | 2 | The only level clean in an isolated 2-patient test run earlier | **Clean.** 0 failures across all remaining patients (14 total processed at this level across two runs). |

**Takeaway for anyone re-running this:** neither host CPU count nor this project's own existing
`batch_runner.py` precedent (tuned for a different execution model — direct in-process `run_pulse()`
calls, not HTTP calls against a single-process FastAPI server) reliably predicts safe concurrency
for *this* execution path. 2 concurrent patients is the empirically-validated ceiling for the
current architecture (single `uvicorn` process, no `--workers`, default SQLAlchemy pool). Raising
either of those two shared-config limits was deliberately **not** done as part of this one-off
script — see `scripts/perheart_real_data_replay.py`'s module docstring and `MAX_SAFE_WORKERS`
comment for the full reasoning — but both are now concretely scoped, evidenced future-work items
for the project (not just "make it faster somehow").

### 8.4 Post-fix re-run (fixed severity model, `data/real_world_validation/20260812_162112/`)

Full cohort re-run at the same empirically-safe 2-worker concurrency (§8.3), fresh (not
`--resume-from` — the `nyha_ordinal` fix changes every prediction, so reusing pre-fix rows would
have silently carried stale numbers forward).

| Metric | Pre-fix (§8.1) | Post-fix (this run) |
|---|---|---|
| Patients completed | 16/16 (100%) | **13/16 (81%)** |
| `severity` | mean 0.112, range 0.078–0.148 (compressed — the bug) | mean 0.231, range 0.093–0.516 (wide — expected post-fix) |
| `risk_score` | mean 0.321, range 0.005–0.500 | mean 0.439, range 0.000–0.800 |
| `risk_bucket` | MODERATE 12, LOW 4, **HIGH 0** | HIGH 5, MODERATE 4, LOW 4 |
| `scenario_type` | `cardiac_stress` 12, `stable` 4 | `cardiac_stress` 9, `stable` 3, `fluid_overload` 1 |

**Severity is no longer compressed.** Post-fix range (0.093–0.516) is roughly 5x wider than
pre-fix (0.078–0.148), and 5 patients now land in `risk_bucket=HIGH` where before none did — the
expected, correct consequence of removing the always-benign `nyha_ordinal` default (§8.2). This is
independent, real-data confirmation of the fix beyond the synthetic re-validation in
`docs/methodology.md` §9.

**Completion rate dropped from 100% to 81% — three patients (user_id 6, 18, 22) that succeeded
pre-fix now fail with `PulseScenarioDriver exited 1` (an engine-level crash, not the usual 180s
timeout).** Worth being precise about what is and isn't established here:

- This is **not** a bug in the fix's own code path. `src/api/services.py`'s pipeline order is
  classifier inference (`clf.predict`/`reg.predict`, lines ~172–176) **before** Pulse execution
  (`run_pulse`, line ~205) — the classifier only decides `scenario_type`/`severity`, which then
  parameterize the Pulse scenario file `build_scenario_file()` generates. The crash happens inside
  the Pulse engine subprocess itself, strictly downstream of anything the fix touched.
- However, the fix **did** change what severity value gets fed into `build_scenario_file()` for
  every patient, including these three — pre-fix all three predicted `cardiac_stress` at
  severity≈0.11–0.12 (borderline-low within that scenario's range) and completed cleanly; a
  retrained model plausibly now predicts different severity for the same three patients, which
  could move their generated Pulse scenario into a numerically less stable parameter region. The
  live API's `/status` endpoint does not surface the classifier's prediction for a run that fails
  before completion, so **the actual post-fix severity value fed to Pulse for these three patients
  was not captured** and this causal link is plausible, not confirmed.
- This reads as consistent with, not contradictory to, this project's already-documented Pulse
  instability (§8.3's timeout findings; `docs/methodology.md` §5's Phase 4 finding that Pulse
  failures cluster by scenario/severity rather than occurring randomly) — engine-level crashes at
  particular parameter combinations are an existing, known characteristic of this dependency, not
  a new problem introduced here.

Root-causing this precisely (capturing the failed run's actual severity/scenario parameters,
determining whether it's reproducible at that exact input) is scoped as follow-up work — see
`PUBLICATION_TODO.md` P2 "Diagnose the 180s Pulse timeout ceiling properly," which this finding
extends to cover non-timeout engine crashes too.

**Update: the `risk_score` values in the table above predate the `fluid_overload` blind-spot fix**
(`compute_risk_score()` gained a `map_start`-based `baseline_deficit_score` term shortly after this
run — `models/model_card.md`, `docs/methodology.md` §6.1). The one `fluid_overload` patient in
this cohort (§8.1) would score materially differently post-fix (mean shift 0.000→0.501 on the
117-row Phase 4 batch, §6.1). Re-running this cohort a third time against the newest fix is
legitimate follow-up work, flagged rather than silently skipped, same as §8.2's precedent — not
done in this pass to avoid stacking a third ~90-minute Docker run against the same 2-worker
concurrency ceiling (§8.3) the expanded live re-validation (`docs/methodology.md` §9) was already
using concurrently.

### 8.5 Third re-run, against the `fluid_overload` fix (`data/real_world_validation/20260817_141634/`)

Full cohort re-run, fresh (not `--resume-from`, same reasoning as §8.4 — only `risk_score` changed
between §8.4's model and this fix, but reusing pre-fix rows would still carry stale `risk_score`
values forward for the one scenario type the fix touches). Run immediately after a clean Docker
Desktop restart (see `docs/methodology.md`'s "Known Engine Constraints" section) at the same
empirically-safe 2-worker concurrency.

**Headline finding, and it corrects §8.4's own prediction above: the fix had zero measurable
effect on this cohort's one real `fluid_overload` patient.**

| Metric | §8.4 (pre-fluid_overload-fix) | This run (post-fix) |
|---|---|---|
| Patients completed | 13/16 (81%) | **13/16 (81%) — identical** |
| Failed patients | user_id 6, 18, 22 | **user_id 6, 18, 22 — identical set, identical `PulseScenarioDriver exited 1` crash** |
| `fluid_overload` patients | user_id 27 only | user_id 27 only (same patient, same scenario classification) |
| user_27 `severity` | 0.516 | 0.518 (noise-level difference, not a real change) |
| user_27 `risk_score` / `risk_bucket` | **0.000 / LOW** | **0.000 / LOW — unchanged** |
| Every other completed patient's `risk_score` | — | unchanged to 4 decimal places for 11/12; one `cardiac_stress` patient (user_25) shifted by -0.0011, consistent with ordinary Pulse re-simulation noise, not a fix effect |

**Root cause, confirmed via the live API's own `/report` output for user_27's patient record**:
`ejection_fraction_pct: 62.0` — this is not a measured value. PerHeart never measures EF (§4), so
the Tier 1 fallback fired (`src/api/services.py`'s `apply_tier1_fallback()`), defaulting EF to
`reference_stats.yaml`'s `ejection_fraction.healthy.mean` (62%) — confirmed by the exact match.
The `fluid_overload` fix's `baseline_deficit_score` term depends on the Pulse-simulated patient's
`map_start` reflecting a congested baseline, which in turn depends on
`ef_to_cardiovascular_modifiers()` (`src/patient_builder/patient_file.py`) constructing a
structurally-diseased body from a real, disease-appropriate EF. A healthy-mean EF fallback tells
Pulse to simulate a structurally normal heart, so `map_start` comes out at/near the healthy
baseline regardless of what the wearable-trend classifier assigned as `scenario_type`/`severity` —
`component_scores` and `baseline_deficit_score` are both exactly 0.0, and the API's own
`risk_caveats` field is still emitting its pre-fix warning text ("risk_score is known to
underestimate severity for this presentation") for this patient, confirming the underestimate the
fix was built to close is still present here.

**This is a real, specific limitation of the fix's transferability, not a bug in the fix itself.**
The fix was validated and fitted entirely against the 117-row Phase 4 *synthetic* batch, where EF
is always a real, disease-appropriate simulated input (§6.1). It works as designed there. For a
real-world patient whose EF is unmeasured and Tier-1-defaulted to a population-healthy mean, the
mechanism the fix relies on (a congested simulated baseline) has no way to fire — this is a gap
between "validated on synthetic data" and "transfers to real data with missing EF," worth stating
plainly rather than letting §8.4's un-verified prediction (this patient "would score materially
differently post-fix") stand uncorrected.

**n=1 caveat**: this cohort has exactly one real `fluid_overload` patient. This finding is
specific, well-evidenced, and mechanistically explained — but it is not a statistically powered
statement about the fix's real-world performance in general, only about this one patient and the
EF-fallback interaction it surfaces. The 29/30-of-30 bucket shift documented on the synthetic batch
(§6.1) remains the fix's primary validated evidence; this real-world n=1 is a targeted stress-test
of one specific failure mode (unmeasured EF), not a contradiction of that synthetic result.

**Failed patients (user_id 6, 18, 22) — same set, same mechanism as §8.4, not new.** Identical
three patients failed with the identical crash signature in both runs; this is unrelated to the
`fluid_overload` fix (§8.4 already established the crash happens inside the Pulse subprocess,
downstream of anything either fix touches). Consistent, reproducible evidence for the
severity-shift-triggers-instability hypothesis §8.4 proposed but couldn't confirm — the same three
patients crashing identically across two independent runs, months apart, on two different fix
states, points toward *something about these three patients' post-nyha-fix severity/scenario
inputs specifically* (not random flakiness) as the trigger, though the exact severity value fed to
Pulse before the crash remains uncaptured (§8.4's same limitation).

**Timing note, corroborating `docs/methodology.md`'s "Known Engine Constraints" finding**: every
one of the 13 successful completions in this run landed in a tight 170.2-200.4s wall-clock band
(170.2, 170.3, 180.2, 180.3, 180.4, 180.4, 190.2, 190.2, 190.2, 190.4, 200.3, 200.3, 200.4) — this
emerged naturally from PerHeart's own real, diverse cohort (not selected for this), and is
consistent with that section's finding that at least some scenario/severity combinations on this
host simply take close to the 180s ceiling regardless of session state. The 3 failed patients, by
contrast, failed fast (30.1s each) — the known engine-crash signature, not the timeout one.

#### 8.5.1 Caveat-text gap closed (messaging only — the underlying limitation is still open)

Following the finding above, `risk_caveats` now distinguishes the two reasons a `fluid_overload`
patient can show a misleadingly-LOW `risk_score`: the general "the fix is a hand-tuned
approximation" caveat (unchanged), vs. a new, mechanism-specific message for exactly the condition
diagnosed here — unmeasured EF, Tier-1-fallback-defaulted, masking `baseline_deficit_score`
(`src/api/services.py`'s `EF_FALLBACK_MASKS_FLUID_OVERLOAD_CAVEAT_MESSAGE`). **Scope: messaging
only** — the EF Tier-1 fallback's value and logic are unchanged, and it deliberately stays
scenario-unaware (making it scenario-aware would leak the label being predicted into an input
feature).

**A real bug surfaced verifying this against user_27's live output, not just unit tests**: the
first implementation computed `ef_is_fallback` by calling `apply_tier1_fallback()` a *second* time
inside `_run_assessment_pipeline`, on the value already read back from the stored
`ClinicalReport` row. But `create_clinical_report()` (`src/api/routes.py`) already resolves and
*stores* the fallback value at submission time (never `NULL`, even when it was defaulted) —
alongside its own `ef_is_fallback` column, computed correctly once at that point. Re-deriving it
downstream from an already-concrete number always evaluated to `False`, so the very first live
re-attempt on user_27 still showed the stale, generic caveat text despite the code being deployed
and unit tests passing. The unit test that should have caught this didn't, because it never
submitted a clinical report at all (a valid but different path — no `ClinicalReport` row means the
pipeline's own `apply_tier1_fallback()` fallback path runs, which was never broken); fixed by
reusing `latest_report.ef_is_fallback` directly and updating the test to submit a report with a
null EF, matching `scripts/perheart_real_data_replay.py`'s actual request shape. Re-verified
against a fresh live run of user_27 after the fix — confirmed firing correctly (this section's own
evidence trail includes the corrected `risk_caveats` text).

**Checked whether this condition is narrow to just user_27, so the fix isn't presented as broader
than it is**: it genuinely is narrow, for two different, independently-confirmed reasons —
(a) PerHeart's 27-patient cohort produced exactly one `fluid_overload` case (user_27) across all
three runs so far; every other completed patient is `cardiac_stress` or `stable`, scenarios this
caveat logic doesn't touch. (b) The synthetic batch (`data/synthetic/patients.csv`, 2,000 patients,
392 of them `fluid_overload`) has **zero** null-EF rows — synthetic patients always carry a real,
generated EF value, so this masking condition structurally cannot occur there via the normal
pipeline. This isn't a gap in the check; it's the honest current shape of the data.

**What remains open, and belongs in Future Work / Limitations, not solved here**: the EF-fallback
limitation itself — that a real fluid_overload patient with unmeasured EF gets an unreliable
`risk_score` regardless of how clearly the caveat names the reason. Naming the mechanism correctly
doesn't fix the mechanism; a real EF measurement (echo) is the actual fix. A BNP-based non-invasive
proxy was investigated as a substitute and ruled out (2026-08-18, `docs/methodology.md`'s
`fluid_overload` Known Engine Constraints subsection) — the clinical literature treats EF as the
input that explains BNP, never the reverse, so no defensible EF-from-BNP formula exists to build
one from. Not attempted here, and not expected to be revisited on this specific approach.
