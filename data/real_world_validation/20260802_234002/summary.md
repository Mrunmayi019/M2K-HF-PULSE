# PerHeart real-world data validation summary

Source: PerHeart Pilot Dataset (Kolakowski et al., Data 2026, 11(5):106, Zenodo 10.5281/zenodo.17143199) -- real heart-failure patients, real pulse-oximeter/scale readings, real ages 67-94. See docs/real_world_data_integration.md for the full field-by-field real-vs-imputed breakdown and the Pulse age/BMI-capping caveat below.

Patients replayed: 8
Completed: 8/8 (100%)
Required Pulse age capping (true age outside 18-65): 8/8
Required Pulse BMI capping (true BMI outside ~16.5-29.5): 3/8

## Risk bucket distribution (real patients)

risk_bucket
MODERATE    7
LOW         1

## Scenario type distribution (ML Model 1 classification of real patients)

scenario_type
cardiac_stress    7
stable            1

## Severity / risk score summary

       severity  risk_score
count  8.000000    8.000000
mean   0.111073    0.368038
std    0.011375    0.154172
min    0.099570    0.005400
25%    0.103517    0.362925
50%    0.109775    0.410150
75%    0.112964    0.452475
max    0.136083    0.483200

## Timing

Total wall clock (sum across patients, overlapping under concurrency): 4605s
Mean per patient: 575.6s
