# PerHeart real-world data validation summary

Source: PerHeart Pilot Dataset (Kolakowski et al., Data 2026, 11(5):106, Zenodo 10.5281/zenodo.17143199) -- real heart-failure patients, real pulse-oximeter/scale readings, real ages 67-94. See docs/real_world_data_integration.md for the full field-by-field real-vs-imputed breakdown and the Pulse age/BMI-capping caveat below.

Patients replayed: 16
Completed: 13/16 (81%)
Required Pulse age capping (true age outside 18-65): 16/16
Required Pulse BMI capping (true BMI outside ~16.5-29.5): 3/16

## Failures

 user_id simulation_status                                                                                                         error_message  attempt
      18            failed PulseScenarioDriver exited 1 on /workspace/scenarios/api/e3c94eb9-e6a0-4e13-a9c2-1e23bf1c4588/scenario.json\nstderr:         2
       6            failed PulseScenarioDriver exited 1 on /workspace/scenarios/api/c1e021bf-163b-436a-9311-65685afefb87/scenario.json\nstderr:         2
      22            failed PulseScenarioDriver exited 1 on /workspace/scenarios/api/9607fc3a-fc26-4e9e-821f-cebabd1d8e4b/scenario.json\nstderr:         2

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
mean    0.231094    0.438808
std     0.130493    0.344109
min     0.093247    0.000000
25%     0.125483    0.005900
50%     0.209777    0.447100
75%     0.314150    0.800000
max     0.516080    0.800000

## Timing

Total wall clock (sum across patients, overlapping under concurrency): 6306s
Mean per patient: 394.1s
