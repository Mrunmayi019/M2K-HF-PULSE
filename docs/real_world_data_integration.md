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

**Status: done — 16/16 eligible real patients completed.** Canonical file:
`data/real_world_validation/20260802_234002/combined_results.csv` (merged across every run in this
section's history via `--resume-from`; every intermediate run directory below is kept on disk as
raw audit trail, not the citation target). Full pipeline (ML classification → Pulse → risk scoring
→ staging → projection) executed successfully, with zero mocking, on real physiological data from
27 real heart-failure patients, 16 of whom had enough real daily coverage to fill a genuine 21-day
window (§5).

### 8.1 Aggregate results

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
