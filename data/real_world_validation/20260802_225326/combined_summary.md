# PerHeart real-world data validation summary

Source: PerHeart Pilot Dataset (Kolakowski et al., Data 2026, 11(5):106, Zenodo 10.5281/zenodo.17143199) -- real heart-failure patients, real pulse-oximeter/scale readings, real ages 67-94. See docs/real_world_data_integration.md for the full field-by-field real-vs-imputed breakdown and the Pulse age/BMI-capping caveat below.

Patients replayed: 5
Completed: 5/5 (100%)
Required Pulse age capping (true age outside 18-65): 5/5
Required Pulse BMI capping (true BMI outside ~16.5-29.5): 0/5

## Risk bucket distribution (real patients)

risk_bucket
MODERATE    4
LOW         1

## Scenario type distribution (ML Model 1 classification of real patients)

scenario_type
cardiac_stress    4
stable            1

## Severity / risk score summary

       severity  risk_score
count  5.000000    5.000000
mean   0.120579    0.363420
std    0.026342    0.201843
min    0.078283    0.005700
25%    0.115517    0.432500
50%    0.127153    0.437000
75%    0.134403    0.441900
max    0.147537    0.500000

## Timing

Total wall clock (sum across patients, overlapping under concurrency): 3090s
Mean per patient: 617.9s
