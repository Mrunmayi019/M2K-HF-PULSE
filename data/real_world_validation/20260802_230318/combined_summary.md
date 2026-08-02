# PerHeart real-world data validation summary

Source: PerHeart Pilot Dataset (Kolakowski et al., Data 2026, 11(5):106, Zenodo 10.5281/zenodo.17143199) -- real heart-failure patients, real pulse-oximeter/scale readings, real ages 67-94. See docs/real_world_data_integration.md for the full field-by-field real-vs-imputed breakdown and the Pulse age/BMI-capping caveat below.

Patients replayed: 16
Completed: 5/16 (31%)
Required Pulse age capping (true age outside 18-65): 16/16
Required Pulse BMI capping (true BMI outside ~16.5-29.5): 3/16

## Failures

 user_id simulation_status                                                                                                           error_message  attempt
      15     harness_error                                                                                                           ReadTimeout:       2.0
      16     harness_error                                                                                                           ReadTimeout:       2.0
      17     harness_error                                                                                                           ReadTimeout:       2.0
      18            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/79e85935-a89b-4893-893f-103104c99411/scenario.json      2.0
      19            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/48a59612-9f54-4a87-8191-79193d1d5859/scenario.json      2.0
      21            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/4a2e7522-db96-4446-842e-65d138abb156/scenario.json      2.0
      22            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/c0a2c182-7dee-4ff3-902b-184dba9e5018/scenario.json      2.0
      23            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/21631709-91cb-4e3e-af55-c1ae91aeb1ee/scenario.json      2.0
      24            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/11de3992-bc1b-45d9-a967-82689a21eb31/scenario.json      2.0
      25     harness_error                                                                                                           ReadTimeout:       2.0
      27     harness_error                                                                                                           ReadTimeout:       2.0

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

Total wall clock (sum across patients, overlapping under concurrency): 4381s
Mean per patient: 273.8s
