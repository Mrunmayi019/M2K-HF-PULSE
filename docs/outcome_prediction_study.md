# Outcome prediction study — trend signals (MIMIC-IV) and hospital-data risk models (Zigong, MIMIC-IV)

**Status: pre-registered 2026-09-28. No Part A or Part B results have been computed yet.**
Everything in §1 was fixed before any outcome-linked number from this study was looked at. If a
choice changes later, the change is logged in §5 with the reason, and the original stays in place.

**Scope.** These are standalone scripts and docs only. Nothing here feeds into, replaces, or is called by
`src/analytics/risk_score.py`, Model 1 (the scenario classifier), the Pulse simulation layer, or
any other production code. This is the same treatment as §7.BB/§7.CC in `docs/methodology.md`.

**What Part A is and is not.** MIMIC-IV trends are **ICU-charted vitals** recorded by nurses and
monitors on acutely ill hospitalised patients. They are **not home or consumer-wearable data**.
Part A tests whether *trend signals in vitals* add prognostic information beyond a single snapshot
in that setting. It does **not** test whether wearables predict outcomes, and it does not validate
Model 1's 21-day ambulatory window. §7.X already established that no such window exists in
MIMIC-IV.

---

## 1. Pre-registered analysis choices

### 1.0 Choices shared by all parts

| Item | Fixed choice |
|---|---|
| Discrimination metrics | ROC-AUC and PR-AUC (average precision), each with a 95% CI |
| CI method | Percentile bootstrap, 2,000 resamples, seed 42. **MIMIC: cluster bootstrap that resamples patients (`subject_id`) with all their admissions.** This fixes the independence issue §7.X flagged but left uncorrected. Zigong: resample rows (see 1.3). |
| Always reported | Exact n, number of events, event rate, PR-AUC's no-skill baseline (= event rate), and one plain-English line on what the result does **not** show |
| Model family | `RandomForestClassifier`, the same family as §7.BB, used in every part so that "same model type" holds literally |
| Hyperparameter grid | §7.BB's grid, unchanged: `n_estimators=[300]`, `max_depth=[4, 8, None]`, `min_samples_leaf=[1, 5, 20]`, `random_state=42`, tuning metric = ROC-AUC |
| Imputation | Median imputation **fit on the training fold only** and applied to the held-out data. For MIMIC, also a binary missing-indicator per vital/lab. |
| Pooling | **None.** MIMIC (in-hospital death) and Zigong (6-month death-or-readmission) are reported separately. No transfer or generalisation claim is made between them. |
| Test-set discipline | Wherever there is a held-out test set, it is scored exactly once, after all tuning. |

### 1.1 Part A — can ICU vital-sign trends predict in-hospital death beyond a snapshot? (MIMIC-IV)

**Step 1 — recon only (`scripts/outcome_study_partA_recon.sql`).** Returns aggregate counts only.
- **Cohort:** the §7.X cohort, re-derived with the identical SQL definition. It must reproduce
  17,129 admissions and 13,047 patients; if it doesn't, the study stops and the drift gets
  investigated.
- **Sources:**
  - `physionet-data.mimiciv_3_1_derived.vitalsign` for HR, SBP, MAP, SpO2, respiratory rate, and
    temperature. These are ICU-charted. `sbp`/`mbp` combine arterial-line and cuff readings.
  - `physionet-data.mimiciv_3_1_icu.chartevents` itemids 224639/226512/226531 for weight.
- **Time anchor:** hospital `admittime`, the same anchor as §7.X. The window is [0, 48h), split
  into halves [0, 24h) and [24h, 48h).
- **Reported per vital, for two populations** (all 17,129 admissions, and the 48h-alive-in-hospital
  subset):
  - admissions with ≥1 reading in 0–48h;
  - % missing (zero readings);
  - admissions with ≥1 reading in *both* halves;
  - admissions eligible for a slope (≥3 readings spanning both halves);
  - reading-count quartiles (median, IQR).
- **Stop point:** step 1 results go to the user before anything is built.

**Go/no-go rule for step 2, fixed now.** A vital is used in step 2 only if ≥80% of the
48h-alive population has ≥1 reading in **both** halves (otherwise first-24h vs. last-24h trend
features would mostly be imputed). Step 2 proceeds only if at least HR, SpO2, respiratory rate,
and one of SBP/MAP pass. Weight is expected to fail (ICU weight is charted roughly daily, not
continuously). If it passes, it is used; if not, it is reported as excluded, not imputed into the
model. The user makes the final go/no-go after seeing step 1.

**Step 2 — modelling population and leakage guard.**
- **Included:** §7.X admissions still in hospital and alive at `admittime + 48h`, defined as
  `dischtime ≥ +48h AND (deathtime IS NULL OR deathtime ≥ +48h)`. Anyone who died or was
  discharged before 48h is excluded, so the outcome can never occur inside the feature window.
  Excluded counts are reported by reason (died <48h / discharged alive <48h).
- **Outcome:** `hospital_expire_flag`.
- **Features:** vitals only, with no labs, demographics, diagnoses, or `discharge_location`.

**Step 2 — features per vital** (all computed from readings in [0, 48h) only):

| Feature | Definition | Source of definition |
|---|---|---|
| `{v}_first` | First reading in the window (the "single snapshot") | new; this is the user's baseline |
| `{v}_first24_mean` | Mean over [0, 24h) | `src/scenario_classifier/features.py::_wearable_features` `first7_mean`, window rescaled from days 0–6 to hours 0–24 |
| `{v}_last24_mean` | Mean over [24h, 48h) | same, `last7_mean` → last 24h |
| `{v}_delta` | `last24_mean − first24_mean` | same, `delta` |
| `{v}_slope` | OLS slope vs. hours since admission (`np.polyfit(t, x, 1)[0]`), units per hour; missing if <3 readings or not spanning both halves | same, `slope` (days → hours) |
| `{v}_sd` | SD of all readings in [0, 48h); missing if <2 readings | **new**, because `features.py` has no variability feature. This is the only definition not reused. |

Readings are used as charted, with no outlier removal (the MIT-LCP `vitalsign` concept already
applies physiological range filters). Missing features are median-imputed with missing
indicators, per 1.0.

**Step 3 — split and tuning.**
- **Split by patient:** `StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)` on
  `hospital_expire_flag` with `groups=subject_id`. Fold 0 is the test set (~20%), the rest is
  train. No patient appears in both.
- **Tuning:** 5-fold `StratifiedGroupKFold` (grouped by `subject_id`) on the train set only, using
  the §7.BB grid. Model (a) and model (b) are each tuned separately in the same way.
- **Test set:** scored once, after both models are frozen.

**Step 4 — comparison on the same test set.**
- **(a) Snapshot model:** `{v}_first` for every vital that passed the gate (plus missing
  indicators).
- **(b) Snapshot + trend model:** (a) plus `first24_mean`, `last24_mean`, `delta`, `slope`, `sd`
  for the same vitals.
- **Primary estimand:** ΔAUC = AUC(b) − AUC(a) on the test set, with a 95% CI from a **paired
  cluster bootstrap** (resampling test-set patients, with both models scored on each resample),
  2,000 resamples, seed 42. ΔPR-AUC is reported the same way.
- **Pre-stated reading:** "trends add discrimination" only if the ΔAUC 95% CI excludes 0. Otherwise
  the conclusion is "no evidence of added discrimination at this sample size", not "trends don't
  matter".
- **Caveat stated in advance:** in (b), `first24_mean` and `last24_mean` also carry *level*
  information over a longer window than one reading. So a gain in (b) could come partly from
  averaging (less noise) rather than trend shape alone. To separate these, a **secondary,
  descriptive** model (b′) = (a) + `first24_mean` + `last24_mean` (levels only, no
  delta/slope/sd) is also tuned and scored. It is reported but not used for the primary claim.

### 1.2 Part B.1 — Zigong hospital-data risk model, properly evaluated

- **Data, cohort, outcome, features:** reuse `scripts/zigong_native_risk_model.py` (§7.BB)
  unchanged. That means the same 5 cleaning rules (n=2001), the same 6-month death-or-readmission
  composite, the same <15% missingness rule, and the same kept fields (LVEF and `leukemia`
  dropped).
- **Patient grouping:** `dat.csv` has 2,008 rows and 2,008 unique `inpatient.number`, with no
  other patient identifier. Rows are therefore treated as independent patients. If one person had
  multiple rows, this would slightly overstate precision; this cannot be checked from the data
  and is listed as a limitation.
- **5-fold CV (new):** nested cross-validation on all n=2001.
  - Outer loop: `StratifiedKFold(5, shuffle=True, random_state=42)`.
  - Inner loop: 5-fold tuning on each outer-train fold with the §7.BB grid.
  - Imputation is fit inside each outer-train fold.
  - Reported: per-fold AUC and PR-AUC, mean ± SD, and min–max across folds.
- **Pooled out-of-fold (OOF) predictions** (each patient scored by the model that did not see
  them) are used for the calibration plot and the MAGGIC comparison. §7.BB's original single 80/20
  held-out result (AUC 0.667) is left as it is and is not rerun or overwritten.
- **Calibration:**
  - Plot: OOF predicted probability split into 10 equal-count deciles. For each decile, mean
    predicted risk vs. observed event rate (with 95% Wilson CI), plus the identity line.
  - Reported: calibration-in-the-large (mean predicted vs. observed) and calibration slope
    (logistic regression of outcome on logit(p)).
  - RandomForest probabilities are **not recalibrated**; they are shown as produced.
  - Saved to `data/outcome_prediction_study/zigong_calibration.png`.
- **MAGGIC-11 comparison:**
  - Population: the §7.CC complete-case cohort (n=622, all 11 MAGGIC fields + drug record).
  - Scores: MAGGIC-11 points from the unmodified §7.CC pipeline vs. the RF's OOF predicted
    probabilities for those same 622 patients.
  - Estimand: ΔAUC = AUC(RF) − AUC(MAGGIC-11), with a 95% CI from a paired bootstrap (resampling
    the 622 patients, scoring both models on each resample), 2,000 resamples, seed 42.
  - ΔPR-AUC is reported the same way.
  - "RF beats MAGGIC-11" is claimed only if the CI excludes 0.
  - Stated in advance: the RF was trained on all 2001 (including these 622 in other folds), while
    MAGGIC-11 is a fixed external score. The RF uses LVEF-free lab panels; MAGGIC-11 uses LVEF.
    The two differ in *inputs*, not just *method*.

### 1.3 Part B.2 — MIMIC-IV admission-level risk model, in-hospital mortality

- **Cohort:** the §7.X cohort, restricted to admissions still in hospital and alive at `admittime
  + 24h`. This is the same leakage logic as Part A, applied to a 24h feature window.
- **Features** (first 24h from `admittime` only, using §7.BB's <15% missingness rule, checked
  field by field and reported):
  - age and sex;
  - admission type;
  - first-24h mean HR, SBP, MAP, SpO2, RR, and temperature;
  - first-24h first-drawn value of standard admission labs from `mimiciv_3_1_hosp.labevents`:
    creatinine, BUN, sodium, potassium, bicarbonate, glucose, haemoglobin, WBC, platelets, INR,
    and NT-proBNP.
  NT-proBNP is included only if it passes the missingness rule, matching §7.BB's inclusion of BNP.
  §7.X's exclusion applied to a single-mechanism test, which this is not.
- **Excluded by rule:** same-admission ICD codes and Charlson comorbidities (coded at discharge,
  so post-hoc information), `discharge_location`, length of stay, and anything timestamped after
  24h.
- **Evaluation:** same as Part B.1, but with patient-grouped folds:
  - nested `StratifiedGroupKFold(5)` grouped by `subject_id`, with mean ± SD and range;
  - OOF decile calibration plot;
  - cluster-bootstrap CIs.
  There is no MAGGIC comparison, because MIMIC has no EF and no NYHA class (see §7.X).
- **Reported separately from Zigong.** No pooled number, and no claim that one cohort's model
  transfers to the other.

---

## 2. Part A step 1 — recon results

*Pending. `scripts/outcome_study_partA_recon.sql` is written but not yet run (see §4).*

## 3. Results

*Pending. Not computed.*

## 4. Data-access status (as of 2026-09-28)

- **Zigong:** `dat.csv` / `dat_md.csv` are available locally at
  `../Dataset/hospitalized-patients-with-heart-failure-...-1.3/` (DUA-signed, outside the repo).
- **MIMIC-IV:** not reachable from this machine right now.
  - The §7.X extract `data/raw/mimic/hf_admission_outcomes.csv` is not on disk.
  - The local Google Cloud SDK install is incomplete (no `gcloud.cmd` or `bq`) and has no
    credentials.
  - Part A and Part B.2 need a working `bq` with access to `physionet-data` (billing project
    `ai-inventory-project`).

## 5. Deviations log

*None yet.*
