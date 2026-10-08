# Gap report: what is not connected, which claims hold, what remains

Audit date: 2026-10-06. Read-only: no code, config, model or data was changed and nothing was merged. This file is the only addition.

**Baseline audited: tag `results-v1` (`e4257ff`).** Its tree is byte-identical to `results-rc1`, so every static finding and live result in [`docs/app_integration_audit.md`](app_integration_audit.md) (the "audit" below) applies unchanged and is cited, not re-derived. That audit's live tests are not repeated here.

**Important correction to the brief: PR #5 is already merged.** `origin/main` (`f1c8656`) = `results-v1` + `470563d` "Unify ML-severity alert and risk-scorer alert into one decide_alert() (#5)" + three paper-only commits. The `fix/unified-alert-decision` branch has no content left that `main` lacks (all its files match `main`; its extra commits are pre-squash history). Wherever PR #5 changes something, it's noted as **[PR #5]**. "main" below means `results-v1` unless it says `origin/main`.

Entry points traced: the 9 routes in `src/api/routes.py` (POST/GET `/patients`, POST `/clinical-report`, POST `/wearable-sync`, GET `/wearable-history`, `/status`, `/history`, `/projection`, `/report`) and the 7 client calls in `frontend/src/api/client.js:24-66`. `getStatus` (`client.js:40`) is never called by any component. Module reachability was computed from an AST import graph rooted at `src/api/main.py`.

---

## Table 1: Not connected to the app

### 1a. Backend code no route reaches

| Item | File:line | Group | Note |
|---|---|---|---|
| Continuous state sync: `run_daily_continuous_pipeline`, `PulseState` table, `cli_state_runner.py`, `cli_state_scenario.py` | `src/api/continuous_state_pipeline.py:143`; `src/api/models.py:170`; `src/pulse_runner/cli_state_runner.py`, `cli_state_scenario.py` | **Finished but unwired** | Only `scripts/verify_continuous_state_*.py` and tests call it. Audit §1 #7, §2.4, §3b (verified with real Pulse: 0 `pulse_states` rows). |
| BCG personalisation `bcg_to_cardiovascular_modifiers()` + `build_scenario_file(extra_modifiers=…)` | `src/patient_builder/patient_file.py:200`; `scenario_file.py:151-162` | **Finished but unwired** | `services.py:268-273` never passes `extra_modifiers`. There's no BCG input anywhere in the API or UI. |
| HR-baseline personalisation `build_patient_file(hr_baseline_bpm=…)` | `patient_file.py:83` | **Finished but unwired** | No API call site passes it (`claims_methodology.md:34` confirms). |
| Alert hysteresis `hysteresis_alert_states()` and `scenario_type_persistence()` | `src/analytics/score_reporting.py:254,345` | **Finished but unwired** | Called only from `tests/test_score_reporting.py`. Every API alert is computed from a single day. |
| Crash-zone skip `run_pulse_with_preflight(skip_if_unstable=True)` | `src/pulse_runner/runner.py:145` | Finished but unwired (by design: the default is to flag, not skip) | |
| `needs_pulse_capping()` | `patient_file.py:74` | Research/test helper | Tests only. |
| `build_features()` (training-time feature builder) | `src/scenario_classifier/features.py:55` | Research-only by design | The API uses `build_inference_features()`. |
| MAGGIC score | `src/analytics/benchmark_scores.py:133` | Research-only by design | `scripts/benchmark_comparison.py`, `scripts/zigong_maggic11_validation.py`. |
| Outcome-calibration data contract | `src/analytics/outcome_calibration.py:1-19,38-74` | Research-only by design ("FOUNDATION ONLY … DELIBERATELY NOT POPULATED") | Tests only. |
| Reference-stat extraction | `src/data_synthesis/reference_extraction.py` | Research-only by design | Builds `reference_stats.yaml`; needs `data/raw/`. |
| Model training: `scenario_classifier/train.py`, `ml_models/train_risk_scorer.py` (XGBoost "secondary" scorer) | | Research-only by design | XGBoost output (`models/risk_scorer_xgb.joblib`) is not used by the API. |
| Phase-4 batch runner | `src/pulse_runner/batch_runner.py` | Research-only by design | Produced `features_dataset.csv`. |
| Pulse SDK save/resume | `src/pulse_runner/sdk_runner.py` | **Dead code** (its docstring: "SUPERSEDED … DO NOT USE") | Kept as a record of the segfault investigation. |
| `PatientNotFoundError` | `src/api/services.py:116` | **Dead code** | Never raised or caught anywhere. |
| Original prototype: `app.py` (Flask), `streamlit_app.py`, `src/rules.py`, `src/generator.py`, `src/run.py`, `src/legacy_analytics.py` | | **Dead code** with respect to the app (README:43-48 calls it "left untouched") | Separate demo; `src/run.py` hardcodes `/workspace/scenarios/generatedResults.csv`. |
| All 29 files in `scripts/` | | Research-only by design | BCG (9), Zigong/MIMIC outcome (7), validation/replay drivers (`validate_phase2/8`, `perheart_real_data_replay`, `nyha_fix_live_revalidation`, `reattempt_single_patient`), stress tests (2), continuous-sync verification (2), `model1_extended_eval`, `train_clinical_only_variant`, `docker_smoke_test.sh`. |

### 1b. Computed but never shown (API returns or DB stores; no component reads it)

| Field | Where produced | Note |
|---|---|---|
| `status.current_alert` (classifier-only fallback alert for failed runs) | `routes.py:168-179` | Audit §1 #4 and §2.3 (real browser: nothing shown). **[PR #5]** adds `status.alert`, but the failed-run screen (`AppShell.jsx:64-71`) is unchanged, so it's still not shown. |
| `latest_assessment_stale` | `routes.py:186` | Only mentioned in a comment (`AppShell.jsx:39`). |
| `score_provenance` (`alert`, `alert_basis`, `confidence`, `simulation_status`, `threshold_clinically_validated`), `severity_band` | `models.py:142-167` | Never read. **[PR #5]** the hero card now reads the new `alert.level`, but `score_provenance.alert` is still returned. That makes **two alert answers in one payload**, which disagreed live (P1: `alert` vs `WATCH`, audit §3b). |
| `ef_is_fallback`, `bnp_is_fallback` | `routes.py:51-60`, stored in `clinical_reports` | Not in `RiskAssessmentPayload` (`schemas.py:116-185`). The UI shows a defaulted 62% EF as if measured (audit §3 #6). |
| `waveform_data` on the Reports tab | `ReportsPage.jsx:91-96` doesn't pass it | Report text differs between the Dashboard and Reports tabs (audit §3 #9). |
| `/projection` per-horizon `risk_score`, `status` | `routes.py:220-229` | `ForwardProjectionPanel.jsx` reads only `projected_severity` and `risk_bucket`. |
| `component_scores`, `baseline_deficit_score`, `dominant_mechanism` | `services.py:344-347` | Simulation Lab tab only (`SimulationLabPage.jsx:228-240`), never on the main dashboard. |
| `simulation_runs.error_message` | | Shown, but as a **raw Python traceback** to the end user (audit §2.3). |

### 1c. Shown but not real

| Element | File:line | Problem |
|---|---|---|
| "Run New Simulation" button | `TopBar.jsx:14-22`, wired to `refresh` (`AppShell.jsx:75`) | Only re-fetches `/report`; it never runs a simulation. |
| "v0.1.0 · HIPAA-audited env" | `Sidebar.jsx:94` | Hardcoded compliance claim. No HIPAA work exists anywhere in the repo (no doc mentions it). |
| "Heart failure digital twin · continuous monitoring" | `TopBar.jsx:8` | The app recomputes each day from scratch; continuous state isn't used (1a). |
| "7-Day Trend" column | `VitalsTable.jsx:15` | Slopes are fitted over the full 21-day window (`deterioration_rate.py:73-100`, `np.polyfit` over all rows). The same table's subtitle says "21-day trend" (`VitalsTable.jsx:7`). |
| "Classified from wearable input" | `CurrentConditionPanel.jsx:53` | The classifier also uses age, sex, BMI, EF and NT-proBNP (`features.py:29-30`). This matters because a defaulted EF changes the classification. |
| "Pulse Pressure (mmHg, from loop)" | `CardiacWaveformPanel.jsx:89-90`, `DoctorReportCard.jsx:16` | LV pressure amplitude, not arterial pulse pressure (audit §1 13e). |
| Hero animated ECG | `EcgWave.jsx:4-27` | A hard-coded decorative path that looks like a live trace (audit §1 13b). |
| Hero risk-warning texts ("Model confidence is high", "seek clinical evaluation promptly") | `HeroStatusCard.jsx:10-14,20` | Unreachable, because `risk_caveats` (always containing the ECG disclaimer) takes precedence (audit §3 #5). **[PR #5]** renames these to `ALERT_WARNING` but keeps `risk_caveats \|\|` first, so they're still unreachable. |
| Sidebar "pending" for failed patients | `Sidebar.jsx:15` | The Reports tab says "failed" for the same patients (verified in a browser, audit §2.3). |
| Patient label | `Sidebar.jsx:87` only | Not settable via the API; other views ignore it (audit §1 13c). |
| Mock data | `frontend/src/mock/mockData.js` via `VITE_USE_MOCK` (`usePatients.js:5` etc.) | Off by default. `VITE_USE_MOCK` isn't in `frontend/.env.example`. |

### 1d. Database tables and columns

| Table/column | Written by app? | Read by app? |
|---|---|---|
| `pulse_states` (whole table) | **No** (scripts only) | **No** |
| `patients.label` | **No** (manual SQL only, `models.py:34-38`) | Sidebar only |
| `clinical_reports.bnp_is_fallback` | Yes | **Never read** |
| `clinical_reports.ef_is_fallback` | Yes | Read by the pipeline (`services.py:216`), never returned to the UI |
| `simulation_runs.scenario_json_path` | Only on failure (`services.py:291`) | **Never read** |
| `simulation_runs.started_at`, `completed_at` | Yes | **Never read** (not returned) |
| `wearable_readings.created_at`, `clinical_reports.reported_at` | Yes | Only internally for ordering |
| **[PR #5]** `risk_assessments.baseline_high_streak_days`, `instability_seen_in_streak` | Yes | Read by `decide_alert()` |

### 1e. Config, environment variables and model files

| Item | Status |
|---|---|
| `DATABASE_URL` (`database.py:18`), `VITE_API_URL` (`client.js:1`) | Used |
| `VITE_USE_MOCK` | Used only for mock mode; undocumented in `.env.example` |
| `models/scenario_classifier_clinical_only.joblib`, `severity_regressor_clinical_only.joblib` | **Unused by the app** (Zigong scripts only) |
| `models/risk_scorer_xgb.joblib` | **Unused by the app** (secondary model, by design) |
| `data/synthetic/patients.csv`, `wearable_trends.csv` | Not read at API runtime (training and scripts); `reference_stats.yaml` is |
| Hardcoded paths `SCENARIOS_DIR=/workspace/scenarios/api` (`services.py:34`), `DEFAULT_OUTPUT_DIR` (`projection.py:22`) | Work only inside the container; a host run writes to `<drive>:\workspace` (audit §3 #11) |

---

## Table 2: Claims versus reality

| # | Claim (quoted) | Source | Verdict | Evidence |
|---|---|---|---|---|
| 1 | "deployed as a stateful service with day-to-day continuity of engine state" | `paper/main.tex:75` (origin/main) | **Not true in the app** | Routes call only the from-scratch `services.run_assessment_pipeline` (`routes.py:94`); verified live with real Pulse, 0 `pulse_states` (audit §3b). True only in scripts. |
| 2 | "a physiological digital twin … that … carries simulated state from day to day" | `paper/main.tex:677` | **True only in scripts** | Same as #1. The Fig. caption's "continuous-state mode" (`:139`) is accurate only if described as a separate, script-driven mode. |
| 3 | "The FastAPI service exposes eight endpoints over five tables" | `paper/main.tex:289`; README:75-77 ("5 SQLAlchemy tables … 8 endpoints"); README:293 ("7 endpoints") | **Not true (stale)** | 9 routes (`grep -c @router.` = 9) and 6 tables (`pulse_states`). |
| 4 | "Missing EF or NT-proBNP defaults to a documented healthy value … always flagged" | `paper/main.tex:289` | **Partly true** | Flag stored (`routes.py:51-60`), but not returned in the assessment payload or shown in the UI (1b). |
| 5 | "detect early signs of heart failure decompensation … days before symptoms would otherwise prompt a hospital visit" | README:7-10 | **Not true (unvalidated)** | `claims_methodology.md:132`: trend detection "remains untested" on real patients. Outcome AUCs are 0.517–0.596 (`claims_methodology.md:119-125`). |
| 6 | "Personalized Digital Twin" / "personalized to an individual patient's clinical baseline (EF, NT-proBNP, demographics) and driven forward by their own rolling wearable trend" | README:5; methodology.md:39-41 | **Partly true** | Demographics, EF and severity drive Pulse. NT-proBNP only feeds the classifier and NYHA. Wearables act only via the classifier's severity. BCG and HR-baseline personalisation are script-only (1a). With EF defaulted, P2/P3 got a near-normal heart (audit §3b). |
| 7 | "Wearable data … accumulates to a 21-day window before BackgroundTasks triggers one assessment pipeline (ML Model 1 → Pulse → risk scoring → staging → projection)" | README:79-84 | **True in the app** | `routes.py:86-94`, `services.py:189-360`; verified live (audit §3b). Also true: every reading after day 21 retriggers a full from-scratch run (audit §2.4). |
| 8 | "`risk_caveats` surfaces the §6.1 fluid_overload finding directly in API responses" | README:83 | **True in the app** | `services.py:95-110`; EF-fallback variant verified live (P3, audit §3b). |
| 9 | Phase 3 "92% test accuracy … MAE 0.048" | README:57-60 | **Not true (stale)** | methodology.md:240-252 supersedes it: 90.7%, MAE 0.047. True only in the training script. |
| 10 | "pytest tests/ -v # 137 tests" | README:147, :327 | **Not true (stale)** | 255 collected on `results-v1`, 281 on `origin/main`. |
| 11 | Projection one-liner `project_physiology(..., deterioration_rate_per_day=0.03)` | README:189-195 | **Not true** (command fails) | Signature is `(patient, scenario_type, current_severity, composite_rate, …)` (`projection.py:100-108`). |
| 12 | Run the API in raw `kitware/pulse:4.3.1` with `pip3 install -r requirements.txt` | README:205-208 | **Not true** since the version pins | Pins don't install on that image's Python 3.9 (`docs/integration_pre_results.md` §10.3). |
| 13 | "Phase 4 … `src/simulation_features.py`" | README:61-62 | **Not true** (wrong path) | It's `src/analytics/simulation_features.py`. |
| 14 | "Every number used in `src/data_synthesis/`, `src/rules.py`, or later ML/analytics code must trace back to a row here. No magic numbers in code." | data_provenance.md:3-5 | **Partly true** | Risk-bucket boundaries 0.35/0.65 (`risk_score.py:74-75`), `STABLE_SEVERITY_CAP` 0.15 (`generate_patients.py:45`), `CONFIDENCE_BY_STATUS` 0.3/0.5/0.8, `MIN_CONFIDENCE_FOR_ALERT` 0.5, crash range 0.6–0.85 (`runner.py:123`) and **[PR #5]** `C3_STREAK_THRESHOLD_DAYS` are not in the table (documented only in code docstrings as unvalidated). Three rows are still TODO (`data_provenance.md:83-85`). |
| 15 | "Healthy control EF mean 62% … still assumed_default" | data_provenance.md:72 | **True** (honestly flagged) | It's also the value that masks P2/P3 (Gap G3). |
| 16 | Hysteresis / categorical persistence "added" | methodology.md:1754-1760, :1834-1840 | **True only in tests** | Never called by the API (1a). |
| 17 | Score production and alert decision "architecturally separate" | methodology.md:1702 | **True in code, not shown in the app** | `alert_decision()` reaches the API via `score_provenance`, but no component reads it. **[PR #5]** `decide_alert()` is shown in the hero card. |
| 18 | Claims 1–4 in `claims_methodology.md` (BCG CO gap, synthetic trend detection, outcome AUCs, Zigong-native AUC 0.667) | claims_methodology.md:12-166 | **True only in scripts**, accurately scoped | That doc itself states script-only status and limits. Two items were not re-verified by its author (MIMIC, BCG re-run, `:182-184`). |
| 19 | "Clinical reference values are grounded in real data, not assumptions" | README:337-342 | **Partly true** | Most are; assumed defaults remain (EF 62, BNP fallback 100, wearable baselines, `SD_RATE_TO_RISK_SCORE_PER_DAY`), all flagged in `data_provenance.md`. |
| 20 | CI badge: "pytest + frontend build on every push/PR" | README:3, :332 | **True** | `.github/workflows/ci.yml` (pytest + `npm ci && npm run build`); no Pulse in CI. |

No slides or separate abstract are in the repo. The paper draft (`paper/main.tex`, origin/main only) is the closest thing, and its abstract is covered by rows 1–4.

---

## Table 3: Remaining gaps

| # | Gap | What is missing | Why it matters | Effort | Needs team or professor decision? |
|---|---|---|---|---|---|
| G1 | Continuous state sync not in the API | No route, scheduler or flag calls `run_daily_continuous_pipeline`. There's also no **recovery/reset rule**: what to do after a failed day (it silently resumes from the last good state, `continuous_state_pipeline.py:160-169`), after a gap in readings, when a new EF arrives mid-stream, or when state drifts. Day-2+ deltas measure a different quantity than the from-scratch calibration (`:30-39`). | The paper (Table 2 #1–2) claims a stateful service. Wiring it without a reset rule risks compounding drift and silent recovery from stale state. | Wiring: half a day. Reset rule plus a re-check of risk-score semantics on resumed days: more than a day. | **Yes.** Either wire it with a reset rule, or reword the paper to "script-driven continuous mode". |
| G2 | Alert logic | `results-v1`: two alert systems, neither shown (`risk_bucket` drives the UI; `alert_decision()` unseen). **[PR #5]**: one `decide_alert()`. When Pulse runs fine it ignores the ML severity (HIGH→ALERT unless C3→WATCH, MODERATE→WATCH, LOW→NONE); the hero card uses it. `score_provenance.alert` is still returned. **Open question:** return both the twin alert and the ML-severity signal side by side? Live, P3 (fluid_overload, severity 0.665, EF defaulted) gets **NONE** from `decide_alert()` but `alert` from the old logic (audit §3b). | The sickest-by-classifier patients can show green/NONE. Two contradictory `alert` values in one payload. | Showing both signals: half a day. Removing the legacy field: under 1 hour. | **Yes:** which signal is authoritative, and whether to show both. |
| G3 | Missing-EF warning only for fluid_overload | `build_risk_caveats()` emits the EF-fallback caveat only if `scenario_type == fluid_overload and risk_bucket == LOW` (`services.py:101-106`). P2 (deconditioning, EF blank, severity 0.727) showed a green LOW badge with no warning (audit §3b). `ef_is_fallback` isn't returned to the UI. | A defaulted EF changes both classification and simulation; users see a healthy-looking result. | Generic "EF not measured" badge plus payload field: under 1 hour to half a day. | Partly: wording, and whether to suppress the risk badge when EF is defaulted. |
| G4 | Risk score fixed by EF for EF ≤ 40; flat projections | Risk is `max(acute, baseline_deficit)` and the baseline term dominates. P1 (EF 30) scored **0.4874 on days 21/22/23 and at all three horizons** while severity moved 0.556–0.668 (audit §3b). The team's own note: "WATCH is effectively always on for EF<=40 patients" (`docs/unified_alert_evaluation.md:92-96`, origin/main). | Wearable trends barely move the headline score for HFrEF patients, so projections look flat. This undermines "early detection" for the main target group. | Diagnosis: half a day. Re-design or re-weighting: more than a day. | **Yes:** scoring design. |
| G5 | Hero banner and "Pulse Pressure" label | `risk_caveats \|\|` shadows every risk warning (`HeroStatusCard.jsx:20`; still true after [PR #5]). The LV pressure amplitude is labelled "Pulse Pressure" (1c). | The urgency text is never shown; there's a physiologically wrong label in the UI and in the downloadable report. | Under 1 hour each. | No. |
| G6 | Old databases crash on missing columns; no migrations | `results-v1`: `create_all()` never adds columns; an old SQLite DB gives `GET /patients` 500 (`no such column: patients.label`, audit §3 #2). **[PR #5]** adds `add_missing_columns()` (`database.py`, nullable columns only); still no migration tool (Alembic), and NOT NULL or renamed columns are unsupported. | A long-lived or demo DB breaks on upgrade. | Fixed for nullable columns by [PR #5]. Alembic: half a day. | No. |
| G7 | Docker image build fails on some networks | `backend/Dockerfile:52` `pip install` has no timeout or retry settings. On this machine the root cause was **Avast HTTPS scanning** (TLS interception → `CERTIFICATE_VERIFY_FAILED`, hash mismatches), not just slowness (audit §2.1). `xgboost==3.2.0` pulls a 351 MB `nvidia_nccl_cu12` into a CPU-only image. | Anyone on a filtered or slow network can't build the demo. | `PIP_DEFAULT_TIMEOUT`/`PIP_RETRIES` plus a troubleshooting note: under 1 hour. Dropping the CUDA dependency: half a day (needs a re-check of model loading). | No. |
| G8 | Demo patients missing from the demo database | `docs/integration_pre_results.md:63-64`: the referenced demo patients don't exist in the DB. There's no seed script on `main`; `scripts/demo_seed_continuous.py` exists only on unmerged `copilot/vscode-mtl4oaya-kb8l` (2026-09-03) and depends on the unwired continuous pipeline. Labels need manual SQL. A fresh Compose DB starts empty (it did on 2026-10-06). | The demo needs 3–5 pre-run patients (each about 8 minutes of Pulse; RAM-heavy, audit §3b #5). | A seed script via the API with labels: half a day. | Partly: which patient stories to show. |
| G9 | Tests | 255 tests (`results-v1`; 281 on origin/main) cover analytics, scoring, the API with **Pulse mocked** (`test_api.py`, `test_projection.py`, `test_pulse_preflight.py`, `test_continuous_state_pipeline.py` use mocks), the builder, synthesis and the classifier. **No tests for:** the frontend (no test runner in `package.json`), end-to-end with real Pulse, CI running Pulse (`ci.yml` has no Docker or Pulse job), the Windows run path (`docker_smoke_test.sh` is macOS-only: `date -v`). | Every UI bug in Table 1c was found by hand. Pulse regressions (e.g. EF-fallback masking) aren't caught. | Frontend smoke tests: half a day. Real-Pulse CI job: more than a day (about 8 minutes per patient). | Partly: whether CI time for Pulse is acceptable. |
| G10 | Results-plan items | **PerHeart exclusion reasons and flow diagram:** only coarse counts ("11 excluded: < 21 overlapping real days"; "3 excluded: Pulse engine crash (user 6, 18, 22)"), in a figure that exists only on unmerged `analysis/results-v1-offline` (`remaining_items.py:192-216`); no per-patient reason table. **Physiological plausibility:** HR only (`remaining_items.json` `reference_range_check`; MAP/CO/SV "not computed", no reference ranges), on the same branch. **Severity sweep:** only a post-hoc Spearman on the existing batch (`dose_response_spearman`), no controlled per-scenario sweep through Pulse. **Projection examples:** none found on any branch. | These are the results-section evidence for engine plausibility and the projection feature. | Merge the offline branch: under 1 hour. Per-patient exclusion table: under 1 hour. Plausibility with MAP/CO/SV ranges: half a day. Controlled severity sweep: more than a day (Pulse time). Projection examples: half a day. | Yes: reference ranges for MAP/CO/SV need to be chosen and cited. |
| G11 | Open branches and PRs not merged | **`analysis/results-v1-offline`** (4 commits): `docs/results_v1_offline_analyses.md`, `results/results_v1_offline/*` (ML metrics, weight sensitivity, MIMIC age baseline, API timing, reference ranges, dose-response, R², LOSO, flow diagram), `src/evaluation/results_v1_offline/*`. **`feature/scenario-testing`**: `results/scenario_tests/RESULTS.md`, `alert_fix_*`, `protocol_amendments.md`, `scorer_diagnosis.md`, `expected_outcomes.md`, posthoc JSONs, `config/scenario_tests/cohort.yaml`, which **the paper on main cites** (pre-registered cohort, `main.tex:458`). **`copilot/vscode-mtl4oaya-kb8l`**: `scripts/demo_seed_continuous.py`. Fully contained in main, safe to delete: `fix/unified-alert-decision`, `fix/unstable-alert-fallback`, `feature/real-outcome-validation`, `integrate/pre-results`, `feature/continuous-state-sync`. Stale: `copilot/fix-backend-tests` (July; commits `.pyc` files). | The paper's results rest on files not on `main`. | Merging the two results branches: under 1 hour each (docs and results only). | Yes: the team agrees what goes into the frozen results. |
| G12 | Shown-but-not-real UI items | "Run New Simulation" only refreshes; the "HIPAA-audited env" footer; the "7-Day Trend" header; "Classified from wearable input"; sidebar "pending" vs Reports "failed"; a raw traceback on screen (1c). | Misleading in a demo or viva. | Under 1 hour total. | No (except whether to keep the HIPAA wording at all: remove). |
| G13 | Stale docs | README endpoint/table/test counts, accuracy, the projection command, raw-image run instructions, the `simulation_features.py` path (Table 2 #3, #9–13); `continuous_state_pipeline.py:3-5` "nothing currently calls into this module" vs the paper's claim. | Reviewers check the README first. | Under 1 hour. | No. |

---

## Prioritised list

### Must fix before a demo
1. **G8: Seed demo patients** through the API (one at a time, apps closed, about 8 minutes each) and set labels; otherwise the dashboard is empty.
2. **G12: Remove or fix the misleading UI text:** the HIPAA footer, "Run New Simulation", "7-Day Trend", "Classified from wearable input", the raw traceback, and pending vs failed.
3. **G5: Restore the hero risk warning** (put the ECG disclaimer in the waveform panel only) and fix the "Pulse Pressure" label.
4. **G3: Show an "EF not measured" warning for every scenario.** Avoid demoing an EF-blank patient until then (it shows a green LOW).
5. **G2:** decide which alert the hero card shows, and avoid a patient where the two disagree (e.g. EF-blank fluid_overload).
6. **G7:** build on a network without TLS interception (disable Avast HTTPS scanning while building), or add pip timeout and retries.

### Must fix or state before a paper
1. **G1 / Table 2 #1–2:** either wire continuous sync into the API with a reset rule, or reword "deployed as a stateful service with day-to-day continuity" to "script-driven continuous mode, not used by the deployed service".
2. **G4:** state explicitly that the risk score is EF-dominated for EF ≤ 40 and that projections are flat in risk (only severity moves). Ideally diagnose further.
3. **G2:** state that `decide_alert()` ignores the ML severity when Pulse runs fine, and report the P3-type case (EF-defaulted fluid_overload → NONE).
4. **G11:** merge `analysis/results-v1-offline` and `feature/scenario-testing` results into `main` (the paper cites them).
5. **G10:** a per-patient PerHeart exclusion table, plausibility for MAP/CO/SV with cited ranges, and projection examples. If the severity sweep isn't done, say so.
6. **Table 2 #3, #4, #14:** correct the endpoint/table counts, the "always flagged" wording, and either add the alert thresholds to `data_provenance.md` or soften "no magic numbers".

### Can wait
1. **G6:** Alembic migrations (PR #5's guard covers the current nullable columns).
2. **G9:** frontend tests, a real-Pulse CI job, a cross-platform smoke test.
3. **G13:** README cleanup (do it with the paper fixes if time allows).
4. Wire hysteresis/persistence (1a) once there are multi-day assessments (depends on G1).
5. Remove dead code (`sdk_runner.py`, `PatientNotFoundError`, the prototype files) and delete fully merged branches.
6. Drop the CUDA dependency from the CPU image (G7, size and build time).
