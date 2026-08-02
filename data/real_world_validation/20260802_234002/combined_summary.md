# PerHeart real-world data validation summary

Source: PerHeart Pilot Dataset (Kolakowski et al., Data 2026, 11(5):106, Zenodo 10.5281/zenodo.17143199) -- real heart-failure patients, real pulse-oximeter/scale readings, real ages 67-94. See docs/real_world_data_integration.md for the full field-by-field real-vs-imputed breakdown and the Pulse age/BMI-capping caveat below.

Patients replayed: 16
Completed: 16/16 (100%)
Required Pulse age capping (true age outside 18-65): 16/16
Required Pulse BMI capping (true BMI outside ~16.5-29.5): 3/16

## Risk bucket distribution (real patients)

risk_bucket
MODERATE    12
LOW          4

## Scenario type distribution (ML Model 1 classification of real patients)

scenario_type
cardiac_stress    12
stable             4

## Severity / risk score summary

        severity  risk_score
count  16.000000   16.000000
mean    0.112059    0.321425
std     0.017871    0.192822
min     0.078283    0.004900
25%     0.101592    0.270575
50%     0.111195    0.404250
75%     0.118426    0.445425
max     0.147537    0.500000

## Timing

Total wall clock (sum across patients, overlapping under concurrency): 9590s
Mean per patient: 599.4s
