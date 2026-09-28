# Zigong cohort: MAGGIC-11 (MAGGIC-adapted, missing smoker status + HF duration) -- EXPLORATORY, standalone

NOT the validated 13-variable MAGGIC score. 11 of 13 predictors used, all real per-patient
Zigong values (age via ageCat bin-midpoint; beta-blocker/ACEI-ARB derived from dat_md.csv).
current_smoker and hf_duration_18mo_plus are structurally absent from this dataset and are
EXCLUDED (zero-contribution), not defaulted/assumed.

Cleaning: n raw=2008 -> n cleaned=2001 (same 5 rules as Sec 7.Y).
MAGGIC-11 complete-case cohort (11 fields, no imputation): n=622
Composite outcome (death OR readmission, 6mo) event rate: 41.8%

## Discrimination (AUC / PR-AUC)

- AUC = 0.604 (95% CI 0.559-0.649, percentile bootstrap, 2000
  resamples, seed=42)
- PR-AUC = 0.496 (95% CI 0.443-0.558); event-rate baseline = 0.418

## Calibration (decile bins)

```
 n  mean_score  observed_event_rate
73     13.8356               0.2877
60     19.0833               0.2833
86     22.0814               0.3372
35     24.0000               0.3714
75     25.4800               0.4667
70     27.5571               0.4286
68     29.4853               0.5147
33     31.0000               0.4545
65     32.7692               0.5538
57     37.3509               0.5088
```