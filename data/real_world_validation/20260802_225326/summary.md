# PerHeart real-world data validation summary

Source: PerHeart Pilot Dataset (Kolakowski et al., Data 2026, 11(5):106, Zenodo 10.5281/zenodo.17143199) -- real heart-failure patients, real pulse-oximeter/scale readings, real ages 67-94. See docs/real_world_data_integration.md for the full field-by-field real-vs-imputed breakdown and the Pulse age/BMI-capping caveat below.

Patients replayed: 2
Completed: 2/2 (100%)
Required Pulse age capping (true age outside 18-65): 2/2
Required Pulse BMI capping (true BMI outside ~16.5-29.5): 0/2

## Risk bucket distribution (real patients)

risk_bucket
LOW         1
MODERATE    1

## Scenario type distribution (ML Model 1 classification of real patients)

scenario_type
stable            1
cardiac_stress    1

## Severity / risk score summary

       severity  risk_score
count  2.000000     2.00000
mean   0.096900     0.22380
std    0.026328     0.30844
min    0.078283     0.00570
25%    0.087592     0.11475
50%    0.096900     0.22380
75%    0.106208     0.33285
max    0.115517     0.44190

## Timing

Total wall clock (sum across patients, overlapping under concurrency): 1048s
Mean per patient: 524.0s
