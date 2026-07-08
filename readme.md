# M2K HF-PULSE

**Personalized Digital Twin for Early Heart Failure Deterioration Detection**

A system that combines wearable/clinical patient data, the [Kitware Pulse](https://pulse.kitware.com/)
physiology simulation engine, and machine learning to detect early signs of heart failure
decompensation before a patient reaches crisis — days before symptoms would otherwise prompt a
hospital visit.

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
     request/response schemas with physiological-range validation, and 7 endpoints. Wearable data
     is submitted daily and accumulates to a 21-day window before `BackgroundTasks` triggers one
     assessment pipeline (ML Model 1 → Pulse → risk scoring → staging → projection) — every read
     endpoint (`/status`, `/history`, `/projection`, `/report`) is a fast DB read, never blocking
     on Pulse. `risk_caveats` surfaces the §6.1 `fluid_overload` finding directly in API responses.
     See `docs/methodology.md` §6.4 for the full orchestration design.
   - **Phase 7 onward (not started):** frontend dashboard. See `docs/architecture.md` for the full
     target pipeline diagram.

## Quick Start

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
pytest tests/ -v                                        # 135 tests, no Docker required
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
docs/
  architecture.md                 # current + target system diagrams
  methodology.md                  # why each decision was made, what was validated
  data_provenance.md              # every clinical number, traced to its source
scripts/
  validate_phase2.py              # runs all 5 scenario types through Pulse
tests/                            # 135 tests, no Docker required
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
- **`models/model_card.md`** — both trained models' training data, performance, and limitations

## Contributors

Mrunmayi Mohite · Kaveri Sharma · Meghan Singhal
