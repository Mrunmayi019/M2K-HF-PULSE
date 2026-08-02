# PerHeart real-world data validation summary

Source: PerHeart Pilot Dataset (Kolakowski et al., Data 2026, 11(5):106, Zenodo 10.5281/zenodo.17143199) -- real heart-failure patients, real pulse-oximeter/scale readings, real ages 67-94. See docs/real_world_data_integration.md for the full field-by-field real-vs-imputed breakdown and the Pulse age/BMI-capping caveat below.

Patients replayed: 16
Completed: 8/16 (50%)
Required Pulse age capping (true age outside 18-65): 16/16
Required Pulse BMI capping (true BMI outside ~16.5-29.5): 3/16

## Failures

 user_id simulation_status                                                                                                           error_message  attempt
      15            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/8fcfbd7e-74bc-4320-b940-7c7a3864968f/scenario.json      2.0
      16            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/3df293a1-6008-4459-8beb-69071dae45d3/scenario.json      2.0
      17            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/f38e2e5e-2db0-4a12-be79-2e2f1edce526/scenario.json      2.0
      18            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/3583405e-1e33-4382-ad3e-f443f39e26dd/scenario.json      2.0
      19            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/86a2124c-185e-4039-925c-87cc2953dde5/scenario.json      2.0
      21            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/e499e72e-10f1-4d23-878c-cf64dc7af442/scenario.json      2.0
      22            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/62e7704b-cda9-47a0-a806-2cb9ac1bd76f/scenario.json      2.0
      24            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/4503e464-33c6-476d-802e-b264fc24fd30/scenario.json      2.0

## Risk bucket distribution (real patients)

risk_bucket
MODERATE    5
LOW         3

## Scenario type distribution (ML Model 1 classification of real patients)

scenario_type
cardiac_stress    5
stable            3

## Severity / risk score summary

       severity  risk_score
count  8.000000    8.000000
mean   0.113044    0.274813
std    0.023511    0.225693
min    0.078283    0.004900
25%    0.093571    0.005850
50%    0.115465    0.401550
75%    0.128966    0.438225
max    0.147537    0.500000

## Timing

Total wall clock (sum across patients, overlapping under concurrency): 6467s
Mean per patient: 404.2s
