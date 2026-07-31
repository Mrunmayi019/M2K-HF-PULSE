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
  src/legacy_analytics.py → analyze()       → {features, stage, risk, score, driver, forecast}
```

Two frontends (`streamlit_app.py`, `app.py`) share this pipeline. Runs only inside the Kitware
Pulse Docker container. See CLAUDE.md for full module responsibilities, hardcoded paths, and known
gotchas (Pulse crash detection not yet implemented in `run.py`; condition names here are a
prototyping shortcut, not the locked 5-scenario taxonomy). `src/analytics.py` was renamed to
`src/legacy_analytics.py` in Phase 5 to free up `src/analytics/` for the target-path package —
no logic changes, see "Known naming collisions" below.

## Target state (per project planning doc roadmap, Phase 0–9)

```
Wearable / clinical report input
         │
         ▼
  src/scenario_classifier/              — Phase 3, BUILT
         │  ML Model 1: RandomForestClassifier (scenario_type, 92% test acc.) +
         │  RandomForestRegressor (severity, MAE 0.048), on clinical + wearable-trend features
         │  (scenario_type, severity)
         ▼
  src/patient_builder/                  — Phase 2, BUILT
         │  (patient.json, scenario.json — personalized via EF/severity through Pulse Actions/
         │   Conditions, not raw wearable numbers; see methodology.md §4 for the real Pulse
         │   mechanisms discovered -- CardiovascularMechanicsModification, not a direct EF input)
         ▼
  src/pulse_runner/                     — Phase 2, BUILT (runner.py) + Phase 4, BUILT (batch_runner.py)
         │  (Pulse simulation output CSV, with crash/timeout/log-scan detection -- validated by
         │   actually catching a real IrreversibleState collapse during Phase 2 tuning;
         │   batch_runner.py parallelizes this across a stratified sample of synthetic patients)
         ▼
  src/analytics/simulation_features.py  — Phase 4, BUILT
         │  (per-run feature extraction: HR rise, MAP drop, CO drop%, compensation/instability
         │   flags -- feeds data/simulation_runs/features_dataset.csv, Phase 5's model input)
         ▼
  src/analytics/risk_score.py           — Phase 5, BUILT (primary risk scorer)
         │  (hand-tuned, clinically-cited weighted score -- LOW/MODERATE/HIGH; see
         │   methodology.md §6 for every component's citation and the fluid_overload blind spot
         │   found during validation)
         │
         │  src/ml_models/train_risk_scorer.py — Phase 5, BUILT (secondary/experimental)
         │  (XGBoost regressor on the same features, 5-fold CV given n=117 -- see
         │   models/model_card.md for why this is not the primary path)
         ▼
  src/analytics/staging.py              — Phase 5, BUILT (rule-based NYHA classification)
  src/analytics/deterioration_rate.py   — Phase 5, BUILT (slope-based rate, days-to-next-stage)
  src/analytics/projection.py           — Phase 5, BUILT (incremental severity re-simulation,
         │                                 7/14/30-day horizons, reuses patient_builder/pulse_runner)
         ▼
  src/api/ (FastAPI) + SQLite/Postgres    — Phase 6, BUILT; extended Phase 7
         │  (5 tables: patients, clinical_reports, wearable_readings, simulation_runs,
         │   risk_assessments -- orchestrates everything above via one BackgroundTasks pipeline
         │   per /wearable-sync call once a 21-day window fills; every GET endpoint is a fast DB
         │   read, zero Pulse calls in the request path; see methodology.md §6.4). Phase 7 added
         │   GET /patients, exposed scenario_type/severity/EF/BNP/vital_slopes/latest_wearable
         │   (already computed, previously discarded after use), and CORS middleware (needed the
         │   moment a browser -- not curl -- called the API from a different origin). The Phase 7
         │   frontend extension (below) added GET /patients/{id}/wearable-history (full synced
         │   wearable series, not just the latest reading -- feeds the Trends & History charts).
         ▼
  frontend/ (React + Vite)               — Phase 7, BUILT; extended Phase 7 (Trends/Lab/Reports/Settings)
         │  (src/components/: layout/, hero/, condition/, vitals/, projection/, report/, shared/
         │   state components, + trends/, lab/, reports/, settings/ from the extension below;
         │   src/hooks/: usePatients, usePatientReport (polls while running/pending), + useTrends,
         │   useTheme from the extension; built against a decoded design reference,
         │   frontend/design_reference.html -- see methodology.md §10 for the decode approach and
         │   every design-vs-real-API gap found and resolved)
         ▼
  frontend/ sidebar tabs beyond the dashboard  — Phase 7 extension, BUILT
         │  (Trends & History, Simulation Lab, Reports, Settings -- previously static labels with
         │   no click handler, now all wired to real data/actions; adds a working dark/light/
         │   system theme toggle across the whole app. See methodology.md §11 and
         │   docs/frontend_extension_validation.md for the full design rationale and verification
         │   evidence.)
```

## Known naming collisions

The target architecture reuses names already taken by prototype files at the top level of `src/`:

| Target | Existing (prototype, kept as-is) | Status |
|---|---|---|
| `src/pulse_runner/runner.py` | `src/run.py` | **Resolved (Phase 2):** both exist side by side. `run.py` still backs the working Streamlit/Flask prototype unchanged; `runner.py` is the target-path version with timeout + crash/log/completeness detection, used by `scripts/validate_phase2.py` and going forward. |
| `src/patient_builder/patient_file.py` + `scenario_file.py` | `src/generator.py` | **Resolved (Phase 2):** same pattern — `generator.py` untouched, new modules target the locked 5-scenario taxonomy instead of the prototype's ad hoc condition names. |
| `src/analytics/` (package: `staging.py`, `deterioration_rate.py`, `projection.py`, `simulation_features.py`, `risk_score.py`) | `src/analytics.py` (single file) | **Resolved (Phase 5):** the prototype file was renamed to `src/legacy_analytics.py` (no logic changes — `app.py`/`streamlit_app.py` each updated one import line: `from src.legacy_analytics import analyze`). `src/analytics/` is now the real target-path package; `simulation_features.py` moved in from its temporary Phase 4 location. |

## Tech stack

- Simulation: Kitware Pulse Physiology Engine (`kitware/pulse:4.3.1` Docker image)
- Data synthesis / analytics: Python, pandas, numpy
- ML: scikit-learn (Random Forest, Phase 3), XGBoost (secondary, Phase 5)
- Backend: FastAPI + SQLAlchemy, SQLite by default (`DATABASE_URL` env var portable to Postgres —
  "stretch/deploy claim" per the planning PDF; no Postgres server actually stood up here)
- Frontend (current prototype): Streamlit / Flask; (target, Phase 7, BUILT): React 19 + Vite,
  plain fetch/hooks (no React Query — kept dependencies minimal per the Phase 7 plan)
