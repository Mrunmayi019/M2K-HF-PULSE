# Zigong cohort: NEW clinical-only Model 1 variant -- genuine, unconfounded test

Unlike Sec 7.Z (froze wearable inputs on the already-trained full model, got a collapsed/near-constant output), this model was trained from scratch on CLINICAL_FEATURE_COLUMNS only -- there is nothing to freeze. See scripts/train_clinical_only_variant.py for training details and the synthetic held-out evaluation.

## Caveats (restated, not silently reused)

1. age = ageCat bin midpoint, not real continuous age.
2. nt_probnp_pg_ml = raw BNP, no unit conversion (none validated in this project) -- invalid like-for-like substitution, only variant reported.

## Output distribution (confirms not collapsed)

mean=0.3514, std=0.2619, range=[0.0395, 0.8368]

## Cohort / outcome

- n = 625 (same complete-case cohort as Sec 7.Y/7.Z)
- Composite outcome (death OR readmission, 6mo) event rate: 41.3%

## Discrimination (AUC / PR-AUC)

- AUC = 0.517 (95% CI 0.473-0.562, percentile bootstrap, 2000 resamples, seed=42)
- PR-AUC = 0.419 (95% CI 0.372-0.478); event-rate baseline = 0.413