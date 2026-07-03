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
  src/patient_builder/                  — Phase 2, not yet created
         │  (patient.json, scenario.json — personalized via EF/BNP, not raw wearable numbers)
         ▼
  src/pulse_runner/                     — Phase 2, not yet created
         │  (Pulse simulation output CSV, with crash/timeout handling)
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

## Known naming collisions to resolve when those phases start

The target architecture reuses names already taken by prototype files at the top level of `src/`:

| Target (future) | Existing (prototype, keep as-is for now) |
|---|---|
| `src/pulse_runner/runner.py` | `src/run.py` |
| `src/patient_builder/patient_file.py` + `scenario_file.py` | `src/generator.py` |
| `src/analytics/` (package: `staging.py`, `deterioration_rate.py`, `projection.py`, `simulation_features.py`) | `src/analytics.py` (single file) |

Decision on how to resolve each (rename prototype file vs. fold logic into the new package) is
deferred to whichever phase actually builds that piece — flagging here now so it isn't a surprise.
Per CLAUDE.md, any of these three target directories require a plan check before code is written.

## Tech stack

- Simulation: Kitware Pulse Physiology Engine (`kitware/pulse:4.3.1` Docker image)
- Data synthesis / analytics: Python, pandas, numpy
- ML: scikit-learn (Random Forest, Phase 3), XGBoost (secondary, Phase 5)
- Backend (target): FastAPI + Postgres/SQLite — not yet started
- Frontend (current prototype): Streamlit / Flask; (target): TBD, see roadmap Phase 7
