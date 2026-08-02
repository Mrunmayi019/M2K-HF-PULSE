# PerHeart real-world data validation summary

**Status: PARTIAL RUN, interrupted deliberately.** Only 4 of the 16 eligible real patients were
replayed before this run was stopped (after `user_5`'s checkpoint, before `user_6` started) to
allow a planned machine shutdown. The remaining 12 patients (`user_6, 15, 16, 17, 18, 19, 21, 22,
23, 24, 25, 27`) were never attempted — not failures, simply not yet run. A follow-up run (planned:
parallelized, unlike this sequential run — see §7 of `docs/real_world_data_integration.md`) will
cover the rest in a separate timestamped directory; this directory's numbers should not be read as
final until that happens.

Source: PerHeart Pilot Dataset (Kolakowski et al., Data 2026, 11(5):106, Zenodo 10.5281/zenodo.17143199) -- real heart-failure patients, real pulse-oximeter/scale readings, real ages 67-94. See docs/real_world_data_integration.md for the full field-by-field real-vs-imputed breakdown and the Pulse age/BMI-capping caveat below.

Patients replayed: 4
Completed: 3/4 (75%)
Required Pulse age capping (true age outside 18-65): 4/4
Required Pulse BMI capping (true BMI outside ~16.5-29.5): 0/4

## Failures

 user_id simulation_status                                                                                                           error_message
       1            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/ccced5a2-e917-4c9c-982b-f52404b11e95/scenario.json

## Risk bucket distribution (real patients)

risk_bucket
MODERATE    3

## Scenario type distribution (ML Model 1 classification of real patients)

scenario_type
cardiac_stress    3

## Severity / risk score summary

       severity  risk_score
count  3.000000    3.000000
mean   0.136364    0.456500
std    0.010332    0.037739
min    0.127153    0.432500
25%    0.130778    0.434750
50%    0.134403    0.437000
75%    0.140970    0.468500
max    0.147537    0.500000

## Timing

Total wall clock: 2234s
Mean per patient: 558.5s
