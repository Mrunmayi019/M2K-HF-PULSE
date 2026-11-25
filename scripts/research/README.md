# Research and validation scripts

The scripts behind the paper's validation results and the one-off checks reported in `docs/`. They
were moved to the `archive/full-research-snapshot` branch on 9 Oct 2026 (#12) and are back on `main`
so that every reported number can be traced to the code that produced it. They are kept as they
ran; the only changes are paths, updated for this folder.

Most need data that is not in the repository (MIMIC-IV, Zigong and PerHeart are under their own
data-use agreements) or the Pulse engine (run inside the backend image, see each docstring). Run
them from the repository root, for example `python -m scripts.research.zigong_outcome_validation`.

| Script | Output | What it does |
|---|---|---|
| **Real outcomes** | | |
| `mimic_outcome_extraction.sql` | `data/raw/` (not committed) | MIMIC-IV HF admissions and outcomes (BigQuery) |
| `mimic_outcome_validation.py` | `data/mimic_outcome_validation/` | Baseline-deficit term vs in-hospital death, MIMIC-IV |
| `zigong_outcome_validation.py` | `data/zigong_outcome_validation/` | Same term vs 6-month death or readmission, Zigong |
| `zigong_model1_clinical_only_validation.py` | `data/zigong_model1_clinical_only_validation/` | Model 1's clinical features alone, Zigong |
| `train_clinical_only_variant.py` | model file | Trains the clinical-only Model 1 variant |
| `zigong_clinical_only_model_validation.py` | `data/zigong_clinical_only_model_validation/` | That variant on Zigong |
| `zigong_maggic11_validation.py` | `data/zigong_maggic11_validation/` | MAGGIC-11 external benchmark, Zigong |
| `zigong_native_risk_model.py` | `data/zigong_native_risk_model/` | Lab-panel model trained and tested on Zigong (external benchmark) |
| `benchmark_comparison.py` | `docs/benchmark_comparison.md` | MAGGIC on the synthetic batch |
| **Real home data and measured hemodynamics** | | |
| `perheart_real_data_replay.py` | `data/real_world_validation/` | PerHeart patients replayed through the live API |
| `bcg_real_patient_validation.py`, `bcg_real_patient_run.py` | `data/bcg_validation/subject14/` | BCG subject 14: build and run |
| `bcg_subject102_validation.py`, `bcg_subject102_run.py` | `data/bcg_validation/subject102/` | BCG subject 102: build and run |
| `bcg_extract_subject14_features.py`, `bcg_extract_subject102_features.py` | `data/bcg_validation/` | BCG waveform features |
| `bcg_step1_diagnostic.py` | `data/bcg_validation/step1_diagnostic/` | SV/CO arithmetic check |
| `bcg_hr_baseline_experiment.py`, `bcg_hr_baseline_run.py` | `data/bcg_validation/` | Measured HR as Pulse's baseline (research flag, negative result) |
| **Model and pipeline checks** | | |
| `model1_extended_eval.py` | `models/phase3_extended_eval_report.txt` | Extended offline evaluation of the scenario model |
| `nyha_fix_live_revalidation.py`, `reattempt_single_patient.py` | `data/validation_runs/` | Live re-validation after removing the NYHA feature |
| `validate_phase2.py` | console | One Pulse run per scenario (engine scenario check) |
| `validate_phase8.py` | `data/validation_runs/` | Full-pipeline batch through the live API |
| `synthetic_deterioration_stress_test.py`, `synthetic_deterioration_pulse_check.py` | `data/synthetic_deterioration_stress_test/` | Synthetic deterioration anchored to the BCG patients |
| `verify_continuous_mode_live.py` | `results/live_checks/continuous_mode_live/` | Continuous mode with real Pulse |
| `verify_continuous_state_live_14day.py` | console | 14-day flat-patient continuous run |

Paper figures are made by `scripts/paper_figures/`; engine diagnostics are in `scripts/diagnostics/`.
The old Streamlit/Flask prototype stays on `archive/full-research-snapshot`.
