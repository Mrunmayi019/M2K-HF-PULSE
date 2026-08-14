# Handoff — M2K HF-PULSE

**Read this first if you are a new Claude Code session picking up this project from a fresh
`git clone` / GitHub zip download, with no memory of prior sessions.** This file is committed to
the repo specifically so it survives that transfer (unlike session-local planning docs, which are
gitignored). It is intentionally long and explicit — assume nothing carries over except what's
written here and in the rest of the repo.

Owner: Kaveri Sharma (`kaveri05sharma@gmail.com`, GitHub `kaverii11`), sole author/committer.
Repo: https://github.com/Mrunmayi019/M2K-HF-PULSE — working branch is `main` directly (no PR
workflow; Kaveri is the only contributor). Purpose: a research paper on a personalized
heart-failure digital-twin system, built on the Kitware Pulse physiology engine.

---

## 1. Set up the machine, first

Full step-by-step is in `docs/running_the_stack.md`; `readme.md`'s "Quick Start" has the one-line
version. The one thing neither says loudly enough:

**Train the ML models locally before your first `docker compose up --build`.**
`models/*.joblib` are gitignored (never committed — they're derived artifacts, not source), and
they are baked into the backend image at build time (not volume-mounted), so a fresh clone has no
models until you generate them:

```bash
pip install -r requirements.txt
python -m src.scenario_classifier.train      # writes models/scenario_classifier.joblib + severity_regressor.joblib
docker compose up --build                    # now the image will have real models
```

Skip this and every patient's background assessment silently crashes with
`FileNotFoundError: /workspace/models/scenario_classifier.joblib` the first time a 21-day
wearable window fills — see `docs/running_the_stack.md`'s troubleshooting section for the full
symptom description and recovery steps if this already happened to you.

You need: Python 3.11+, Docker Desktop (with WSL2 backend on Windows), Node 20 (only if touching
the frontend directly — `docker compose` builds it for you otherwise). Full env verification
(`docker --version`, `docker compose version`, GPU/CPU notes for Apple Silicon) is in
`docs/running_the_stack.md`.

**Git identity for this repo — set this before your first commit:**
```bash
git config user.name "Kaveri Sharma"
git config user.email "kaveri05sharma@gmail.com"
```
**Every commit in this repo's history is authored solely by Kaveri Sharma — no AI co-author
trailer.** This is a deliberate, explicit standing instruction from the repo owner, not an
oversight. Continue that convention: do not add `Co-Authored-By: Claude ...` (or any AI tool) to
commit messages in this repo, regardless of what tool authored the diff.

---

## 2. Two directories, historically — know which one you're in

Earlier work on this project (before this repo existed in its current form) happened across two
separate local directories on the original dev machine: `M2K-HF-PULSE-main` (an extracted zip,
used to actually run `docker compose`) and `M2K-HF-PULSE-repo` (a proper git clone, used for
version control). **They drifted** — code fixes landed in `-repo` and had to be manually
re-synced into `-main` more than once before rebuilding Docker, which cost real debugging time.

**On a fresh machine working from this GitHub repo, you don't have this problem** — there's only
one directory, and it's both your git checkout and what you build Docker from. But if you ever see
two differently-named copies of this project on disk again (e.g. an old zip extraction alongside a
fresh clone), assume they've diverged and don't build Docker from the stale one without diffing
first.

---

## 3. What's done — status as of this handoff (2026-08-14)

High-level (see `readme.md` "Status" and `docs/methodology.md` for full phase-by-phase history):
Phases 1-9 (data synthesis, Pulse integration, ML models, risk scoring, API, frontend, Docker/CI)
are complete and tested (143/143 tests passing, `pytest tests/ -v`). The frontend's 4 previously
placeholder tabs (Trends & History, Simulation Lab, Reports, Settings) are fully built. Real-world
data integration is done: the PerHeart Pilot Dataset (Zenodo 10.5281/zenodo.17143199, 27 real HF
patients) has been replayed through the live pipeline twice (`docs/real_world_data_integration.md`
§8).

**This session's work (all pushed to `main`, commit `affe1a8` and prior):**

1. **Diagnosed and fixed a live severity-regressor bug** (`nyha_ordinal` train/inference
   mismatch — live severity MAE was 0.271 vs. 0.048 offline). Fixed by removing `nyha_ordinal`
   from the feature set entirely (`src/scenario_classifier/features.py`). Full story:
   `docs/methodology.md` §9, `models/model_card.md`.
2. **Re-ran the 16-patient PerHeart cohort against the fixed model**: 13/16 completed (81%),
   severity range widened from a compressed 0.078–0.148 to a realistic 0.093–0.516. 3 new
   engine-crash failures analyzed, not hidden. `docs/real_world_data_integration.md` §8.4.
3. **Fixed the `fluid_overload` risk-score blind spot.** `risk_score.py`'s `compute_risk_score()`
   only ever saw hemodynamic *change* during one Pulse encounter, so `fluid_overload` (whose
   danger is an already-abnormal *baseline*, not an acute swing) scored a constant 0.000
   regardless of true severity — confirmed on all 30 `fluid_overload` rows in the 117-row Phase 4
   batch. Fix: added a `baseline_deficit_score` term (from `map_start`, already computed but
   previously discarded) and `risk_score = max(acute_score, baseline_deficit_score)` — the
   existing 5 acute weights/citations are untouched. Post-fix: mean `fluid_overload` risk_score
   0.000 → 0.501, `risk_bucket` 30/30 `LOW` → 29/30 `MODERATE`. `src/analytics/risk_score.py`'s
   module docstring has the full design rationale; `models/model_card.md` and
   `docs/methodology.md` §6.1 have the numbers.
4. **Expanded statistical rigor**: bootstrap 95% CIs added everywhere point estimates used to
   stand alone (offline test-set accuracy/MAE, live re-validation MAE/accuracy), ROC/AUC added
   for the scenario classifier (macro-AUC 0.990), and the live re-validation sample grew from
   n=5 to n=30 (20 completed — see the degradation finding below). `scripts/model1_extended_eval.py`
   is new; run it any time to regenerate `models/roc_curves.png`,
   `models/risk_score_reliability_proxy.png`, `models/phase3_extended_eval_report.txt`.
5. **Wrote a missingness/failure-mechanism analysis** (`docs/methodology.md`, new subsection at
   the end of §5): this project's Pulse failures are not one phenomenon. There are two, with
   opposite statistical character:
   - **Mechanism 1 — engine crash** (`PulseScenarioDriver exited 1`), **MNAR with respect to
     severity**: concentrated in `cardiac_stress`/`acute_deterioration` (the two `Exercise`-action
     scenarios) specifically at *high* severity. Confirmed independently across 4 separate runs
     this session.
   - **Mechanism 2 — resource-contention timeout** (180s ceiling / `ReadTimeout`), **MAR with
     respect to concurrency level**, not severity: solved by capping concurrency at 2 workers
     (`docs/real_world_data_integration.md` §8.3).
   - **A third, not-yet-fully-explained pattern surfaced in this session's final run** (see
     item 6 below) — worth reading if you pick up the 180s-timeout diagnostic work.
6. **New finding, not yet root-caused: Docker Desktop/WSL2-level performance degradation after
   hours of sustained Pulse subprocess load.** During the expanded (n=30) live re-validation run,
   per-patient wall-clock time climbed mid-run from ~400-500s to 700+s, and failures started
   hitting *every* scenario type and severity level (not just the high-severity
   `cardiac_stress`/`acute_deterioration` pattern above) — 15/28 failed at one point (54%).
   A `pulse-backend` **container** restart partially helped (first 2 retried patients succeeded)
   but did not fully resolve it (8 of the next 10 still failed). `docker stats` showed normal
   CPU/memory for the container throughout, and host CPU was only ~33% utilized — ruling out
   obvious resource contention at either layer. This suggests degradation below the container
   level (the Docker Desktop VM / WSL2 itself) that a full **Docker Desktop restart** (not just a
   container restart) might clear — **this was not attempted** in this session, by choice, to
   avoid further delaying an already-long run. Full details, including exact timings:
   `data/validation_runs/20260812_184726_nyha_fix_revalidation/summary.md`.

---

## 4. What's left — full to-do, in priority order

This section is the up-to-date, complete replacement for a prior session-local `PUBLICATION_TODO.md`
that was deliberately gitignored and does not exist on a fresh clone. Treat this as the
authoritative current list.

### P1 — biggest blockers to a credible submission

- [ ] **Real clinical outcome validation.** Everything validated so far (synthetic + PerHeart
      real data) shows the pipeline runs correctly on real inputs — not that its risk predictions
      correlate with actual outcomes (hospitalization, real deterioration events). This is the
      single biggest gap between "systems demo" and "clinical research paper." Not solvable in
      code. Needs a clinical partnership: identify a cardiology department/HF clinic contact,
      scope what outcome data they could share, check IRB requirements at Kaveri's institution.
      **Not started.** This is the long pole — start the conversation early and do the other
      items in parallel while it's in progress.

- [ ] **Diagnose the Pulse failure/timeout behavior properly**, combining two related open
      questions:
      (a) Is the ~180s Pulse-subprocess ceiling itself a Docker Desktop/WSL2-specific
      characteristic of this host, or universal? Real Pulse calls have been observed landing
      right at 170-190s repeatedly. If host-specific, this belongs in the paper's
      reproducibility section as an environment caveat, not presented as a universal figure.
      (b) **New and higher-priority**: root-cause the session-degradation finding in §3 item 6
      above. Try a full Docker Desktop restart (not just `docker compose restart`) before the
      next long real-data run and see if it recovers full-speed performance — this is the
      concrete, cheap next experiment. If it does, that confirms VM-level degradation and the
      practical mitigation is "restart Docker Desktop between long runs, not just containers."
      If it doesn't, the degradation may be host-level (thermal, memory fragmentation over
      session length) and worth a full machine reboot test instead.

- [ ] **Re-run the PerHeart cohort a third time**, now against the `fluid_overload`-fixed risk
      scorer (item 3 in §3 above was validated offline against the 117-row Phase 4 batch, not
      re-validated against PerHeart or the live API). `docs/real_world_data_integration.md` §8.4
      flags this explicitly. Cheap in code terms
      (`python -m scripts.perheart_real_data_replay --resume-from data/real_world_validation/20260812_162112/results.csv`
      — note: since only `severity`/`scenario_type` changed with the nyha fix and this new fix
      only changes `risk_score`, you may want a fresh full run rather than `--resume-from`, which
      skips patients already marked `complete` and would carry forward stale `risk_score` values
      for them; check `scripts/perheart_real_data_replay.py`'s own docstring for the exact
      resume semantics before choosing). Budget ~90-150 min real Docker time at 2-worker
      concurrency, more if the degradation pattern in §3 item 6 recurs.

- [ ] **Increase the live re-validation completion rate**, or explicitly document why n=20 (not
      n=30) is the reportable number. Options, cheapest first: (a) just re-run
      `scripts/nyha_fix_live_revalidation.py --resume-from <path to 20260812_184726 run's
      combined_results.csv>` after a full Docker Desktop restart, to top up the remaining ~10
      patients; (b) if the degradation recurs, accept n=20 and write the methods section to be
      explicit that a real environmental constraint, not sample availability, set the final n.

### P2 — known, scoped gaps worth closing before submission

- [ ] **Quantify statistical power more explicitly for the small real-world samples.** n=16
      (PerHeart) and n=20 (live re-validation) are still small. Before treating either as a
      population-level result: consider widening the live re-validation further (the script
      supports any `n_per_scenario` argument — `python -m scripts.nyha_fix_live_revalidation 10`
      for n=50, budget accordingly), and/or explicitly report power/precision limitations in the
      paper rather than treating the bootstrap CIs already computed as sufficient on their own.

- [ ] **Benchmark against an established clinical risk score** (Seattle Heart Failure Model,
      MAGGIC, or GWTG-HF). Journals want evidence of added value over existing standards of
      care, not just internal self-consistency. Scope: (a) pick one with a public/implementable
      formula, (b) compute it on the same synthetic + PerHeart cohorts, (c) compare risk-bucket
      agreement or discrimination (AUC) against `src/analytics/risk_score.py`'s output.
      **Not started.**

- [ ] **Medication modeling.** Nearly all real HF patients are on diuretics/beta-blockers/ACE
      inhibitors — none represented in current Pulse scenarios, a real gap for any
      real-world-applicability claim. Scope: does Pulse itself support drug-modeling actions? Do
      a quick feasibility check (read Pulse's own action/state documentation, check
      `backend/`'s Pulse SDK bindings for anything drug-related) before committing engineering
      time — this might be out of reach without engine-level work. **Not started.**

### P3 — strengthens the paper's positioning

- [ ] Related-work / positioning section — how this compares to existing HF digital-twin and
      wearable-risk-prediction literature. Pure writing, no code. **Not started.**

- [ ] Formal ethics & data-availability statement — can cite PerHeart's own ethics approval
      (Jagiellonian University, ref. 1072.6120.17.2023) and the license-discrepancy handling
      already documented in `docs/real_world_data_integration.md` §2.1. **Not started.**

### P4 — standard journal scaffolding (not modeling work, but required)

- [ ] Reproducibility package — this repo's own documentation culture (`docs/methodology.md`,
      `docs/data_provenance.md`, `models/model_card.md`) is already a genuine strength; mostly
      needs packaging/pointing to in the paper, not rebuilding.
- [ ] Decide on and check the target journal's AI-tool-usage disclosure policy for the paper text
      itself. Note: this is separate from git commit history, which is already solely under
      Kaveri's name by deliberate policy (§1 above) — that policy concerns *code* authorship
      attribution, not what the *paper text* needs to disclose about how it was written, which is
      a separate decision the target journal's policy will determine.

### Suggested order of attack

1. Try the Docker Desktop restart experiment (P1, cheap, directly unblocks re-runs).
2. Re-run PerHeart against the `fluid_overload` fix (P1).
3. Top up the live re-validation sample (P1).
4. Start the real clinical outcome validation conversation *now*, even though it's slow
   (institutional timelines are the long pole — start early, keep doing P2/P3/P4 in parallel).
5. Benchmark comparison + medication-modeling feasibility check (P2).
6. Related-work/ethics writing (P3).
7. Journal scaffolding (P4) — do last, once the results section is stable.

---

## 5. Quick reference

| What | Where |
|---|---|
| Full phase-by-phase project history | `docs/methodology.md` |
| Model performance numbers, both models | `models/model_card.md` |
| Real-world (PerHeart) data integration writeup | `docs/real_world_data_integration.md` |
| Data provenance / real-vs-synthetic/imputed rules | `docs/data_provenance.md` |
| Docker/local setup, troubleshooting | `docs/running_the_stack.md` |
| Re-run PerHeart cohort | `python -m scripts.perheart_real_data_replay` (see its own docstring for flags) |
| Re-run live severity/scenario re-validation | `python -m scripts.nyha_fix_live_revalidation [n_per_scenario]` |
| Regenerate ROC/AUC + bootstrap CI report | `python -m scripts.model1_extended_eval` |
| Retrain ML Model 1 (classifier + regressor) | `python -m src.scenario_classifier.train` |
| Run the test suite | `pytest tests/ -v` (143 tests, no Docker required) |
| Primary risk-score formula | `src/analytics/risk_score.py` (read its module docstring first) |

**2-worker concurrency ceiling**: any script hitting the live API with multiple patients at once
(`scripts/perheart_real_data_replay.py`, `scripts/nyha_fix_live_revalidation.py`) is hardcoded to
`MAX_SAFE_WORKERS = 2`. This was empirically derived this session (higher worker counts caused
DB connection-pool exhaustion and CPU contention — see `docs/real_world_data_integration.md` §8.3)
and should not be casually raised without re-deriving it on the actual host being used.
