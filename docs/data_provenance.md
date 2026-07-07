# Data Provenance

Single source of truth for every clinical threshold / distribution parameter used anywhere in this
codebase. Every number used in `src/data_synthesis/`, `src/rules.py`, or later ML/analytics code
must trace back to a row here. No magic numbers in code (see CLAUDE.md "Known Gotchas").

Never real patient data in anything committed to git — real datasets live under `data/raw/`
(gitignored) and only their *aggregate statistics* (mean/SD/range) are written into
`src/data_synthesis/reference_stats.yaml` and this file. Synthetic patient/wearable data generated
from those statistics is what actually ships in the repo (see CLAUDE.md "Locked Phase 0 Decisions").

## Real datasets acquired (2026-07-07)

| Key | What it is | Access | Rows | Location |
|---|---|---|---|---|
| `mimic_bigquery_extract` | Real MIMIC-IV HF admissions: age, gender, mean HR/SBP/DBP, creatinine, sodium, aggregated per admission | PhysioNet-credentialed, queried via Google BigQuery (`physionet-data` project); pre-extracted CSV supplied by user | 11,837 admissions / 9,293 unique patients | `data/raw/mimic/hf_patient_features_clean.csv` (gitignored) |
| `andrewmvd_kaggle` | Chicco & Jurman (2020) heart failure clinical records — the canonical, most-cited HF Kaggle dataset (184k+ downloads, CC BY 4.0). Only source we have with ejection fraction. | Kaggle API (`andrewmvd/heart-failure-clinical-data`) | 299 patients | `data/raw/kaggle/andrewmvd_clinical/` (gitignored) |
| `fedesoriano_kaggle` | General cardiovascular risk dataset (combined Cleveland/Hungarian/Switzerland/VA + Statlog cohorts). **Not HF-specific** — used only as a general age/BP/HR cross-check, never for EF/BNP. | Kaggle API (`fedesoriano/heart-failure-prediction`) | 918 patients | `data/raw/kaggle/fedesoriano_prediction/` (gitignored) |
| `nhanes_kaggle` | Official CDC NHANES survey (`demographic.csv` joined with `examination.csv` on SEQN, filtered to adults ≥18 with valid height+weight). **Not HF-specific** — general US population — but the only source we have with any anthropometrics at all. | Kaggle API (`cdc/national-health-and-nutrition-examination-survey`, files `demographic.csv` + `examination.csv` only) | 5,847 adults (2,791 male / 3,056 female) | `data/raw/kaggle/cdc_nhanes/` (gitignored) |

All aggregate stats below are computed reproducibly by `src/data_synthesis/reference_extraction.py`
— rerun it any time to regenerate this table's numbers from the raw files (MIMIC itself isn't
redownloadable by the script since it requires PhysioNet credentials; the Kaggle sources are).

**Rejected candidate:** `aadarshvelu/heart-failure-prediction-clinical-records` (n=5,000, same
column schema as `andrewmvd_kaggle`). Checked and found to be a resampled/augmented version of the
same small underlying pool, not 5,000 independent patients: only 203 unique `platelets` values
across 5,000 rows, 3,680 exact duplicate rows, and mean/SD nearly identical to `andrewmvd_kaggle`'s
299 rows. Using it as a "third source" would silently double-count the same ~300 real patients
while implying a much larger independent sample — excluded for that reason.

**Also considered and skipped:** PMData (Simula Research wearable dataset). It's a real, public
dataset, but it's general fitness/lifelogging data from 16 participants, not heart-failure-patient
data — the planning doc's description of it as "wearable data collected from heart failure
patients" doesn't match what's actually in it. Decision: skip it; the synthetic
`data/synthetic/wearable_trends.csv` (generator-produced, see Phase 1) remains the actual labeled
wearable training source for now.

## Reference Table

| Parameter | Value / Range | Source Key | Citation | Status |
|---|---|---|---|---|
| Age (HF admissions) | mean 68.72, SD 13.73, n=11,837 | `mimic_bigquery_extract` | MIMIC-IV via BigQuery | derived from real dataset |
| Age (general HF cohort, cross-check) | mean 61.49, SD 13.88 | `sinha_2024` | Sinha et al. | seeded from planning doc example; skews younger than MIMIC's acute-inpatient cohort (different population, expected) |
| Sex ratio (HF admissions) | 56.3% male | `mimic_bigquery_extract` | MIMIC-IV via BigQuery | derived from real dataset |
| Sex ratio (cross-check) | 64.9% male | `andrewmvd_kaggle` | Chicco & Jurman 2020 | derived from real dataset |
| Ejection Fraction, HFrEF (EF≤40%) | mean 32.3%, SD 6.8, range 14–40%, n=219 | `andrewmvd_kaggle` | Chicco & Jurman 2020 | derived from real dataset |
| Ejection Fraction, HFpEF (EF≥50%) | mean 56.9%, SD 6.0, range 50–80%, n=60 | `andrewmvd_kaggle` | Chicco & Jurman 2020 | derived from real dataset |
| Ejection Fraction, healthy control | mean 62%, range 55–70% | — | — | **still assumed_default** — `andrewmvd_kaggle` is all-HF-patients, no true healthy-control EF source yet |
| Serum creatinine | mean 1.82 mg/dL, SD 1.58 | `mimic_bigquery_extract` | MIMIC-IV via BigQuery | derived from real dataset (cross-check: `andrewmvd_kaggle` mean 1.39, SD 1.03) |
| Serum sodium | mean 138.4 mEq/L, SD 4.2 | `mimic_bigquery_extract` | MIMIC-IV via BigQuery | derived from real dataset (cross-check: `andrewmvd_kaggle` mean 136.6, SD 4.4) |
| Resting HR / RestingBP (general population cross-check only) | HR mean 84.75 (inpatient, MIMIC) / BP mean 132.4 (fedesoriano) | `mimic_bigquery_extract`, `fedesoriano_kaggle` | — | derived, but **not used as wearable_baseline** — see note below |
| Height (male) | mean 174.3 cm, SD 7.8, n=2,791 | `nhanes_kaggle` | CDC NHANES | derived from real dataset |
| Height (female) | mean 160.5 cm, SD 7.1, n=3,056 | `nhanes_kaggle` | CDC NHANES | derived from real dataset |
| Weight (male) | mean 86.4 kg, SD 21.3 | `nhanes_kaggle` | CDC NHANES | derived from real dataset — note the wide SD reflects real US adult obesity prevalence, appropriate for an HF-risk cohort |
| Weight (female) | mean 76.0 kg, SD 21.8 | `nhanes_kaggle` | CDC NHANES | derived from real dataset, same note as above |
| NT-proBNP diagnostic cutoff, age < 50 | > 450 pg/mL | `bhosale_2024` | Bhosale et al. | seeded from planning doc example |
| NT-proBNP diagnostic cutoff, age 50–75 | > 900 pg/mL | `bhosale_2024` | Bhosale et al. | seeded from planning doc example |
| NT-proBNP diagnostic cutoff, age > 75 | > 1800 pg/mL | `bhosale_2024` | Bhosale et al. | seeded from planning doc example |
| BNP (not NT-proBNP) general threshold | > 35 pg/mL | (AHA/ACC 2022 guideline, Stage B criterion) | 2022 AHA/ACC/HFSA Guideline | from planning doc, needs page ref; TODO — no acquired dataset measures BNP at all |
| LVEF Stage B threshold | ≤ 40% | (AHA/ACC 2022 guideline) | 2022 AHA/ACC/HFSA Guideline | from planning doc, needs page ref |
| Ohte et al. parameters | — | — | Ohte et al. | TODO — not yet extracted |
| NYHA class ↔ METs mapping | I: >7 METs, II: 5–7, III: 2–5, IV: <2 | — | heart.org / AHA NYHA classification | seeded from planning doc |

**Note on wearable_baseline resting HR:** MIMIC's mean HR (84.75, SD 15.06) and fedesoriano's
RestingBP (132.4, SD 18.5) are measurements of acutely-ill inpatients / a coronary-clinic cohort —
not an at-home stable wearable user. They were deliberately **not** used to set
`wearable_baseline.resting_hr_bpm` (kept at the assumed-default 70±8) because doing so would make
every synthetic patient look tachycardic at rest by construction. They're kept in
`reference_stats.yaml` as a decompensated-state sanity ceiling instead — see the comment there.

## How to extend this file

1. Add a row before using any new number in code.
2. Prefer citing the exact page/table of the source paper once you have it, not just the paper name.
3. Update `src/data_synthesis/reference_stats.yaml` in lockstep — that file must mirror this table's
   `sourced` values exactly (see the `source` key on every entry there).
4. If a new value comes from a real dataset, add extraction logic to
   `src/data_synthesis/reference_extraction.py` rather than hand-computing it once — keeps every
   number reproducible from `data/raw/`.
