# PerHeart real-world data validation summary

Source: PerHeart Pilot Dataset (Kolakowski et al., Data 2026, 11(5):106, Zenodo 10.5281/zenodo.17143199) -- real heart-failure patients, real pulse-oximeter/scale readings, real ages 67-94. See docs/real_world_data_integration.md for the full field-by-field real-vs-imputed breakdown and the Pulse age/BMI-capping caveat below.

Patients replayed: 16
Completed: 13/16 (81%)
Required Pulse age capping (true age outside 18-65): 16/16
Required Pulse BMI capping (true BMI outside ~16.5-29.5): 3/16

## Failures

 user_id simulation_status                                                                                                         error_message  attempt
      22            failed PulseScenarioDriver exited 1 on /workspace/scenarios/api/af170fd1-c20e-496b-be77-4b22b15cccfd/scenario.json\nstderr:         2
      18            failed PulseScenarioDriver exited 1 on /workspace/scenarios/api/8a20da30-adfb-4480-95ce-80aaceb3584e/scenario.json\nstderr:         2
       6            failed PulseScenarioDriver exited 1 on /workspace/scenarios/api/46f64a3d-bdcc-4a06-8fdf-b10bd4e726a0/scenario.json\nstderr:         2

## Risk bucket distribution (real patients)

risk_bucket
HIGH        5
LOW         4
MODERATE    4

## Scenario type distribution (ML Model 1 classification of real patients)

scenario_type
cardiac_stress    9
stable            3
fluid_overload    1

## Severity / risk score summary

        severity  risk_score
count  13.000000   13.000000
mean    0.231127    0.438723
std     0.130539    0.344106
min     0.093787    0.000000
25%     0.125827    0.005900
50%     0.209717    0.446000
75%     0.313913    0.800000
max     0.517653    0.800000

## Timing

Total wall clock (sum across patients, overlapping under concurrency): 2514s
Mean per patient: 157.1s
