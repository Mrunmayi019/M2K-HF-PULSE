# Reproducibility Package (draft index)

**Status: pointer/index doc, not new content.** `HANDOFF.md` P4 notes this project's own
documentation culture is already a genuine strength for a journal's reproducibility checklist —
this doc's job is to make that easy to find and cite, not to rebuild anything.

## What a reviewer/reader needs, and where it already is

| Reproducibility need | Where it already exists in this repo |
|---|---|
| Full system architecture, current + target | `docs/architecture.md` |
| Why each design/modeling decision was made, phase-by-phase | `docs/methodology.md` (69KB — the single most load-bearing doc; §5-§9 cover training protocol, risk-scoring formula + citations, API/pipeline design, and an honest limitations + failure-mechanism analysis) |
| Every clinical number traced to a source | `docs/data_provenance.md` |
| Both trained models' training data, performance, limitations | `models/model_card.md` |
| Real-world (non-synthetic) validation methodology + results | `docs/real_world_data_integration.md` |
| Frontend build rationale + manual verification evidence | `docs/frontend_extension_validation.md` |
| Step-by-step environment setup, troubleshooting | `docs/running_the_stack.md` |
| Benchmark comparison against an external clinical score | `docs/benchmark_comparison.md` (this session) |
| Medication-modeling feasibility investigation | `docs/medication_modeling_feasibility.md` (this session) |
| Related-work positioning | `docs/related_work.md` (this session, first-pass) |
| Ethics / data-availability statement | `docs/ethics_statement.md` (this session, first-pass) |

## Reproduction steps (already-documented commands, gathered in one place)

```bash
# 1. Environment
pip install -r requirements.txt

# 2. Train both ML Model 1 components (classifier + severity regressor)
python -m src.scenario_classifier.train

# 3. Run the test suite (156 tests as of this session: 143 original + 13 new for the
#    MAGGIC benchmark comparator — no Docker required)
PYTHONPATH=. pytest tests/ -v

# 4. Full stack (Postgres + FastAPI/Pulse backend + React frontend)
docker compose up --build
# then: bash scripts/docker_smoke_test.sh   -- real end-to-end Pulse pipeline check

# 5. Regenerate the statistical/benchmark artifacts
python -m scripts.model1_extended_eval        # ROC/AUC + bootstrap CIs
python -m scripts.benchmark_comparison         # MAGGIC comparison (this session)

# 6. Real-world (PerHeart) replay (Docker required, calls live API)
python -m scripts.perheart_real_data_replay
```

## What's NOT reproducible from a fresh clone alone

Being explicit about this rather than letting a reviewer discover it independently:

- **Trained models** (`models/*.joblib`) are gitignored — must be regenerated locally (step 2
  above) before `docker compose up --build`, or the backend's background pipeline crashes with
  `FileNotFoundError` on the first patient (`docs/running_the_stack.md` troubleshooting section).
- **Raw source data** (`data/raw/mimic/`, `data/raw/perheart/`, Kaggle/NHANES extracts) is
  gitignored per this project's "never real/raw patient data in git" rule
  (`docs/data_provenance.md`). The *derived* synthetic datasets and aggregate reference statistics
  used to build them ARE committed (`data/synthetic/`,
  `src/data_synthesis/reference_stats.yaml`) — the generator is fully reproducible from those, but
  re-deriving the reference statistics from scratch requires re-obtaining PhysioNet-credentialed
  MIMIC-IV access and the specific Kaggle/NHANES downloads named in `data_provenance.md`.
- **PerHeart real-data replay** downloads its own ~32KB input on first run (script docstring,
  `scripts/perheart_real_data_replay.py`) but needs the live API running, real Docker/Pulse time
  (3-12 min/patient), and is gated by the license-discrepancy handling in
  `docs/real_world_data_integration.md` §2.1.
- **Exact wall-clock numbers** throughout `docs/methodology.md`/`docs/real_world_data_integration.md`
  (e.g. ~110s/Pulse-call, the Docker Desktop/WSL2 degradation finding) are specific to the
  original development host's Apple Silicon emulation and are explicitly flagged in those docs as
  environment-dependent, not universal — a reviewer reproducing on different hardware should
  expect different absolute timings, not necessarily the same qualitative findings.

## Still open (not this doc's job to close)

- AI-tool-usage disclosure for the paper text itself — target-journal-dependent, `HANDOFF.md` P4
  flags this as a separate decision from the git-commit-authorship policy (`HANDOFF.md` §1),
  which is already settled (solely Kaveri Sharma, no AI co-author trailer).
- A DOI/archival snapshot (e.g. Zenodo-archiving a tagged release of this repo) if the target
  journal wants one — not set up yet.
