# PerHeart real-world data validation summary

Source: PerHeart Pilot Dataset (Kolakowski et al., Data 2026, 11(5):106, Zenodo 10.5281/zenodo.17143199) -- real heart-failure patients, real pulse-oximeter/scale readings, real ages 67-94. See docs/real_world_data_integration.md for the full field-by-field real-vs-imputed breakdown and the Pulse age/BMI-capping caveat below.

Patients replayed: 1
Completed: 1/1 (100%)
Required Pulse age capping (true age outside 18-65): 1/1
Required Pulse BMI capping (true BMI outside ~16.5-29.5): 0/1

## Risk bucket distribution (real patients)

risk_bucket
LOW    1

## Scenario type distribution (ML Model 1 classification of real patients)

scenario_type
stable    1

## Severity / risk score summary

       severity  risk_score
count  1.000000      1.0000
mean   0.078283      0.0057
std         NaN         NaN
min    0.078283      0.0057
25%    0.078283      0.0057
50%    0.078283      0.0057
75%    0.078283      0.0057
max    0.078283      0.0057

## Timing

Total wall clock: 694s
Mean per patient: 694.4s
