# Handoff: running M2K HF-PULSE v1.2 from a fresh clone

This is the short, current path from `git clone` to the five-patient demo. The older root `HANDOFF.md` is a long session log written for earlier phases. Where the two disagree, **this file wins**: in particular, **do not retrain the models**. Restore the frozen results-v1 models instead (step 3).

Repo: https://github.com/Mrunmayi019/M2K-HF-PULSE (`main`; release tag `v1.2`).

## 1. Prerequisites

- **Docker Desktop** (WSL2 backend on Windows), Docker Compose v2. At least 8 GB of memory for Docker, and about 25 GB of free disk for images and volumes.
- **Python 3.11+** on the host. It is only needed for the seed script (standard library only) and for optional local tooling.
- **Git.** Node 20 is needed only for frontend development outside Docker.
- On Windows, read §8 **before** the first build.

## 2. Docker and the Pulse engine image

```bash
docker pull kitware/pulse:4.3.1     # ~3.8 GB; the backend image copies /pulse out of it
```

The backend image (`backend/Dockerfile`) is built `FROM kitware/pulse:4.3.1` and pinned to `linux/amd64`. There is no arm64 Pulse build.

## 3. Restore the frozen models (always, before every build or run)

`models/*.joblib` is gitignored. The frozen results-v1 models are committed under `artifacts/results-v1/models/`, and every reported result used them. **They are copied into the backend image at build time** (`COPY . .`), so restore them **before** `docker compose build`:

```bash
cp artifacts/results-v1/models/scenario_classifier.joblib models/
cp artifacts/results-v1/models/severity_regressor.joblib  models/
sha256sum -c docs/results-v1-models.sha256      # all four lines must say OK
```

PowerShell: `Copy-Item artifacts\results-v1\models\*.joblib models\`, then compare `Get-FileHash models\*.joblib -Algorithm SHA256` with `docs/results-v1-models.sha256`.

Expected SHA-256 (the same values are in `results/scenario_tests/RESULTS.md`):

| File | SHA-256 | Bytes |
|---|---|---|
| `scenario_classifier.joblib` | `2157cb21991390e6b2417ff8793c2b62a32eeef7467963b94d5058cc37d05a49` | 9,252,401 |
| `severity_regressor.joblib` | `4b7afeab6210464b2e3730bf54248362db0ecc83ed58626a488fd3d47cb79f0e` | 37,213,825 |

Do this again whenever `models/` might have been overwritten, for example after running `python -m src.scenario_classifier.train`, which writes new, different models into `models/`. If a model was rebuilt into an image, rebuild the image after restoring.

## 4. Synthetic data

`data/synthetic/patients.csv` and `wearable_trends.csv` are committed, so a fresh clone already has them. To regenerate them (deterministic, seed 42; the result should equal the committed files):

```bash
pip install -r requirements.txt
python -m src.data_synthesis.generate_patients         # data/synthetic/patients.csv (n=2000)
python -m src.data_synthesis.generate_wearable_trends  # data/synthetic/wearable_trends.csv
```

Without a host Python environment, run the same commands inside the backend image. `./data` is bind-mounted:

```bash
docker compose run --rm pulse-backend python -m src.data_synthesis.generate_patients
docker compose run --rm pulse-backend python -m src.data_synthesis.generate_wearable_trends
```

## 5. Start the backend and frontend (fresh mode, all flags off)

```bash
docker compose up -d --build
```

- Frontend: http://localhost:3000. API: http://localhost:8000 (`/docs` for OpenAPI).
- **Fresh mode with every feature flag off is the default** and needs no configuration: `PIPELINE_MODE=fresh`, and `ENABLE_BCG_MODIFIERS`, `ENABLE_HR_BASELINE`, `ENABLE_ALERT_HYSTERESIS` and `ENABLE_SCENARIO_PERSISTENCE` are all off (`src/feature_flags.py`). This is the configuration that matches results-v1 (`tests/test_flags_off_parity.py`). Do not set any flag for the demo.
- To change a flag, use a compose override file (`docker compose -f docker-compose.yml -f my-override.yml up -d`) with `pulse-backend.environment`. Use a **separate Postgres volume** for any flag-on run, so the flags-off demo data is never mixed with it.
- Never run `docker compose down -v` on a stack whose database you want to keep: `-v` deletes the Postgres volume.

## 6. Seed the five demo patients

```bash
python scripts/seed_demo_patients.py                       # API at http://localhost:8000
python scripts/seed_demo_patients.py --base-url http://localhost:8100   # another port
```

The script submits each patient through the live API and waits for the real Pulse run, which takes about 5–10 minutes per patient, one at a time. It skips patients that already exist. Then follow **`docs/demo_walkthrough.md`**: what to click for each patient, the expected values, why DEMO 5's projections fail, and how to show continuous mode safely (DEMO 1 plus the reset button only).

## 7. What is not in git, and how to get it

| What | Where it lives | How to get it |
|---|---|---|
| Working models `models/*.joblib` | gitignored | Copy from `artifacts/results-v1/models/` (committed), as in §3. |
| Clinical-only model variants (`models/*_clinical_only.joblib`) | gitignored, local only | `python scripts/train_clinical_only_variant.py`. Needs the raw datasets below. Not used by the app. |
| **MIMIC-IV** extract (`data/raw/mimic/`) and every per-patient MIMIC result (`data/mimic_outcome_validation/results.csv`) | gitignored | Requires **PhysioNet credentialed access** and a signed DUA (https://physionet.org/content/mimiciv/), queried via Google BigQuery (`physionet-data`). **Row-level MIMIC data must never be committed**, de-identified or not. Only aggregate `summary.md` files are committed. |
| **Zigong** HF EHR data and its per-patient results (`data/zigong_*/results.csv`, `*_features.csv`) | gitignored | PhysioNet restricted access, same rule as MIMIC: never commit row-level data. |
| Kaggle datasets (`andrewmvd/heart-failure-clinical-data`, `fedesoriano/heart-failure-prediction`, `cdc/national-health-and-nutrition-examination-survey`) | `data/raw/kaggle/`, gitignored | Download from Kaggle with your own Kaggle API key. |
| PerHeart pilot dataset | `data/raw/perheart/`, gitignored | Zenodo, DOI `10.5281/zenodo.17143199`. |
| Gu TriSeg digital-twin data (`data/raw/gu_triseg/`) | gitignored | From its authors' public "TriSeg-Digital-Twins" repository (Feng et al.); see `data/raw/gu_triseg/README.md` on a machine that has it. |
| Sources and licences for all of the above | — | `docs/data_provenance.md`, `docs/claims_methodology.md`. |
| **`data/bcg_ablation/`** (102 MB, untracked in the main checkout) | local only | Pulse runs of the BCG-modifier ablation for calibration subjects 14 and 102 (arms A–E, BCG_only, D_HR). Every small file is committed on branch `experiment/calibration-pilot`. Only the raw per-timestep `scenarioResults.csv`/`full_results.csv` dumps are local. They can be regenerated by rerunning the ablation scripts on that branch. That branch is unreviewed: don't merge it. |
| **`data/calibration_pilot/`** (61 MB, untracked in the main checkout) | local only | Pulse runs for the TriSeg calibration pilot (`runs/`, `sensitivity/`, `bp_check/`, `arm_c/`). Same situation: reports and small files are on `experiment/calibration-pilot`, raw `scenarioResults.csv` dumps are local only. |
| Raw Pulse per-timestep dumps elsewhere (`data/bcg_validation/**`, `data/synthetic_deterioration_stress_test/**`, `scenarios/**`) | gitignored | Regenerable by rerunning the corresponding script. The small evidence files beside them are committed. |
| Scenario-test per-run SQLite DBs (`results/scenario_tests/flag_runs/*/dbs/`, ~1.4 GB) | gitignored | Rerun the harness. `raw_labels.csv` keeps what the evaluation needs. |
| Local SQLite DB (`data/db/`), Postgres volumes (`*_pg_v12_flagsoff`, `*_pg_v12_continuous`) | Docker / local | Recreated by §5–6. The demo PC's volumes hold the 2026-10-08/09 demo-check data. |
| Demo-check logs (`D:\pulse-release-work\results\`: `run2_continuous.log`, `run2_container_files/`, `dashboard_notes.md`) | demo PC only | The source for `docs/research_flags_evaluation.md` §7. Copy them off that machine if they are still needed. |
| **Secrets** | your local `.env` | Copy `.env.example` to `.env` (gitignored by `*.env`) and fill it in. The app itself needs no API keys. Credentials (PhysioNet/BigQuery, Kaggle) only ever go in `.env` or your own credential store. |
| `venv/`, `frontend/node_modules/`, `frontend/.env` | gitignored | `python -m venv venv && pip install -r requirements.txt`; `npm ci` in `frontend/`; `frontend/.env` holds only `VITE_API_URL`. |

## 8. Windows notes

- **Docker storage on D:.** Docker Desktop → Settings → Resources → Advanced → *Disk image location*. On the demo PC it is `D:\dockerData\DockerDesktopWSL\disk\docker_data.vhdx` (about 21 GB with these images). Keep it off C: if C: is nearly full.
- **Temp and cache folders on D:.** Point `TEMP`/`TMP`, `PIP_CACHE_DIR` and the npm cache at D:, for example:
  ```powershell
  setx TEMP D:\tmp ; setx TMP D:\tmp ; setx PIP_CACHE_DIR D:\pip-cache
  npm config set cache D:\npm-cache
  ```
  Docker Desktop also downloads its updates into `%LOCALAPPDATA%\Temp\DockerDesktopUpdates` on C: (about 600 MB). Turn off automatic update checks if C: space matters.
- **pip timeouts.** On slow or filtered connections, use `pip install --timeout 120 --retries 10 -r requirements.txt`. The backend Dockerfile already sets `PIP_DEFAULT_TIMEOUT=120` and `PIP_RETRIES=10`.
- **Avast HTTPS scanning breaks builds.** Avast Web Shield intercepts TLS. `docker compose build` then fails in pip (`CERTIFICATE_VERIFY_FAILED`, or corrupt downloads), and git/pip can fail on the host too. Turn off *Enable HTTPS scanning* before building and turn it back on afterwards.
- **Memory.** Give Docker 8 GB. One Pulse run uses about 0.3 GB of container memory at 100% of one CPU. Seed patients one at a time (the seed script does). Keep the laptop plugged in and awake: if it sleeps, Pulse pauses and the wait can time out. Windows may grow the pagefile on C: during long runs.
- **Always restore the frozen models before running** (§3). It is the easiest step to forget, and a stale `models/` silently changes every result.

## 9. Fresh-clone check

Run on 2026-10-09 on the demo PC (Windows 11, Docker Desktop, Compose v5.1.4), following this file from a fresh `git clone -b docs/handoff` into `D:\pulse-release-workresh-clone-test`. The test ran beside the live demo, so it used a separate compose project name and different ports (an override with `ports: !override`, backend 8100, frontend 3100, `VITE_API_URL=http://localhost:8100`).

- §3: models copied from `artifacts/results-v1/models/`. `sha256sum -c docs/results-v1-models.sha256` gives 4 × OK, and the models baked into the built image have the same hashes. The first attempt found that a Windows CRLF checkout breaks `sha256sum -c`; `.gitattributes` now keeps `*.sha256` as LF.
- §4: both generators, run inside the backend image, reproduce the committed `data/synthetic/*.csv` exactly (0 changed lines; only line endings differ on a Windows checkout).
- §5: `docker compose up -d --build` completed; the frontend served HTTP 200 and the API answered.
- §6: all five demo patients ran on real Pulse and reproduced `docs/demo_walkthrough.md` exactly:

| Patient | Scenario | Severity | Risk | Bucket | NYHA | Alert |
|---|---|---|---|---|---|---|
| DEMO 1 | stable | 0.12 | 0.006 | LOW | I | NONE |
| DEMO 2 | acute_deterioration | 0.59 | 0.736 | HIGH | IV | ALERT |
| DEMO 3 | deconditioning (EF defaulted) | 0.66 | 0.055 | LOW | II | NONE |
| DEMO 4 | fluid_overload | 0.70 | 0.508 | MODERATE | III | WATCH |
| DEMO 5 | cardiac_stress | 0.40 | 0.770 | HIGH | IV | ALERT |

DEMO 5's three projections (projected severity 0.409 / 0.418 / 0.438) came back `failed`, as documented. The seed script's own process was stopped by the host for low memory while it was waiting on DEMO 5. The backend still finished DEMO 5, and its values above were read from the API. Afterwards, only the test project's containers were removed (`docker compose -p m2k-freshclone-test down`, without `-v`).
