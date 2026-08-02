# M2K HF-PULSE

[![CI](https://github.com/Mrunmayi019/M2K-HF-PULSE/actions/workflows/ci.yml/badge.svg)](https://github.com/Mrunmayi019/M2K-HF-PULSE/actions/workflows/ci.yml)

**Personalized Digital Twin for Early Heart Failure Deterioration Detection**

A system that combines wearable/clinical patient data, the [Kitware Pulse](https://pulse.kitware.com/)
physiology simulation engine, and machine learning to detect early signs of heart failure
decompensation before a patient reaches crisis — days before symptoms would otherwise prompt a
hospital visit.

## Quick Start

The whole stack (Postgres + FastAPI/Pulse backend + React frontend) in one command:

```bash
git clone https://github.com/Mrunmayi019/M2K-HF-PULSE.git
cd M2K-HF-PULSE
docker compose up --build
```

Then open **http://localhost:3000**. The API itself is at `http://localhost:8000/docs` (interactive
OpenAPI UI).

> **Note for Apple Silicon (M1/M2/M3) users:** the backend image bundles the Pulse physiology
> engine from `kitware/pulse:4.3.1`, which only ships an `amd64` build — Docker Desktop runs it
> under emulation on arm64 Macs. Everything works, but Pulse simulation calls are noticeably
> slower than on a native amd64 machine (see `docs/methodology.md` §8) — the first patient's
> assessment (which needs 4 real Pulse calls) can take several minutes rather than seconds. This
> is expected, not a hang.

See `docs/running_the_stack.md` for the full step-by-step walkthrough (verifying each service,
smoke-testing the real Pulse pipeline, and troubleshooting).

First run will take a while (building both images + `pip install`/`npm ci`); subsequent
`docker compose up` runs are fast thanks to layer caching. `docker compose down` stops everything;
add `-v` to also drop the Postgres volume.

## Status

This repo currently contains two things side by side:

1. **A working prototype** (`app.py`, `streamlit_app.py`, `src/rules.py`, `src/generator.py`,
   `src/run.py`, `src/legacy_analytics.py`) — a Streamlit/Flask dashboard that takes live patient
   vitals, runs one Pulse simulation, and prints a clinical risk summary. This is the original demo
   and its logic is left untouched as the target architecture is built out alongside it (the
   analytics module was renamed from `src/analytics.py` in Phase 5 purely to free up the
   `src/analytics/` package name — no behavior change).
2. **The target architecture**, built out in phases (see `docs/methodology.md` for full detail on
   each):
   - **Phase 0/1 (done):** repo scaffold + a correlated synthetic patient generator and wearable
     trend simulator, grounded in real reference data (see Data Sources below), not guessed values.
   - **Phase 2 (done):** real integration with the Pulse engine (`src/patient_builder/`,
     `src/pulse_runner/`) — patient/scenario construction and simulation execution with crash
     detection, validated against all 5 locked scenario types running inside the actual Pulse
     Docker container.
   - **Phase 3 (done):** ML scenario classifier (`src/scenario_classifier/`) — a RandomForest
     classifier predicts the 5-way `scenario_type` from clinical + wearable-trend features (92%
     test accuracy), paired with a RandomForestRegressor for `severity` (MAE 0.048). See
     `docs/methodology.md` §5 for the train/val/test protocol and feature design.
   - **Phase 4 (done):** batch Pulse simulation dataset (`src/pulse_runner/batch_runner.py`,
     `src/simulation_features.py`) — a stratified sample of 150 synthetic patients run through
     Pulse in parallel (117 succeeded, 33 failed — almost entirely high-severity
     `cardiac_stress`/`acute_deterioration` runs destabilizing the engine, a known Phase 2 limit),
     with per-run features (HR rise, MAP drop, CO drop%, compensation/instability flags) extracted
     into `data/simulation_runs/features_dataset.csv` for Phase 5's risk scorer. See
     `docs/methodology.md` §5 for full composition and results.
   - **Phase 5 (done):** risk scoring & clinical logic (`src/analytics/`, `src/ml_models/`) — a
     primary hand-tuned, clinically-cited weighted risk score (`risk_score.py`); a
     secondary/experimental XGBoost regressor (`train_risk_scorer.py`, explicitly not primary —
     see `models/model_card.md` for why); rule-based NYHA staging (`staging.py`); a wearable-trend
     deterioration rate calculator (`deterioration_rate.py`); and forward projection via
     incremental Pulse re-simulation (`projection.py`). See `docs/methodology.md` §6 for the full
     scoring formula, citations, and a known limitation found during validation.
   - **Phase 6 (done):** FastAPI backend (`src/api/`) — 5 SQLAlchemy tables (patients,
     clinical_reports, wearable_readings, simulation_runs, risk_assessments), Pydantic
     request/response schemas with physiological-range validation, and 8 endpoints (the 8th,
     `GET /patients/{id}/wearable-history`, added in the Phase 7 frontend extension below).
     Wearable data
     is submitted daily and accumulates to a 21-day window before `BackgroundTasks` triggers one
     assessment pipeline (ML Model 1 → Pulse → risk scoring → staging → projection) — every read
     endpoint (`/status`, `/history`, `/projection`, `/report`) is a fast DB read, never blocking
     on Pulse. `risk_caveats` surfaces the §6.1 `fluid_overload` finding directly in API responses.
     See `docs/methodology.md` §6.4 for the full orchestration design.
   - **Phase 7 (done):** frontend dashboard (`frontend/`) — a React (Vite) single-page dashboard
     built against a decoded design reference (`frontend/design_reference.html`), wired to the
     Phase 6 API. Comparing the design against the actual API surfaced several fields the pipeline
     computes but never returned (scenario_type, severity, EF, BNP, per-vital trend slopes, latest
     wearable reading) — added as small, additive extensions to `src/api/models.py|schemas.py|
     services.py|routes.py` (plus a `GET /patients` list endpoint) rather than fabricated
     client-side. Design elements with no real backing data (an HF Stage A-D badge, per-horizon
     HR/MAP/CO, an absolute "Simulation Output" vitals column, a fabricated stage-progression
     probability) were either dropped or redesigned around the fields that are actually computed —
     see the Phase 7 plan for the full list of these decisions. Handles `collecting` /
     `running`/`pending` / `failed` / `complete` simulation states and backend-unreachable errors
     as distinct UI states, not just a single loading spinner.
   - **Phase 7 extension (done):** the sidebar's other 4 sections — Trends & History, Simulation
     Lab, Reports, Settings — were static labels with no click handler; all 4 are now wired to real
     data and actions, plus a working dark/light/system theme toggle across the whole app. Trends &
     History adds per-vital trend charts (needed the new `GET /wearable-history` endpoint above) and
     a risk-score-over-time chart, both hand-built SVG components with hover tooltips, no charting
     library added. Simulation Lab is a patient-creation wizard that drives the real API end to end
     (demographics → clinical report → a client-side-generated 21-day wearable trend, 4 presets) —
     the first way to create a patient from the UI itself — plus a live view of the selected
     patient's raw risk-score component breakdown. Reports is a master-detail view across all
     patients reusing the existing report/copy/download component. See `docs/methodology.md` §11
     and `docs/frontend_extension_validation.md` for the full design rationale and the manual,
     real-browser verification evidence (including one real dark-mode rendering bug found and
     fixed).
   - **Real-world data validation (done):** every prior validation used synthetic or hand-typed
     input; this replays real physiological data from a published, ethics-approved dataset — the
     PerHeart Pilot Dataset (27 real heart-failure patients, ages 67-94, real pulse-oximeter/scale
     readings from one-month home trials, Kolakowski et al., *Data* 2026, Zenodo
     `10.5281/zenodo.17143199`) — through the real pipeline via `scripts/perheart_real_data_replay.py`.
     16 of 27 real patients have enough real daily coverage (HR, SpO2, weight) to fill a genuine
     21-day window; fields the dataset doesn't measure (height, sleep, HRV, steps, EF, NT-proBNP)
     are filled from this project's own existing, already-cited `assumed_default` constants
     (`reference_stats.yaml`) or the existing Tier 1 fallback — never new invented numbers. Every
     one of these real patients falls outside Pulse's native 18-65 age range, so results reflect
     the existing age/BMI proxy-clamp (`methodology.md` §4/§8), not these patients' literal bodies
     — flagged per-patient in the results, not buried. **Result: 16/16 real patients completed**
     (`data/real_world_validation/20260802_234002/combined_results.csv`) — 12 `cardiac_stress` / 4
     `stable`, 12 MODERATE / 4 LOW risk, zero HIGH. Two caveats worth reading before citing these
     numbers: severity is compressed into a narrow band across all 16, independently reproducing an
     already-documented live-inference bug (`methodology.md` §7/§8); and all 16 came back NYHA
     Class I, most likely a mechanical consequence of every patient sharing the same Tier 1 EF/BNP
     fallback (this dataset never measured either), not a real clinical finding. Getting a stable
     concurrent run also took 3 attempts (9 → 4 → 2 workers) after diagnosing a DB connection-pool
     exhaustion and separately a real Pulse-level contention ceiling — see
     `docs/real_world_data_integration.md` §8.3 for the full breakdown. That same doc has the full
     dataset citation, field-by-field real-vs-imputed mapping, and the license-statement discrepancy
     found in the source and how it's handled.

## Running Individual Components (Manual Setup)

For running one piece at a time outside `docker compose` (developing a single component, or
debugging in isolation) — see "Quick Start" above for the one-command full-stack path.

### Run the existing prototype dashboard

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
docker run -it -p 8501:8501 -p 5000:5000 -v "$(pwd)":/workspace kitware/pulse:4.3.1 /bin/bash

# inside the container:
pip3 install flask pandas streamlit plotly
streamlit run /workspace/streamlit_app.py     # primary UI, port 8501
# or:
python3 /workspace/app.py                     # simpler Flask fallback, port 5000
```

### Run the data synthesis / patient builder code (no Docker needed)

```bash
pip install -r requirements.txt
python3 -m src.data_synthesis.generate_patients        # writes data/synthetic/patients.csv (n=2000)
python3 -m src.data_synthesis.generate_wearable_trends  # writes data/synthetic/wearable_trends.csv
pytest tests/ -v                                        # 137 tests, no Docker required
```

### Train the Phase 3 scenario classifier (no Docker needed)

```bash
python3 -m src.scenario_classifier.train
# writes models/scenario_classifier.joblib, models/severity_regressor.joblib,
# models/confusion_matrix.png, models/feature_importances.png, models/phase3_eval_report.txt
```

### Compute risk scores + train the Phase 5 secondary XGBoost model (no Docker needed)

The primary risk score (`src/analytics/risk_score.py`) is a pure function — call
`compute_risk_score(hr_rise, map_drop, co_drop_pct, compensation_flag, instability_flag)` directly
on any row from `data/simulation_runs/features_dataset.csv`, no training required. The
secondary/experimental XGBoost comparison model does need training:

```bash
python3 -m src.ml_models.train_risk_scorer
# writes models/risk_scorer_xgb.joblib, models/phase5_xgb_cv_report.txt
# see models/model_card.md for why this is secondary, not primary
```

### Run a Pulse simulation with the new patient_builder/pulse_runner pipeline

Requires Docker (see `docs/methodology.md` §4 for the Pulse-specific gotchas this handles):

```bash
docker run --rm -v "$(pwd)":/workspace -w /workspace kitware/pulse:4.3.1 bash -c "
  pip3 install -q pandas pyyaml
  python3 -m scripts.validate_phase2
"
```

### Verify the Phase 5 forward projection (Docker required, calls Pulse repeatedly)

```bash
docker run --rm -v "$(pwd)":/workspace -w /workspace kitware/pulse:4.3.1 bash -c "
  pip3 install -q pandas pyyaml
  python3 -c \"
import pandas as pd
from src.analytics.projection import project_physiology
patients = pd.read_csv('data/synthetic/patients.csv')
patient = patients.iloc[0].to_dict()
print(project_physiology(patient, patient['scenario_type'], float(patient['severity']), deterioration_rate_per_day=0.03))
\"
"
```

### Run the Phase 6 API server (Docker required for real assessments, calls Pulse)

The server itself is pure Python (no Docker needed just to start it), but the background
assessment pipeline calls `run_pulse()`, so run it inside the container for real end-to-end use:

```bash
docker run --rm -p 8000:8000 -v "$(pwd)":/workspace -w /workspace kitware/pulse:4.3.1 bash -c "
  pip3 install -q -r requirements.txt
  uvicorn src.api.main:app --host 0.0.0.0
"
```

Then visit `http://localhost:8000/docs` for the interactive OpenAPI UI (this is also where the
`risk_caveats` field's full documented rationale is visible). Typical flow: `POST /patients` →
`POST /patients/{id}/clinical-report` → `POST /patients/{id}/wearable-sync` once daily for 21 days
(the assessment pipeline triggers automatically once the window fills) → `GET /patients/{id}/status`
`/history` `/projection` `/report`. Database defaults to a local SQLite file at
`data/db/m2k_hf_pulse.db` (gitignored runtime state); override with the `DATABASE_URL` env var.

### Run the Phase 4 batch simulation dataset

Requires Docker. Takes roughly 90 minutes for the default 150-patient batch (4 parallel workers,
~110s/run under this project's Docker emulation — see `docs/methodology.md` §5/§8); results are
checkpointed incrementally to `data/simulation_runs/checkpoint.csv` so an interruption doesn't lose
progress already made.

```bash
docker run --rm -v "$(pwd)":/workspace -w /workspace kitware/pulse:4.3.1 bash -c "
  pip3 install -q pandas pyyaml
  python3 -m src.pulse_runner.batch_runner
"
# writes data/simulation_runs/features_dataset.csv (successful runs) and
# data/simulation_runs/failed_runs.csv (if any runs crashed/timed out)
```

### Run the Phase 7 frontend dashboard

Backend must be running first (see the Phase 6 API instructions above).

```bash
cd frontend
npm install
cp .env.example .env   # VITE_API_URL defaults to http://localhost:8000
npm run dev
```

Visit the printed local URL. The sidebar lists patients from `GET /patients`; select one to see
its dashboard (hero risk status, current condition, vitals, forward projection, and a
copy/download-able clinical summary report), all sourced from `GET /patients/{id}/report`.

### Run the real-world data validation (Docker required, calls Pulse per patient)

Backend must already be running (`docker compose up`, see Quick Start). Replays a real, published,
ethics-approved heart-failure patient dataset (PerHeart, 27 patients, real pulse-oximeter/scale
readings) through the live API. Downloads its own small (~32KB) input data on first run. See
`docs/real_world_data_integration.md` for the full field-mapping, license, and results writeup.

```bash
PYTHONUNBUFFERED=1 PYTHONPATH=. python -m scripts.perheart_real_data_replay             # all eligible real patients
PYTHONUNBUFFERED=1 PYTHONPATH=. python -m scripts.perheart_real_data_replay --limit 2    # quick smoke test first
PYTHONUNBUFFERED=1 PYTHONPATH=. python -m scripts.perheart_real_data_replay \
  --resume-from data/real_world_validation/<prior-run>/combined_results.csv              # resume + retry, merges into a fresh combined_results.csv
# writes data/real_world_validation/<timestamp>/results.csv, summary.md, mapped_readings/,
# and (with --resume-from) combined_results.csv / combined_summary.md
```

Concurrency is auto-detected but capped at 2 (`MAX_SAFE_WORKERS`) — empirically the only safe
level found for this architecture (single-process backend, default DB connection pool); see
`docs/real_world_data_integration.md` §8.3 before raising it. `PYTHONUNBUFFERED=1` matters for a
multi-patient run — without it, per-patient progress doesn't flush to a redirected/background
output until the process exits.

Real Pulse runs observed 3–12 minutes per patient in this environment; ~16 eligible patients is a
multi-hour run — checkpointed per patient, so an interruption doesn't lose progress already made.

## Repository Structure

```
app.py, streamlit_app.py          # prototype frontends (untouched)
src/
  rules.py, generator.py,
  run.py, legacy_analytics.py     # prototype pipeline (untouched, analytics.py renamed in Phase 5
                                   #   to free up the src/analytics/ package name below)
  data_synthesis/                 # Phase 1: synthetic patients + wearable trends
  patient_builder/                # Phase 2: Pulse patient/scenario JSON construction
  pulse_runner/                   # Phase 2: Pulse execution + crash detection
                                   #   + Phase 4: batch_runner.py (parallelized batch execution)
  scenario_classifier/            # Phase 3: feature engineering + scenario/severity models
  analytics/                      # Phase 4: simulation_features.py (per-run feature extraction)
                                   #   + Phase 5: risk_score.py (primary), staging.py,
                                   #   deterioration_rate.py, projection.py
  ml_models/                      # Phase 5: train_risk_scorer.py (secondary/experimental XGBoost)
  api/                            # Phase 6: database.py, models.py (5 tables), schemas.py,
                                   #   services.py (Tier 1 fallback + background pipeline),
                                   #   routes.py (7 endpoints), main.py (FastAPI app)
data/
  synthetic/                      # generated patients.csv / wearable_trends.csv
  simulation_runs/                # Phase 4: features_dataset.csv / failed_runs.csv / checkpoint.csv
  db/                             # Phase 6: SQLite file (gitignored runtime state)
  raw/, reference/                # real source data (gitignored, never committed)
models/                           # trained model artifacts + eval plots (gitignored, never committed)
                                   #   model_card.md documents both Model 1 and Model 2, incl.
                                   #   the Phase 5 secondary model's limitations
frontend/                         # Phase 7: React (Vite) dashboard; extended (Trends/Lab/Reports/
                                   #   Settings tabs + dark mode) in the Phase 7 extension
  design_reference.html           #   decoded design export (colors/layout/interaction reference)
  src/
    components/                   #   layout/, hero/, condition/, vitals/, projection/, report/,
                                   #     shared/ (skeleton, error/collecting/failed states),
                                   #     + trends/, lab/, reports/, settings/ (Phase 7 extension)
    hooks/                        #   usePatients, usePatientReport (polls while running/pending),
                                   #     + useTrends, useTheme (Phase 7 extension)
    utils/syntheticTrend.js       #   client-side 21-day wearable trend generator, Simulation Lab
                                   #     only -- not a substitute for src/data_synthesis/
    api/client.js                 #   fetch wrapper, base URL from VITE_API_URL
    mock/mockData.js              #   VITE_USE_MOCK=true renders off this instead of a live API
docs/
  architecture.md                 # current + target system diagrams
  methodology.md                  # why each decision was made, what was validated
  data_provenance.md              # every clinical number, traced to its source
  frontend_extension_validation.md  # Phase 7 extension: what was built + full verification evidence
  real_world_data_integration.md  # real (non-synthetic) patient data validated through the pipeline
scripts/
  validate_phase2.py              # runs all 5 scenario types through Pulse
  validate_phase8.py              # Phase 8: batch-validates 20-30 synthetic patients through
                                   #   the live API pipeline end to end (see docs/methodology.md §7)
  perheart_real_data_replay.py    # replays a real, published HF-patient dataset (PerHeart, Zenodo)
                                   #   through the live API (see docs/real_world_data_integration.md)
tests/                            # 137 tests, no Docker required
backend/Dockerfile                # Phase 9: FastAPI + Pulse engine image (linux/amd64, see file
                                   #   for why); build context is the repo root, not backend/
frontend/Dockerfile               # Phase 9: Vite build -> nginx serve, multi-stage
docker-compose.yml                # Phase 9: db (Postgres) + pulse-backend + frontend, one command
.github/workflows/ci.yml          # Phase 9: pytest + frontend build on every push/PR
```

## Data Sources

Clinical reference values are grounded in real data, not assumptions — see
`docs/data_provenance.md` for the full citation table:

- **MIMIC-IV** (11,837 real heart failure admissions, via BigQuery)
- **Kaggle — Chicco & Jurman (2020)** heart failure clinical records (ejection fraction, serum
  creatinine/sodium)
- **CDC NHANES** (height/weight/BMI by sex)

All real/raw source data lives under `data/raw/` and is gitignored — only the derived synthetic
datasets and aggregate statistics are committed.

## Documentation

- **`CLAUDE.md`** — architecture conventions, locked Phase 0 decisions, known gotchas
- **`docs/architecture.md`** — system diagrams (current prototype + target pipeline)
- **`docs/methodology.md`** — the "why" behind each phase, validation results, honest limitations
- **`docs/data_provenance.md`** — every clinical threshold/statistic, traced to a source
- **`docs/running_the_stack.md`** — step-by-step guide to `docker compose up --build`, verifying
  each service, the Pulse-in-container smoke test, and troubleshooting (Node/Vite version, missing
  shared libraries, missing trained models on a fresh build)
- **`docs/frontend_extension_validation.md`** — the Trends/Simulation Lab/Reports/Settings tabs and
  dark mode: what was built, why, and the full manual verification evidence
- **`models/model_card.md`** — both trained models' training data, performance, and limitations

## Contributors

Kaveri Sharma, Mrunmayi Mohite, Meghan Singhal
