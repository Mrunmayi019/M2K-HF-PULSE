# M2K HF-PULSE

**Personalized Digital Twin for Early Heart Failure Deterioration Detection**

A system that combines wearable/clinical patient data, the [Kitware Pulse](https://pulse.kitware.com/)
physiology simulation engine, and machine learning to detect early signs of heart failure
decompensation before a patient reaches crisis — days before symptoms would otherwise prompt a
hospital visit.

## Status

This repo currently contains two things side by side:

1. **A working prototype** (`app.py`, `streamlit_app.py`, `src/rules.py`, `src/generator.py`,
   `src/run.py`, `src/analytics.py`) — a Streamlit/Flask dashboard that takes live patient vitals,
   runs one Pulse simulation, and prints a clinical risk summary. This is the original demo and is
   left untouched as the target architecture is built out alongside it.
2. **The target architecture**, built out in phases (see `docs/methodology.md` for full detail on
   each):
   - **Phase 0/1 (done):** repo scaffold + a correlated synthetic patient generator and wearable
     trend simulator, grounded in real reference data (see Data Sources below), not guessed values.
   - **Phase 2 (done):** real integration with the Pulse engine (`src/patient_builder/`,
     `src/pulse_runner/`) — patient/scenario construction and simulation execution with crash
     detection, validated against all 5 locked scenario types running inside the actual Pulse
     Docker container.
   - **Phase 3 onward (not started):** ML scenario classifier, risk scoring model, FastAPI
     backend, frontend dashboard. See `docs/architecture.md` for the full target pipeline diagram.

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
python3 -m src.data_synthesis.generate_patients        # writes data/synthetic/patients.csv
python3 -m src.data_synthesis.generate_wearable_trends  # writes data/synthetic/wearable_trends.csv
pytest tests/ -v                                        # 44 tests, no Docker required
```

### Run a Pulse simulation with the new patient_builder/pulse_runner pipeline

Requires Docker (see `docs/methodology.md` §4 for the Pulse-specific gotchas this handles):

```bash
docker run --rm -v "$(pwd)":/workspace -w /workspace kitware/pulse:4.3.1 bash -c "
  pip3 install -q pandas pyyaml
  python3 -m scripts.validate_phase2
"
```

## Repository Structure

```
app.py, streamlit_app.py          # prototype frontends (untouched)
src/
  rules.py, generator.py,
  run.py, analytics.py            # prototype pipeline (untouched)
  data_synthesis/                 # Phase 1: synthetic patients + wearable trends
  patient_builder/                # Phase 2: Pulse patient/scenario JSON construction
  pulse_runner/                   # Phase 2: Pulse execution + crash detection
data/
  synthetic/                      # generated patients.csv / wearable_trends.csv
  raw/, reference/                # real source data (gitignored, never committed)
docs/
  architecture.md                 # current + target system diagrams
  methodology.md                  # why each decision was made, what was validated
  data_provenance.md              # every clinical number, traced to its source
scripts/
  validate_phase2.py              # runs all 5 scenario types through Pulse
tests/                            # 44 tests, no Docker required
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

## Contributors

Mrunmayi Mohite · Kaveri Sharma · Meghan Singhal
