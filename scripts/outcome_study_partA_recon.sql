-- docs/outcome_prediction_study.md, Part A step 1 -- RECON ONLY. No model, no outcome modelling.
--
-- Returns AGGREGATE rows only (no patient-level data leaves BigQuery): per-vital coverage of
-- time-stamped readings in the first 48h of admission, for the exact §7.X cohort (17,129 ICU HF
-- admissions / 13,047 patients).
--
-- Cohort: re-derived with the IDENTICAL definition as scripts/mimic_outcome_extraction.sql
-- (ICD-9 428.x / ICD-10 I50.x, >=1 MAP in mimiciv_3_1_derived.vitalsign within
-- [admittime, admittime+24h)). The `cohort_check` row must read 17129 / 13047 -- if it doesn't,
-- stop: the cohort drifted and nothing downstream is comparable to §7.X.
--
-- Time anchor: hospital admittime (same anchor as §7.X). Window [admittime, admittime+48h),
-- halves [0,24h) and [24h,48h).
--
-- Sources (confirm by reading the FROM clauses):
--   HR / SBP / MAP / SpO2 / RR / temperature: physionet-data.mimiciv_3_1_derived.vitalsign
--     (MIT-LCP concept table built from icu.chartevents; ICU-charted only; sbp/mbp combine
--     arterial-line and non-invasive cuff readings; temperature in deg C).
--   Weight: physionet-data.mimiciv_3_1_icu.chartevents, itemids 224639 (Daily Weight, kg),
--     226512 (Admission Weight, kg), 226531 (Admission Weight, lbs).
--
-- Two denominators are reported per vital:
--   population = 'all_17129'     -- the full §7.X cohort
--   population = 'alive_in_hosp_48h' -- the Part A modelling population: still in hospital and
--     alive at admittime+48h (dischtime >= +48h AND (deathtime IS NULL OR deathtime >= +48h)).
--
-- Run:
--   bq query --use_legacy_sql=false --project_id=ai-inventory-project --format=csv \
--     --max_rows=1000 < scripts/outcome_study_partA_recon.sql \
--     > data/outcome_prediction_study/partA_recon.csv

WITH hf_admissions AS (
  SELECT DISTINCT d.hadm_id
  FROM `physionet-data.mimiciv_3_1_hosp.diagnoses_icd` d
  WHERE (d.icd_version = 9 AND d.icd_code LIKE '428%')
     OR (d.icd_version = 10 AND d.icd_code LIKE 'I50%')
),
cohort_ids AS (
  -- identical to mimic_outcome_extraction.sql's first24h_map filter
  SELECT DISTINCT a.hadm_id
  FROM `physionet-data.mimiciv_3_1_hosp.admissions` a
  JOIN hf_admissions hf ON hf.hadm_id = a.hadm_id
  JOIN `physionet-data.mimiciv_3_1_icu.icustays` icu ON icu.hadm_id = a.hadm_id
  JOIN `physionet-data.mimiciv_3_1_derived.vitalsign` v ON v.stay_id = icu.stay_id
  WHERE v.mbp IS NOT NULL
    AND v.charttime >= a.admittime
    AND v.charttime < DATETIME_ADD(a.admittime, INTERVAL 24 HOUR)
),
cohort AS (
  SELECT
    a.hadm_id, a.subject_id, a.admittime, a.hospital_expire_flag,
    (a.dischtime >= DATETIME_ADD(a.admittime, INTERVAL 48 HOUR)
      AND (a.deathtime IS NULL OR a.deathtime >= DATETIME_ADD(a.admittime, INTERVAL 48 HOUR)))
      AS alive_in_hosp_48h,
    (a.deathtime IS NOT NULL AND a.deathtime < DATETIME_ADD(a.admittime, INTERVAL 48 HOUR))
      AS died_lt_48h
  FROM `physionet-data.mimiciv_3_1_hosp.admissions` a
  JOIN cohort_ids c ON c.hadm_id = a.hadm_id
),
vs_long AS (
  SELECT hadm_id, vital, hrs
  FROM (
    SELECT
      c.hadm_id,
      DATETIME_DIFF(v.charttime, c.admittime, MINUTE) / 60.0 AS hrs,
      CAST(v.heart_rate AS FLOAT64) AS heart_rate,
      CAST(v.sbp AS FLOAT64) AS sbp,
      CAST(v.mbp AS FLOAT64) AS map,
      CAST(v.spo2 AS FLOAT64) AS spo2,
      CAST(v.resp_rate AS FLOAT64) AS resp_rate,
      CAST(v.temperature AS FLOAT64) AS temperature
    FROM cohort c
    JOIN `physionet-data.mimiciv_3_1_icu.icustays` icu ON icu.hadm_id = c.hadm_id
    JOIN `physionet-data.mimiciv_3_1_derived.vitalsign` v ON v.stay_id = icu.stay_id
    WHERE v.charttime >= c.admittime
      AND v.charttime < DATETIME_ADD(c.admittime, INTERVAL 48 HOUR)
  )
  UNPIVOT (value FOR vital IN (heart_rate, sbp, map, spo2, resp_rate, temperature))
),
wt_long AS (
  SELECT c.hadm_id, 'weight' AS vital,
         DATETIME_DIFF(ce.charttime, c.admittime, MINUTE) / 60.0 AS hrs
  FROM cohort c
  JOIN `physionet-data.mimiciv_3_1_icu.chartevents` ce ON ce.hadm_id = c.hadm_id
  WHERE ce.itemid IN (224639, 226512, 226531)
    AND ce.valuenum IS NOT NULL
    AND ce.charttime >= c.admittime
    AND ce.charttime < DATETIME_ADD(c.admittime, INTERVAL 48 HOUR)
),
readings AS (
  SELECT * FROM vs_long UNION ALL SELECT * FROM wt_long
),
per_adm AS (
  SELECT hadm_id, vital,
         COUNT(*) AS n_0_48,
         COUNTIF(hrs < 24) AS n_0_24,
         COUNTIF(hrs >= 24) AS n_24_48
  FROM readings
  GROUP BY hadm_id, vital
),
vitals AS (
  SELECT vital FROM UNNEST(['heart_rate','sbp','map','spo2','resp_rate','temperature','weight']) vital
),
grid AS (
  -- every cohort admission x every vital, so zero-reading admissions count as missing
  SELECT c.hadm_id, c.alive_in_hosp_48h, v.vital,
         IFNULL(p.n_0_48, 0) AS n_0_48,
         IFNULL(p.n_0_24, 0) AS n_0_24,
         IFNULL(p.n_24_48, 0) AS n_24_48
  FROM cohort c CROSS JOIN vitals v
  LEFT JOIN per_adm p ON p.hadm_id = c.hadm_id AND p.vital = v.vital
),
grid_pop AS (
  SELECT 'all_17129' AS population, * FROM grid
  UNION ALL
  SELECT 'alive_in_hosp_48h' AS population, * FROM grid WHERE alive_in_hosp_48h
)
SELECT
  'vital_coverage' AS row_type,
  population,
  vital,
  COUNT(*) AS n_admissions,
  COUNTIF(n_0_48 >= 1) AS n_any_0_48h,
  ROUND(100 * COUNTIF(n_0_48 = 0) / COUNT(*), 1) AS pct_missing_0_48h,
  COUNTIF(n_0_24 >= 1 AND n_24_48 >= 1) AS n_both_halves,
  ROUND(100 * COUNTIF(n_0_24 >= 1 AND n_24_48 >= 1) / COUNT(*), 1) AS pct_both_halves,
  COUNTIF(n_0_48 >= 3 AND n_0_24 >= 1 AND n_24_48 >= 1) AS n_slope_eligible,
  -- reading-count quantiles among admissions with >=1 reading: [min, q1, median, q3, max]
  APPROX_QUANTILES(IF(n_0_48 >= 1, n_0_48, NULL), 4) AS n_readings_0_48h_quartiles,
  APPROX_QUANTILES(IF(n_0_24 >= 1, n_0_24, NULL), 4) AS n_readings_0_24h_quartiles,
  APPROX_QUANTILES(IF(n_24_48 >= 1, n_24_48, NULL), 4) AS n_readings_24_48h_quartiles,
  CAST(NULL AS INT64) AS n_patients,
  CAST(NULL AS INT64) AS n_events
FROM grid_pop
GROUP BY population, vital

UNION ALL

SELECT 'cohort_check', 'all_17129', NULL,
  COUNT(*), NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
  COUNT(DISTINCT subject_id), SUM(hospital_expire_flag)
FROM cohort
UNION ALL
SELECT 'cohort_check', 'alive_in_hosp_48h', NULL,
  COUNT(*), NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
  COUNT(DISTINCT subject_id), SUM(hospital_expire_flag)
FROM cohort WHERE alive_in_hosp_48h
UNION ALL
SELECT 'cohort_check', 'died_lt_48h', NULL,
  COUNT(*), NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
  COUNT(DISTINCT subject_id), SUM(hospital_expire_flag)
FROM cohort WHERE died_lt_48h
UNION ALL
SELECT 'cohort_check', 'discharged_alive_lt_48h', NULL,
  COUNT(*), NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
  COUNT(DISTINCT subject_id), SUM(hospital_expire_flag)
FROM cohort WHERE NOT alive_in_hosp_48h AND NOT died_lt_48h
ORDER BY row_type DESC, population, vital
