# Phase 8 batch validation summary

Mode: real Pulse (Docker)
Patients: 25
Completed: 25/25 (100%)

## Failures by scenario type

None.

## Scenario classification agreement (ML Model 1, live in the pipeline)

Agreement rate: 100.0% (25/25)
Severity MAE: 0.271 (offline test-set MAE was 0.048 per methodology.md §5 -- expect this to be somewhat higher since these severities also pass through a full Pulse re-simulation and risk-scoring step, not just the classifier in isolation)

## Risk bucket distribution by true scenario type

risk_bucket          HIGH  LOW  MODERATE
true_scenario_type                      
acute_deterioration     2    2         1
cardiac_stress          1    0         4
deconditioning          0    5         0
fluid_overload          0    5         0
stable                  0    5         0

Expected pattern (methodology.md §6.1): `stable`/`deconditioning` should be ~100% LOW; `fluid_overload` should be ~100% LOW regardless of severity (documented blind spot, not a bug); `cardiac_stress`/`acute_deterioration` should skew MODERATE/HIGH.

## Timing

Total wall clock across all patients: 8854s
Mean per patient: 354.1s
