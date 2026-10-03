# Zigong cohort: Model 1 clinical-feature-component-only exploratory test

**This does NOT test Model 1 as designed.** Model 1 (severity regressor) was trained on 5 clinical features PLUS 24 wearable-trend features from a real 21-day ambulatory window. Zigong has no wearable time series -- this test neutralizes those 24 features to this project's own 'stable'-scenario reference values (zero drift, from reference_stats.yaml's wearable_baseline, via the real, unmodified _wearable_features()/build_inference_features() code) and substitutes approximated clinical inputs. The result characterizes the clinical-feature component only, under approximated inputs -- not Model 1's validated designed behavior.

## Caveats (all load-bearing, not footnotes)

1. **age** is the `ageCat` bin midpoint (e.g. `(59,69]` -> 64), not real continuous age -- a coarse approximation, worst for the open-ended `(89,110]` bucket (midpoint 99.5).
2. **nt_probnp_pg_ml is Zigong's raw BNP value, substituted with NO unit conversion.** This project has no validated BNP-to-NT-proBNP conversion, and none was invented for this test. BNP and NT-proBNP are different assays with different reference ranges and different clinical meaning -- this is an invalid like-for-like substitution. There is only one reported variant (raw, unconverted); no second 'corrected' variant was computed since no defensible conversion factor exists.
3. **All 24 wearable-trend feature slots are neutralized**, not real -- set to this project's own 'stable'-scenario reference values (zero drift), not zero and not invented ad hoc.
4. No retraining occurred; `models/severity_regressor.joblib` was loaded unmodified.

## Cohort / outcome

- n = 625 (same complete-case cohort as Sec 7.Y)
- Composite outcome (death OR readmission, 6mo) event rate: 41.3%

## Discrimination (AUC / PR-AUC)

- AUC = 0.478 (95% CI 0.433-0.523, percentile bootstrap, 2000 resamples, seed=42) for the clinical-only severity-regressor output predicting the 6-month composite outcome.
- PR-AUC = 0.396 (95% CI 0.351-0.452); event-rate baseline = 0.413.