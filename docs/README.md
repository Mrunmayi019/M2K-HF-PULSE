# Documentation index

Start with the top-level `README.md`. The documents below give the detail behind it.

## System

| Document | What it covers |
|---|---|
| `methodology.md` | Why each design decision was made and how each part was validated (the main technical reference) |
| `architecture.md` | Component diagrams |
| `data_provenance.md` | Every clinical threshold and distribution parameter, traced to its source |
| `running_the_stack.md` | Running the full stack with Docker, checking each service, troubleshooting |
| `demo_walkthrough.md` | What each of the five seeded demo patients shows on the dashboard |
| `research_flags_evaluation.md` | The research feature flags: wiring, behaviour and evaluation |
| `results-v1-models.sha256` | Checksums of the frozen models used for every reported result |

## Evaluation

The scenario-test experiments live in `results/scenario_tests/` (Experiment 1 at the top level,
`exp2/`, `exp3/`), each with its pre-registration, amendments and results.

| Document | What it covers |
|---|---|
| `unified_alert_evaluation.md` | The deployed alert decision (`decide_alert()`): ALERT/WATCH rates, development vs held-out seeds |
| `results_v1_offline_analyses.md` | Offline analyses of the results-v1 runs, including the age-only MIMIC-IV baseline |
| `real_world_data_integration.md` | Replay of real home data (PerHeart) through the pipeline |
| `bcg_validation_note.md` | Simulated vs measured hemodynamics for two BCG patients |
| `synthetic_deterioration_stress_test.md` | Synthetic deterioration trajectories built on two real patients' baselines |
| `benchmark_comparison.md` | Agreement between the risk score and MAGGIC on simulated patients |
| `claims_methodology.md` | Each headline claim, re-checked against code and reruns |

## Investigations and design checks

| Document | What it covers |
|---|---|
| `pulse_state_serialization_investigation.md` | Whether Pulse state can be saved and resumed exactly |
| `continuous_state_sync_status.md` | Building the continuous mode (session log) |
| `integration_pre_results.md` | The frozen system version used for the scenario tests |
| `c3_fluid_overload_blindspot_check.md` | Checking that the C3 alert guard does not hide fluid overload |
| `decide_alert_preflight_analysis.md` | Analysis done before implementing `decide_alert()` |
| `followup_analysis_2026-10-05.md`, `-06.md`, `-07.md` | Follow-up analyses cited by Experiment 1's protocol amendments |
| `medication_modeling_feasibility.md` | Whether medication effects (e.g. furosemide) can be modeled in Pulse |
| `frontend_extension_validation.md` | What the dashboard extension does and how it was checked |
| `ethics_statement.md` | Ethics and data-availability statement (draft) |

## Project log

`project-log/` holds internal working notes kept for the record: session handoff notes, a project
walkthrough, an early related-work scan and a reproducibility checklist. They are not needed to use
or reproduce the system.
