# PerHeart real-world data validation summary

Source: PerHeart Pilot Dataset (Kolakowski et al., Data 2026, 11(5):106, Zenodo 10.5281/zenodo.17143199) -- real heart-failure patients, real pulse-oximeter/scale readings, real ages 67-94. See docs/real_world_data_integration.md for the full field-by-field real-vs-imputed breakdown and the Pulse age/BMI-capping caveat below.

Patients replayed: 11
Completed: 0/11 (0%)
Required Pulse age capping (true age outside 18-65): 11/11
Required Pulse BMI capping (true BMI outside ~16.5-29.5): 3/11

## Failures

 user_id simulation_status                                                                                                           error_message  attempt
      17     harness_error                                                                                                           ReadTimeout:         2
      16     harness_error                                                                                                           ReadTimeout:         2
      15     harness_error                                                                                                           ReadTimeout:         2
      27     harness_error                                                                                                           ReadTimeout:         2
      25     harness_error                                                                                                           ReadTimeout:         2
      21            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/4a2e7522-db96-4446-842e-65d138abb156/scenario.json        2
      23            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/21631709-91cb-4e3e-af55-c1ae91aeb1ee/scenario.json        2
      24            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/11de3992-bc1b-45d9-a967-82689a21eb31/scenario.json        2
      19            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/48a59612-9f54-4a87-8191-79193d1d5859/scenario.json        2
      22            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/c0a2c182-7dee-4ff3-902b-184dba9e5018/scenario.json        2
      18            failed PulseScenarioDriver timed out after 180s on /workspace/scenarios/api/79e85935-a89b-4893-893f-103104c99411/scenario.json        2

## Timing

Total wall clock (sum across patients, overlapping under concurrency): 1291s
Mean per patient: 117.4s
