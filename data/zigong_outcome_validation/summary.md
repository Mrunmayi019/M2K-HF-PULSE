# Zigong heart-failure cohort real-outcome test: baseline_deficit_score mechanism only

**Scope**: second independent real-world test of the SAME single mechanism as `scripts/mimic_outcome_validation.py` -- `baseline_deficit_score = f(map_start)` -- this time against a broader composite outcome (death-or-readmission within 6 months). Does NOT validate the full risk scorer, the wearable-trend ML classifier, or the Pulse simulation layer. LVEF/NYHA/BNP are present in this dataset but are NOT fed into this test -- no existing function in this codebase maps them to risk_score or severity (see `docs/methodology.md` for the full explanation and the repo owner's explicit decision not to build one for this pass).

## Cleaning

- n raw = 2008
- Dropped (union of: pulse==0, respiration==0, systolic.blood.pressure==0, height<1.0m, BMI>60.0): 7
- n after cleaning = 2001

## Cohort

- Complete-case cohort (LVEF + NYHA + BNP + all 6 outcome flags present, from cleaned data): n = 625
- Composite outcome (death OR readmission within 6 months) event rate: 41.3% (258 / 625)

## Discrimination (AUC / PR-AUC)

- AUC = 0.533 (95% CI 0.490-0.575, percentile bootstrap, 2000 resamples, seed=42) for baseline_deficit_score predicting the 6-month composite outcome.
- PR-AUC = 0.463 (95% CI 0.412-0.520); event-rate baseline = 0.413.
- Bonus, full cleaned cohort (n=2001, not gated by LVEF/NYHA/BNP presence, since `map` itself is 0% missing): AUC = 0.548 (95% CI 0.525-0.573), PR-AUC = 0.457 (95% CI 0.426-0.490), event rate = 41.3%.

## Calibration (decile bins, complete-case cohort)

```
  n  mean_score  observed_event_rate
441      0.0165               0.3923
 66      0.2747               0.3788
 61      0.4709               0.4754
 57      0.7431               0.5439
```

## Honest limitations of this specific test

- **This validates baseline-risk-predicts-future-outcome only. It does NOT validate day-by-day trend/early-warning detection** (Model 1's actual production use case) -- that remains untested by any real data.
- **Population**: hospitalized HF admissions in Zigong, China -- an already-hospitalized, acutely-ill population at baseline capture, not this project's target outpatient/home-monitoring population (same caveat as the MIMIC-IV test).
- **Composite outcome mixes two different event types** (death, readmission) with very different rates and mechanisms; not decomposed in this pass.
- **LVEF/NYHA/BNP unused** despite being present -- see Scope above.
- **map here is a single admission-time vital**, not a stable ambulatory baseline (same map_start-meaning caveat as MIMIC-IV).
- **Complete-case cohort is a non-random subset** (patients who happened to get an echo and a BNP draw) -- may not represent the full 2008-admission population.