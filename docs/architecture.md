# Architecture

## Current state (prototype, working)

```
Patient vitals (HR, SpO2, BP, RR, Age)
         │
         ▼
  src/rules.py        → detect_condition()  → (condition_name, severity 0–1)
         │
         ▼
  src/generator.py    → create_scenario()   → /workspace/scenarios/generated.json
         │
         ▼
  src/run.py           → run_pulse()         → /workspace/scenarios/generatedResults.csv
         │
         ▼
  src/analytics.py    → analyze()           → {features, stage, risk, score, driver, forecast}
```

Two frontends (`streamlit_app.py`, `app.py`) share this pipeline. Runs only inside the Kitware
Pulse Docker container. See CLAUDE.md for full module responsibilities, hardcoded paths, and known
gotchas (Pulse crash detection not yet implemented in `run.py`; condition names here are a
prototyping shortcut, not the locked 5-scenario taxonomy).

## Target state (per project planning doc roadmap, Phase 0–9)

```
Wearable / clinical report input
         │
         ▼
  ML Model 1 (scenario classifier)      — Phase 3
         │  (scenario_type, severity)
         ▼
  src/patient_builder/                  — Phase 2, BUILT
         │  (patient.json, scenario.json — personalized via EF/severity through Pulse Actions/
         │   Conditions, not raw wearable numbers; see methodology.md §4 for the real Pulse
         │   mechanisms discovered -- CardiovascularMechanicsModification, not a direct EF input)
         ▼
  src/pulse_runner/                     — Phase 2, BUILT
         │  (Pulse simulation output CSV, with crash/timeout/log-scan detection -- validated by
         │   actually catching a real IrreversibleState collapse during Phase 2 tuning)
         ▼
  src/analytics/ (package)              — Phase 5, not yet created
         │  (NYHA/stage classification, deterioration rate, forward projection)
         ▼
  ML Model 2 (risk scorer, hand-tuned primary + XGBoost secondary) — Phase 5
         │
         ▼
  src/api/ (FastAPI) + database          — Phase 6, not yet created
         │
         ▼
  frontend/ dashboard                    — Phase 7, not yet created
```

## Known naming collisions

The target architecture reuses names already taken by prototype files at the top level of `src/`:

| Target | Existing (prototype, kept as-is) | Status |
|---|---|---|
| `src/pulse_runner/runner.py` | `src/run.py` | **Resolved (Phase 2):** both exist side by side. `run.py` still backs the working Streamlit/Flask prototype unchanged; `runner.py` is the target-path version with timeout + crash/log/completeness detection, used by `scripts/validate_phase2.py` and going forward. |
| `src/patient_builder/patient_file.py` + `scenario_file.py` | `src/generator.py` | **Resolved (Phase 2):** same pattern — `generator.py` untouched, new modules target the locked 5-scenario taxonomy instead of the prototype's ad hoc condition names. |
| `src/analytics/` (package: `staging.py`, `deterioration_rate.py`, `projection.py`, `simulation_features.py`) | `src/analytics.py` (single file) | Still pending — Phase 5, needs a plan check per CLAUDE.md when it starts. |

## Tech stack

- Simulation: Kitware Pulse Physiology Engine (`kitware/pulse:4.3.1` Docker image)
- Data synthesis / analytics: Python, pandas, numpy
- ML: scikit-learn (Random Forest, Phase 3), XGBoost (secondary, Phase 5)
- Backend (target): FastAPI + Postgres/SQLite — not yet started
- Frontend (current prototype): Streamlit / Flask; (target): TBD, see roadmap Phase 7
