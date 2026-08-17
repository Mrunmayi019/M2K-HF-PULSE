-- HANDOFF.md P1 "real clinical outcome validation" -- narrow-scope pass, Step 3.
--
-- Extracts a cohort for testing ONE mechanism in src/analytics/risk_score.py -- the
-- baseline_deficit_score term, f(map_start) -- against real in-hospital mortality. This is NOT
-- an extraction for the full pipeline (ML Model 1 / Pulse simulation / the acute risk_score
-- components): those need a 21-day ambulatory wearable trend and a measured ejection fraction,
-- neither of which exists in MIMIC-IV (confirmed via schema/aggregate checks during planning --
-- EF's only chartevents itemid, 227008, has 0 actual measurements in this dataset; median
-- hospital stay is 3 days, only 2.9% of admissions reach 21 days at all).
--
-- Cohort definition:
--   1. HF admissions: any hadm_id with an ICD-9 428.x or ICD-10 I50.x diagnosis code
--      (diagnoses_icd joined to itself via icd_version -- these are the standard, widely used HF
--      diagnosis code prefixes in the MIMIC literature; NOT verified to be the exact same
--      definition the original mimic_bigquery_extract used to get its 11,837 figure, since that
--      query isn't in this repo -- flagged as a difference, not assumed identical).
--   2. Restricted to admissions with >=1 real MAP (mean arterial pressure) reading in
--      mimiciv_3_1_derived.vitalsign STRICTLY within the first 24h of the admission
--      (admittime <= charttime < admittime + 24h) -- the map_start guardrail. vitalsign is an
--      ICU-derived table, so this cohort is implicitly ICU-admitted HF patients (the population
--      MAP is actually measured frequently enough for), not every HF admission in the hospital.
--   3. NOT filtered by outcome -- every eligible admission is included regardless of
--      hospital_expire_flag.
--   4. NOT joined to labevents/NT-proBNP at all (excluded per explicit instruction -- diagnostic,
--      not predictive, in this context, and would confound a single-mechanism test).
--   5. discharge_location is deliberately NOT selected -- outcome-adjacent, must never be a
--      feature.
--
-- age/sex are pulled for cohort description only (Table 1 in the writeup), not used in the
-- tested mechanism (compute_risk_score() is called with only map_start varying -- see
-- scripts/mimic_outcome_validation.py).
--
-- Run via: bq query --use_legacy_sql=false --project_id=ai-inventory-project \
--   --format=csv --max_rows=50000 < scripts/mimic_outcome_extraction.sql \
--   > data/raw/mimic/hf_admission_outcomes.csv
-- (gitignored under data/raw/, per this project's existing "never real patient data in git" rule)

WITH hf_admissions AS (
  SELECT DISTINCT d.hadm_id
  FROM `physionet-data.mimiciv_3_1_hosp.diagnoses_icd` d
  WHERE (d.icd_version = 9 AND d.icd_code LIKE '428%')
     OR (d.icd_version = 10 AND d.icd_code LIKE 'I50%')
),
first24h_map AS (
  SELECT
    a.hadm_id,
    a.subject_id,
    AVG(v.mbp) AS map_start_mmhg,
    COUNT(v.mbp) AS n_map_readings_24h
  FROM `physionet-data.mimiciv_3_1_hosp.admissions` a
  JOIN hf_admissions hf ON hf.hadm_id = a.hadm_id
  JOIN `physionet-data.mimiciv_3_1_icu.icustays` icu ON icu.hadm_id = a.hadm_id
  JOIN `physionet-data.mimiciv_3_1_derived.vitalsign` v ON v.stay_id = icu.stay_id
  WHERE v.mbp IS NOT NULL
    AND v.charttime >= a.admittime
    AND v.charttime < DATETIME_ADD(a.admittime, INTERVAL 24 HOUR)
  GROUP BY a.hadm_id, a.subject_id
)
SELECT
  f.hadm_id,
  f.subject_id,
  f.map_start_mmhg,
  f.n_map_readings_24h,
  a.hospital_expire_flag,
  p.anchor_age AS age,
  p.gender AS sex
FROM first24h_map f
JOIN `physionet-data.mimiciv_3_1_hosp.admissions` a ON a.hadm_id = f.hadm_id
JOIN `physionet-data.mimiciv_3_1_hosp.patients` p ON p.subject_id = f.subject_id
