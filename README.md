# HF-PULSE

[![CI](https://github.com/Mrunmayi019/M2K-HF-PULSE/actions/workflows/ci.yml/badge.svg)](https://github.com/Mrunmayi019/M2K-HF-PULSE/actions/workflows/ci.yml)

Code, data and results for **"Design and Pre-Specified Evaluation of a Stateful, Wearable-Driven
Digital Twin for Heart Failure Home Monitoring"** (Sharma, Mohite, Singhal, Balasubramanyam;
PES University; manuscript in preparation).

HF-PULSE reads 21 days of home-monitoring data (resting HR, SpO₂, weight, steps, sleep, HRV) plus
routine clinical values (age, sex, BMI, ejection fraction, NT-proBNP). A Random Forest estimates a
deterioration scenario and its severity. These drive the [Kitware Pulse](https://pulse.kitware.com/)
physiology engine, and an interpretable risk score turns the simulated hemodynamics into a
three-level alert. In continuous mode the twin carries the engine state from day to day.

> **Research software, not a medical device.** The twin is parameterized from population
> statistics, not fitted to individual patients. It was evaluated on synthetic patient stories and
> on retrospective real data, and it has not been clinically validated.

## Pipeline

```
wearable readings (21 days) ─┐
                             ├─► scenario model ─► patient builder ─► Pulse 4.3.1 ─► hemodynamic features ─► risk score ─► alert
clinical report ─────────────┘   (RF: 5 classes     (EF → modifiers,    (Docker; crash,   (HR rise, MAP drop,    (6 inputs,     (ALERT /
                                  + severity 0–1)     scenario actions)   timeout checks)   CO drop, flags)        NYHA, trend)   WATCH / NONE)
```

- **Fresh mode (default):** every assessment rebuilds the patient and runs one 600 s encounter,
  plus three projection runs at 7, 14 and 30 days.
- **Continuous mode** (`PIPELINE_MODE=continuous`): each day resumes the saved Pulse state and
  re-issues the disease modifiers. A resumed run matches an uninterrupted one to 15 significant
  figures. Continuous mode also records a **baseline anchor**: how far the twin's simulated HR,
  MAP and cardiac output have moved from the start of the state chain. The risk score does not
  read the anchor.

The service is a FastAPI backend (11 endpoints, 7 tables) with a React dashboard.
`docs/architecture.md` describes the components and `docs/methodology.md` explains each design
decision.

## Results

All scenario tests use ten scripted 21-day patient stories (five that should alert, three that
should stay quiet, two edge cases). Every experiment's outcomes and predictions were written down
before its runs. In the table, "deployed" means the alert the system actually raises
(`decide_alert()`, with the C3 guard).

| Experiment | Setup | Main result | Files |
|---|---|---|---|
| 1: scenario test | Seeds 42–44 (development), 45–47 (held out) | Label accuracy 17.6%; deployed alert caught 21/30 deteriorating series at 8.7 false alerts per 100 patient-days. The C3 guard cut false alerts by 67.6% on development seeds and 61.4% on held-out seeds. | `results/scenario_tests/` (`expected_outcomes.md`, `protocol_amendments.md`, `RESULTS.md`, `alert_fix_results*.md`) |
| 2: EF in the training range | Same stories, EF 58–67%, seeds 48–53 | Label accuracy 37.1%; 24/30 caught; 4.8 false alerts per 100 patient-days. 6 of 8 predictions met. | `results/scenario_tests/exp2/` |
| 3: weekly baseline refresh | Exp 2 cohort, twin rebuilt every 7 days | The refresh clears the stuck post-exertion state (post-onset alert days 268 → 140; detection unchanged), but false alerts rise to 10.1 and failed engine days from 3 to 24. 16 of 18 pre-registered predictions held; the amendment's one also held. | `results/scenario_tests/exp3/` |

Other evaluations:

| Test | Result | Files |
|---|---|---|
| Scenario model, 300 held-out synthetic patients | 91.3% accuracy, severity MAE 0.047 | `models/model_card.md`, `models/phase3_eval_report.txt` |
| PerHeart real home data (16 eligible HF patients) | 13/16 ran end to end | `docs/real_world_data_integration.md` |
| MIMIC-IV in-hospital death (17,129 admissions) | Baseline-deficit term AUC 0.596 (age alone 0.591) | `data/mimic_outcome_validation/`, `results/results_v1_offline/` |
| Measured hemodynamics (BCG, 2 patients) | Simulated vs measured stroke volume and cardiac output | `docs/bcg_validation_note.md` |

The engine did not improve detection over the classifier alone: a classifier threshold chosen on
development seeds detected 15/15 held-out series, against 10/15 for the deployed alert, at the same
false-alert rate. The paper discusses what the physiology layer adds and what it does not.

## Quick start

Requires Docker. The Pulse image is `linux/amd64` only; on Apple Silicon it runs under emulation
and an assessment takes minutes, not seconds.

```bash
git clone https://github.com/Mrunmayi019/M2K-HF-PULSE.git
cd M2K-HF-PULSE
cp artifacts/results-v1/models/*.joblib models/          # frozen models used for every result
shasum -a 256 -c docs/results-v1-models.sha256            # all four lines must say OK
docker compose up --build
```

- Dashboard: http://localhost:3000
- API and interactive docs: http://localhost:8000/docs
- Five synthetic demo patients: `python scripts/seed_demo_patients.py` (see `docs/demo_walkthrough.md`)

`docs/running_the_stack.md` has the full walkthrough and troubleshooting.

## Reproducing the results

**Tests** (no Docker; Pulse is mocked):

```bash
pip install -r requirements.txt                          # Python 3.11
PYTHONPATH=. pytest tests/                               # 376 tests
cd frontend && npm ci && npm test                        # Node 20
```

**Score saved runs** (no Pulse runs; reads the committed CSVs):

```bash
PYTHONPATH=. python3 -m src.evaluation.scenario_tests.ablation_eval \
  --results-dir results/scenario_tests --cohort config/scenario_tests/cohort.yaml \
  --out /tmp/ablation_exp1.json                                       # Experiment 1 (deployed alert: 21/30, 8.7)
PYTHONPATH=. python3 -m src.evaluation.scenario_tests.exp2_analyze    # Experiment 2 (and 1, scored the same way)
PYTHONPATH=. python3 -m src.evaluation.scenario_tests.exp3_analyze    # Experiment 3 vs Experiment 2
```

**Rerun an experiment** (real Pulse runs; 60 jobs take several hours). Experiment 3:

```bash
docker compose build pulse-backend
docker compose run --rm --no-deps -v "$PWD:/workspace" \
  -e BASELINE_REFRESH_DAYS=7 -e SCENARIO_TEST_MAX_PARALLEL=2 \
  -e SCENARIO_TEST_COHORT=/workspace/config/scenario_tests/cohort_exp3.yaml \
  -e SCENARIO_TEST_OUTPUT_DIR=/workspace/results/scenario_tests/exp3 \
  pulse-backend python -m src.evaluation.scenario_tests.run_batch
```

The harness checks the model hashes and the flags required by the cohort file before it starts.
Each experiment's pre-registration records how it was run (Experiment 1: `expected_outcomes.md` and
`protocol_amendments.md`; Experiments 2 and 3: `PREREGISTRATION.md`, run from the commit that added
it). Code changed between experiments, so rerun from those commits to reproduce the saved outputs
exactly.

## Configuration

Research features are switched on with environment variables on the backend. All are off by
default, and with all of them off every API response matches a golden file
(`tests/test_flags_off_parity.py`).

| Variable | Default | Effect | Evidence |
|---|---|---|---|
| `PIPELINE_MODE` | `fresh` | `continuous` carries the Pulse state from day to day (adds `POST /patients/{id}/reset-state` and `GET /patients/{id}/twin-state`). | Used by all three scenario experiments. |
| `BASELINE_REFRESH_DAYS` | `0` (off) | Continuous mode: rebuilds the twin from the patient file every N saved states, ramping severity up from 0 in steps of 0.2, and records the drift. | Experiment 3: not recommended (more false alerts and engine failures). |
| `ENABLE_BCG_MODIFIERS` | off | Sets vascular compliance from ballistocardiography features. | Two subjects only; experimental. |
| `ENABLE_HR_BASELINE` | off | Sets Pulse's heart-rate baseline from a measured resting HR. | Negative result: HR fit better, stroke volume worse. |
| `ENABLE_ALERT_HYSTERESIS` | off | Enter/exit hysteresis on the severity alert signal. | Placeholder parameters; no change to twin alerts offline. |
| `ENABLE_SCENARIO_PERSISTENCE` | off | Requires a scenario label to hold for 6 days before Pulse changes scenario. | Not recommended: removed no false alerts, lost one detection. |

`docs/research_flags_evaluation.md` has the details. Invalid values stop the API at startup.

## Repository layout

```
src/
  data_synthesis/        synthetic patients and 21-day wearable trends
  scenario_classifier/   features, Random Forest classifier and severity regressor
  patient_builder/       Pulse patient and scenario files
  pulse_runner/          engine execution, crash/timeout detection, state save/resume
  analytics/             hemodynamic features, risk score, alert decision, staging, projection
  api/                   FastAPI app: models, schemas, routes, fresh and continuous pipelines
  evaluation/            scenario-test harness and analysis scripts for Experiments 1–3
  ml_models/             secondary XGBoost risk model (comparison only)
frontend/                React (Vite) dashboard
tests/                   pytest suite (Pulse mocked)
config/scenario_tests/   cohort files: stories, seeds and required flags per experiment
results/scenario_tests/  pre-registrations, amendments, per-day results and analyses (Exp 1 at top level, exp2/, exp3/)
data/                    synthetic data and real-data validation outputs (no raw restricted data)
artifacts/results-v1/    frozen models used for all reported results
models/                  model card and evaluation reports (the .joblib files are copied in, see Quick start)
docs/                    methodology, architecture, data provenance and evaluation notes (index: docs/README.md)
scripts/                 demo seeding, smoke test, paper figures, one-off engine diagnostics
backend/Dockerfile       backend + Pulse image (linux/amd64)
docker-compose.yml       Postgres, backend and frontend
```

## Data

Training data are synthetic. The generator's population statistics come from aggregate statistics
of real sources: MIMIC-IV (11,837 HF admissions), the Chicco–Jurman HF clinical records, NHANES and
published NT-proBNP cut-offs. Validation used the PerHeart pilot dataset (real home data), MIMIC-IV
and the Zigong HF cohort (real outcomes), and a BCG dataset with echocardiography. Raw MIMIC-IV,
Zigong and PerHeart files are not in this repository; access them under their own data-use
agreements. `docs/data_provenance.md` traces every clinical number to its source.

## Limitations

- Evaluation is on synthetic stories and retrospective data, with no prospective or clinical test.
- In continuous mode, Pulse's baroreflex keeps the twin at a low MAP after simulated exertion, and
  this state drives most high-risk days (`results/scenario_tests/exp3/RESULTS.md`).
- Pulse is unstable when disease modifiers combine with sustained exertion at high severity.
- The API has no authentication and is suitable only for research use.

The paper's Limitations section has the full list.

## Citation

```bibtex
@unpublished{sharma2026hfpulse,
  title  = {Design and Pre-Specified Evaluation of a Stateful, Wearable-Driven Digital Twin for
            Heart Failure Home Monitoring},
  author = {Sharma, Kaveri and Mohite, Mrunmayi and Singhal, Meghan and Balasubramanyam, Adithya},
  note   = {Manuscript in preparation},
  year   = {2026}
}
```

## License

Code: [MIT](LICENSE), copyright 2026 Kaveri Sharma, Mrunmayi Mohite, Meghan Singhal. Data keep
their own terms: outputs derived from the PerHeart dataset (`data/real_world_validation/`) are
CC BY-NC-SA 4.0 (see `LICENSE_NOTE.md` in each run directory), and the Pulse engine in the backend
image keeps its own license.

## Acknowledgment

This work used the resources of CAVE Labs, Center for IoT, PES University, Bengaluru. It received
no external funding.
