# App integration audit: what is actually wired into the live app

Audit date: 2026-10-05. Read-only: no code, config, model or data was changed. This file is the only thing added to the repo.

## 0. Which code was audited (read this first)

There are three different "versions of the app", and they disagree:

| Ref | What it contains |
|---|---|
| **Local checkout** (`experiment/calibration-pilot`, this folder) | Continuous-sync + real-outcome-validation work, but **none of the dashboard fixes** (they exist only on `origin/main`). The STATUS column is still present (`frontend/src/components/vitals/VitalsTable.jsx:16`), the ECG is still captioned "ECG (Lead III, simulated)" (`CardiacWaveformPanel.jsx:51`), there's no patient search, and there's no `build_risk_caveats`. |
| **`origin/main`** (8efd1f3) | Dashboard fixes only; no continuous sync, no score reporting. |
| **`results-rc1` tag = `origin/integrate/pre-results`** (63ba6b4, 2026-10-02) | The merge of main, `fix/unstable-alert-fallback`, `feature/real-outcome-validation` and continuous-state-sync. `origin/feature/scenario-testing` is built on top of it with **zero diff** in `src/api`, `src/analytics`, `frontend`, `backend` and `requirements.txt`. |

**The audit target is `results-rc1`**, since it's the only ref containing every feature on the list. None of `integrate/pre-results`, `fix/unstable-alert-fallback` or `feature/scenario-testing` existed in this clone's refs. They were fetched into a separate scratch repo (the project's `.git` was not touched). All `file:line` references below are to `results-rc1` unless marked "local".

The common chain for everything below:

```
Simulation Lab wizard  frontend/src/components/lab/SimulationLabPage.jsx:76-108 (createPatient -> createClinicalReport -> 21x syncWearableReading)
  -> frontend/src/api/client.js:28,52,60   POST /patients, /clinical-report, /wearable-sync
  -> src/api/routes.py:27, 41-64, 67-99    (21st reading: background_tasks.add_task(services.run_assessment_pipeline) at :94)
  -> src/api/services.py:189-360           _run_assessment_pipeline()
Dashboard read path:
  usePatientReport.js:20 -> client.js:36 GET /report -> routes.py:232-238 -> _build_status() routes.py:125-198 + get_projection() :220-229
  AppShell.jsx:24-90 renders HeroStatusCard, CurrentConditionPanel, VitalsTable, CardiacWaveformPanel, ForwardProjectionPanel, DoctorReportCard
Other tabs: Trends (useTrends.js:23 -> /history + /wearable-history), Reports (usePatients.js:22-33 -> /patients + /report per patient), Lab internals (/report)
```

`GET /patients/{id}/status` (`client.js:40`) and `GET /patients/{id}/projection` exist as routes, but no component calls them directly. Both are only consumed via `/report`.

---

## 1. Summary table

| # | Feature | Status | Evidence | What's missing to make it LIVE |
|---|---|---|---|---|
| 1 | Core pipeline: wearable sync → classifier + severity → Pulse → risk score → dashboard | **LIVE** (code path); **Pulse half not observed live on this machine** | `routes.py:94` → `services.py:244-248` (clf/reg) → `:282` `run_pulse_with_preflight` → `:298` `compute_risk_score` → `:339` RiskAssessment → `routes.py:185` → `HeroStatusCard.jsx:17,32` | Nothing in code. Live smoke test reached the classifier and the Pulse call; Pulse itself was unavailable (see §2). |
| 2 | EF/BNP input + EF fallback + EF-fallback caveat | Input & fallback: **LIVE**. Caveat: **LIVE but narrowly reachable** | Wizard fields `SimulationLabPage.jsx:133-134,86-89` → `routes.py:51-60` `apply_tier1_fallback` (`services.py:122-140`) → stored flag reused `services.py:214-216` → `build_risk_caveats` `services.py:95-110,337` → `HeroStatusCard.jsx:20,59`, `DoctorReportCard.jsx:44` | Caveat appears **only** when `scenario_type == fluid_overload` **and** `risk_bucket == LOW` (`services.py:103`). Omitting EF for any other scenario/bucket produces no EF caveat. The dashboard also never shows that EF *was* defaulted: `ef_is_fallback` isn't in `RiskAssessmentPayload` (`schemas.py:116-185`), and `CurrentConditionPanel.jsx:70` shows the 62% default as if measured. |
| 3 | `baseline_deficit_score` (fluid_overload fix) | **LIVE** (Simulation Lab tab only) | `risk_score.py:105-150` (`max(acute, baseline)`) → `services.py:346-347` → `schemas.py:122-135` → `SimulationLabPage.jsx:228-235` (shown only when `dominant_mechanism == 'baseline'`) | Not shown on the main Patient Dashboard; only in the Lab tab's "Simulation Internals". |
| 4 | Unstable/failed-run classifier fallback alert | **BACKEND-ONLY** | `routes.py:140-179` builds `current_alert` via `build_score_report` (classifier_only); `models.py:148-167` `score_provenance`. **Verified live** (§2): `current_alert.alert = "alert"`, `alert_basis = "classifier_only"`. | **Chain breaks at the frontend:** no component reads `current_alert`, `latest_assessment_stale`, `score_provenance` or `alert` (grep of `frontend/src`: 0 hits outside a comment in `AppShell.jsx:39`). On a failed run the dashboard shows only `SimulationFailedState.jsx`, which says "No risk assessment is shown" (`:9-10`), so the alert that was computed is never shown. |
| 5 | ECG reference-template caveat (`build_risk_caveats`) | **LIVE** | `services.py:74-79,95-110` (shared by `continuous_state_pipeline.py:63,334`) → `risk_caveats` → `HeroStatusCard.jsx:20,59`, `DoctorReportCard.jsx:44`; panel copy `CardiacWaveformPanel.jsx:24-34,65-75` | Only produced for **completed** runs (not observed live, §2). Side effect: because `risk_caveats` is now always non-empty, the hero banner **always** shows the ECG caveat and never the risk-level warning (`HeroStatusCard.jsx:10-14,20`). The HIGH-risk "seek clinical evaluation promptly" text is effectively dead. |
| 6 | 7/14/30-day projections (`compute_projection`) | **LIVE** | `services.py:316-335` `project_physiology(horizons=DEFAULT_HORIZONS_DAYS)` → `projection_json` → `routes.py:220-229` → `/report.projection` → `ForwardProjectionPanel.jsx:5,46-53,78-89` | `compute_projection` itself is a **parameter** of `run_daily_continuous_pipeline` (`continuous_state_pipeline.py:144,304-332`), not a function, so it's only reachable from scripts. The projections the dashboard shows come from `services.py`. |
| 7 | Continuous state sync (`run_daily_continuous_pipeline`, `PulseState`) | **SCRIPT-ONLY** | Defined `continuous_state_pipeline.py:143-360`; imported only by `scripts/verify_continuous_state_pipeline.py`, `scripts/verify_continuous_state_live_14day.py`, `tests/test_continuous_state_pipeline.py`. Its own docstring says "nothing currently calls into this module. Not wired into any route yet" (`:3-5`). | **Chain breaks at `routes.py:94`**: every reading ≥21 calls `services.run_assessment_pipeline` (from scratch). There's no route, scheduler or flag that calls `run_daily_continuous_pipeline`, and `PulseState` isn't exposed by any endpoint. **Verified live** (§2.4): days 22 and 23 created fresh runs; `pulse_states` stayed at 0 rows. |
| 8 | BCG modifiers (`bcg_to_cardiovascular_modifiers`) | **SCRIPT-ONLY** | Defined `patient_file.py:200`; consumed through `build_scenario_file(..., extra_modifiers=...)` (`scenario_file.py:151-162`, "None for every synthetic-patient call site"). Callers: `scripts/bcg_*`, `scripts/synthetic_deterioration_pulse_check.py`. | `services.py:268-273` never passes `extra_modifiers`. There's no BCG field in any schema, route or the wizard. |
| 9a | MAGGIC score | **SCRIPT-ONLY** | `benchmark_scores.py:133` `compute_maggic_score`; callers `scripts/benchmark_comparison.py`, `scripts/zigong_maggic11_validation.py`, tests | No import from `src/api`. |
| 9b | Outcome calibration | **SCRIPT-ONLY** (types only) | `outcome_calibration.py:1-19` ("FOUNDATION ONLY … DELIBERATELY NOT POPULATED"), dataclasses `:38-74`; imported only by `tests/test_outcome_calibration.py` | Nothing to wire yet, by design. |
| 9c | `score_reporting` / `score_provenance` | **BACKEND-ONLY** | `build_score_report` `score_reporting.py:195-233` used by `models.py:148-167` (`score_provenance` property → `RiskAssessmentPayload.score_provenance`, `schemas.py:152-181`) and `routes.py:169-177` (`current_alert`). `severity_band` `models.py:142-146`. `hysteresis_alert_states` / `scenario_type_persistence` (`:254,345`) are used only by tests. | Returned in every `/report`, `/status` and `/history` payload, but the frontend reads none of `score_provenance`, `severity_band`, `current_alert` or `confidence`. |
| 10 | `deterioration_rate` / `days_to_next_stage` | **LIVE** | `services.py:313-314` → `models.py:117-118` → `ForwardProjectionPanel.jsx:35-44,94-97` ("Projected time to next risk tier", "at ceiling"/"stable"); `DoctorReportCard.jsx:40-41`; `vital_slopes` → `VitalsTable.jsx:22-29`, `CurrentConditionPanel.jsx:80` | Only after a completed run. |
| 11 | NYHA class | **LIVE** | `staging.py:32-57` → `services.py:306-312` → `HeroStatusCard.jsx:35`, `DoctorReportCard.jsx:28`, `TrendsHistoryPage.jsx:70` | Only after a completed run. |
| 12 | `alert_decision()` vs `risk_bucket == "HIGH"` | **Dashboard uses `risk_bucket` only**; `alert_decision()` is BACKEND-ONLY | `alert_decision` `score_reporting.py:152-182` → only via `build_score_report` → never read by the frontend. `risk_bucket` drives: `HeroStatusCard.jsx:17-19,32,39` (badge, red "risk-high" card, "clinical follow-up recommended today"), `Sidebar.jsx:13-15`, `ReportsPage.jsx:10,28`, `ForwardProjectionPanel.jsx:42,44,77,86`, `TrendsHistoryPage.jsx:52,67,102`, `SimulationLabPage.jsx:210,225`, `DoctorReportCard.jsx:27` | The two can disagree, and the dashboard shows only one of them (see §3.2). |
| 13a | Vitals STATUS column removed | **LIVE** (rc1/main only) | `VitalsTable.jsx:12-16` (rc1: Metric / Today's Input / 7-Day Trend) | **Missing in the local checkout** (`VitalsTable.jsx:16` local still has `<th>Status</th>`). |
| 13b | ECG relabelled as reference template | **LIVE** (rc1/main only) | `CardiacWaveformPanel.jsx:24-25,65,72-75`; `DoctorReportCard.jsx:13-14` | Local checkout still says "simulated". The hero card's animated `EcgWave.jsx` is a hard-coded decorative SVG path (`:4-27`) with no label. That's not a data claim, but it looks like a live trace. |
| 13c | Patient label | **Partially LIVE** (sidebar only) | `models.py:39`, `schemas.py:34` → `Sidebar.jsx:87` (`p.label \|\| avatar.label`) | Not settable via the API (`PatientCreate`, `schemas.py:18-22`, has no `label`; only via manual SQL per the `models.py:34-38` comment). Hero, Trends, Reports and Lab ignore it and use `avatarFromId().label` (`AppShell.jsx:34`, `TrendsHistoryPage.jsx:99`, `ReportsPage.jsx:19,66`, `SimulationLabPage.jsx:198`). So the sidebar can say "Demo – Cardiac Stress" while the page header says "Patient #AB12". |
| 13d | Patient search | **LIVE** (rc1/main only) | `Sidebar.jsx:20-34,67-78` (ID, `#XXXX`, label) | Local checkout has no search. |
| 13e | "Pulse Pressure" label | **Still mislabelled** | `CardiacWaveformPanel.jsx:15-19,89-90` and `DoctorReportCard.jsx:8-10,16` compute `max(p) − min(p)` over `pv_loop.pressure_mmhg`, which is the **left-ventricular** pressure column (`simulation_features.py:101-102`, `left_heart_pressure`) | LV pressure falls to near-zero in diastole, so this is LV systolic − LV end-diastolic pressure (≈ peak LV pressure), not arterial pulse pressure (systolic − diastolic arterial, typically ~40 mmHg). No commit on any ref touches this label. |

---

## 2. Live smoke test

### 2.1 How it was run, and what could not be run

- **Code:** `results-rc1` exported with `git archive` into a scratch directory outside the repo. Models: `artifacts/results-v1/models/*.joblib`, SHA-256 `2157cb21…f79f0e` and `4b7afeab…f0e`, matching `docs/integration_pre_results.md:338-341`. Note that doc's hashes are printed one hex character short (63 chars).
- **Backend image (the project's normal method): could not be built on this machine.** `docker build -f backend/Dockerfile` failed in the `pip install -r requirements.txt` layer three times. Attempt 1 hit `ReadTimeoutError` (files.pythonhosted.org). Attempts 2–3 used a scratch copy of the Dockerfile with only `ENV PIP_DEFAULT_TIMEOUT=600 PIP_RETRIES=20` added. Both failed with `THESE PACKAGES DO NOT MATCH THE HASHES` (expected `99b4a6bb…312c`, got a different value each time) during the 351.5 MB `nvidia_nccl_cu12` download that `xgboost==3.2.0` pulls in on Linux. During this period `curl` to github.com, npmjs, pypi and Docker Hub also returned connection resets. **Root cause (confirmed 2026-10-06): Avast Antivirus "Web Shield" HTTPS scanning on this PC.** pypi.org, files.pythonhosted.org and github.com are all served with a certificate issued by `CN=Avast Web/Mail Shield Root … generated by Avast Antivirus for SSL/TLS scanning`. Windows tools trust it; the Linux build container doesn't (a later Compose build failed outright with `SSL: CERTIFICATE_VERIFY_FAILED – unable to get local issuer certificate`). The interception is also the likely cause of the earlier connection resets and hash mismatches on the large wheel. This is not a project defect. Disable Avast's HTTPS scanning while building. (Drive C: being nearly full was a separate issue, and Docker's data disk is on D:.) No image other than `kitware/pulse:4.3.1` was left behind.
- **Fallback actually used:** the same `results-rc1` code run on the host (`uvicorn src.api.main:app --port 8010`) using the project's existing `venv` (Python 3.13, scikit-learn 1.9.0, numpy 2.5.1, pandas 3.0.3, xgboost 3.3.0; sklearn matches the pin, the others are minor-version off), with `DATABASE_URL` pointing at a fresh scratch SQLite file. `PulseScenarioDriver` only exists inside the Pulse image, so **every run ends at the documented `failed` state** (`FileNotFoundError: [WinError 2]`, `services.py:282`). This exercises everything up to the Pulse call plus the failed-run alert path. **It does not exercise** risk score, risk bucket, NYHA, caveats, projections or waveform data. Those were never produced, so they are **not observed live** and their status above rests on the static trace.
- **Inputs exactly as the frontend sends them:** POST /patients → POST /clinical-report → 21 sequential POST /wearable-sync. Readings were generated by the frontend's own `generateTrend()` (`frontend/src/utils/syntheticTrend.js`), executed with Node.
- No running job was touched. There were no containers or app processes running at the start, and the audit used ports 8010/8011/4178, not 8000/3000/5173.

### 2.2 Results (all three patients: age 68, Male, 172 cm, 82 kg)

| | P1: EF 30, BNP 2500, "Mild Decline" preset | P2: **EF omitted**, BNP 2500, "Mild Decline" | P3: **EF omitted**, BNP 2500, weight-gain-dominant custom trend |
|---|---|---|---|
| patient_id | `18992683-…6ab6` | `0122bd8b-…89f0` | `5104214d-…b677` |
| clinical-report stored | EF 30.0, BNP 2500, `ef_is_fallback=false` | **EF 62.0, `ef_is_fallback=true`** | **EF 62.0, `ef_is_fallback=true`** |
| sync #20 / #21 | `collecting:20` / `simulation_triggered:21` | same | same |
| scenario_type (SimulationRun) | deconditioning | deconditioning | **fluid_overload** |
| severity | 0.6208 | 0.7510 | 0.6403 |
| simulation_status | `failed` | `failed` | `failed` |
| latest_assessment | `null` | `null` | `null` |
| risk_score / risk_bucket / NYHA / caveats / waveform | not produced (no RiskAssessment row) | same | same |
| projection | `{"available": false, "horizons": null}` | same | same |
| history | 0 assessments | 0 | 0 |
| **current_alert** | `alert`, `alert_basis=classifier_only`, `source=classifier_only`, `simulation_status=unstable`, `confidence=0.3`, `severity_band=exceeds_stable_range`, `threshold_clinically_validated=false` | same shape, `alert` | same shape, `alert` |
| error_message | `FileNotFoundError: [WinError 2] …` + traceback | same | same |

**Step 5 (EF omitted → EF fallback caveat):** The fallback itself works: EF was defaulted to 62% and flagged. The **caveat did not appear**, because it only exists on a completed RiskAssessment, and none was produced here. P3 *was* classified `fluid_overload`, the one scenario where the EF-fallback caveat can fire, so with a working Pulse this patient would show that caveat if its risk bucket came out LOW. **Not verified live.**

### 2.3 Frontend

- `npm ci && npm run build` (vite 5.4.21) on `results-rc1/frontend`: **build succeeds** (64 modules, `index-*.js` 249 kB / 77 kB gzip). `npm run lint` (oxlint) could not run on this machine: `Cannot find module '@oxlint/binding-win32-x64-msvc'`, which looks like a Node 22.11 vs required `>=22.12` engine mismatch.
- **Browser check (done 2026-10-06, Chrome on this Windows machine, built dashboard served at `localhost:4178` against the scratch API on :8010).** A first attempt failed because the only connected Chrome was on a different (macOS) computer, whose `localhost` is not this machine. What the real browser showed for the three test patients:
  - **Patient Dashboard:** "Simulation failed … No risk assessment is shown below", followed by the **full raw Python traceback** (`FileNotFoundError: [WinError 2] …`, file paths, `subprocess.py` frames) printed in the UI. The page text contains no "alert", "severity", "scenario" or "classifier", so the backend's `current_alert = alert` is not visible anywhere. The top bar says "Last simulation: never".
  - **Sidebar:** all three patients show "68 yrs · **pending**". **Reports tab:** the same three patients show "**failed**", so two tabs disagree about the same state. The report preview says "No completed assessment yet for this patient."
  - **Trends & History:** "No completed assessments yet", plus six wearable charts ("23-day synced history", Sep 14 → Oct 6).
  - **Simulation Lab:** "No completed simulation yet for Patient #5AB6".
  - **Patient search:** typing `b677` filtered the sidebar to Patient #B677 only. Works.
  - Panels that need a completed run (hero/risk badge, NYHA, Current Condition, Vitals table, Cardiac Waveform, Forward Projection, report text) were **not rendered**, since no run completed (Pulse unavailable, §2.1). Their content still rests on the code trace below.

  The API fields each component reads (from the code):

| Component | Fields read | Shown for the test patients (status `failed`) |
|---|---|---|
| `AppShell.jsx` | `status.simulation_status`, `latest_assessment`, `latest_wearable`, `reading_count`, `error_message`, `waveform_data`, `projection.horizons` | `failed` branch (`:64-71`): renders only TopBar + `SimulationFailedState`. **`current_alert` (alert=alert) is never shown.** |
| `HeroStatusCard` | `risk_bucket`, `nyha_class`, `risk_caveats` | not rendered |
| `CurrentConditionPanel` | `scenario_type`, `severity`, `ejection_fraction_pct`, `nt_probnp_pg_ml`, `vital_slopes`, wearable vitals | not rendered (the classifier's scenario/severity exist on the failed SimulationRun but aren't exposed except inside `current_alert`) |
| `VitalsTable` | wearable vitals, `vital_slopes` | not rendered |
| `CardiacWaveformPanel` | `waveform_data.pv_loop`, `.ecg`, `assessment.severity` | not rendered |
| `ForwardProjectionPanel` | `severity`, `risk_bucket`, `days_to_next_stage`, `horizons[7/14/30].projected_severity/.risk_bucket` | not rendered |
| `DoctorReportCard` | `risk_bucket`, `nyha_class`, `scenario_type`, `severity`, EF, BNP, `deterioration_direction`, `days_to_next_stage`, `risk_caveats`, `pv_loop` | not rendered |
| `Sidebar` | `p.label`, `latest_assessment.risk_bucket`, `simulation_status` | "68 yrs · pending". A failed patient is labelled **"pending"** (`Sidebar.jsx:15` only special-cases `collecting`). |
| `ReportsPage` row | `risk_bucket`, `scenario_type`, `simulation_status` | "failed" |
| `TrendsHistoryPage` | `/history` assessments (`risk_score`, `risk_bucket`, `scenario_type`, `severity`, `nyha_class`), `/wearable-history` | "No completed assessments yet" + vitals charts |
| `SimulationLabPage` internals | `scenario_type`, `severity`, `risk_score`, `risk_bucket`, `dominant_mechanism`, `baseline_deficit_score`, `component_scores` | "No completed simulation yet" |

### 2.4 Step 6: two consecutive days (continuous sync or fresh?)

P1 got day 22 (2026-10-05) and day 23 (2026-10-06) through `POST /wearable-sync`. Each returned `202 simulation_triggered` (`reading_count` 22, 23), and each created a **new from-scratch SimulationRun**, re-classified on the shifted 21-day window:

| run id | day | scenario | severity | status |
|---|---|---|---|---|
| 1 | 21 | deconditioning | 0.6208 | failed |
| 4 | 22 | deconditioning | 0.6134 | failed |
| 5 | 23 | deconditioning | 0.6011 | failed |

`pulse_states` rows for P1: **0**. The `scenario.json` written for the patient has top-level keys `PatientConfiguration`, `DataRequestManager`, `AnyAction`, with **no `EngineStateFile` and no `SerializeState`**. So each day **starts fresh** from a newly built patient. This would be the same with a working Pulse: the code path (`routes.py:94` → `services.py`) never loads or saves engine state. Continuous sync is not part of the app.

---

## 3. Broken or inconsistent things found

1. **The local checkout is not the release.** This folder is on `experiment/calibration-pilot` and lacks every dashboard fix, `build_risk_caveats`, the alert-fallback wiring and the frontend pieces listed in 13a–d. Anyone demoing from this folder gets the old dashboard. (`git -c http.sslBackend=schannel fetch` works where plain `git fetch` fails with an SSL certificate error.)
2. **The existing local DB crashes the release code.** Pointing `results-rc1` at a copy of `data/db/m2k_hf_pulse.db` gives `GET /patients` → **HTTP 500** with `sqlite3.OperationalError: no such column: patients.label`. `init_db()` uses `create_all` (`database.py`), which never adds columns to existing tables, and there is no migration. Any long-lived SQLite or Postgres DB created before 2026-09-03 needs `ALTER TABLE patients ADD COLUMN label`.
3. **The computed alert is invisible exactly when it matters.** For a failed or unstable run, the backend computes `current_alert.alert = "alert"` (verified, §2.2), but the dashboard shows only "Simulation failed … No risk assessment is shown" and the sidebar says "pending" (confirmed in a real browser, §2.3). The same page also dumps the raw Python traceback (`AppShell.jsx:68` → `SimulationFailedState.jsx:12-16` renders `error_message` verbatim) to the end user, and the Reports tab says "failed" for the same patients the sidebar calls "pending". The whole point of `fix/unstable-alert-fallback` (alert the sickest, crash-zone patients) doesn't reach the user.
4. **Two alert systems that can disagree; the UI uses only one.** For a completed run, the red "HIGH RISK / clinical follow-up recommended today" styling is driven purely by `risk_bucket` (Pulse risk_score ≥ 0.65). `alert_decision()` is driven by classifier severity > 0.15. A patient can be `risk_bucket=LOW` with `alert="alert"` (e.g. severity 0.6), or HIGH with `no_alert`. Both values are in the payload; the dashboard shows only `risk_bucket`.
5. **The hero warning banner can never show the risk-level warning any more.** `warningText = risk_caveats || GENERIC_WARNING[bucket]` (`HeroStatusCard.jsx:20`), and `risk_caveats` now always contains the ECG caveat, so the HIGH-risk "seek clinical evaluation promptly" text and the LOW "Model confidence is high" text are unreachable. Every patient's red, amber or green banner shows the ECG template disclaimer instead.
6. **The EF fallback is invisible on the dashboard.** `ef_is_fallback` is stored but not returned in `RiskAssessmentPayload`. `CurrentConditionPanel` shows "62% Ejection Fraction" for an unmeasured patient, identical to a measured 62%. The only signal is the fluid_overload-and-LOW caveat.
7. **"Pulse Pressure (mmHg, from loop)" is still LV pressure amplitude**, not arterial pulse pressure (§1, 13e). The same value is in the downloadable report (`DoctorReportCard.jsx:16`).
8. **The patient label is inconsistent across views** and can't be set through the API (§1, 13c).
9. **Reports tab report preview omits the waveform summary.** `ReportsPage.jsx:91-96` doesn't pass `waveformData` to `DoctorReportCard`, so the same patient's report text differs between the Dashboard and Reports tabs.
10. **Docstrings are stale relative to the merge.** `continuous_state_pipeline.py:3-5` still says "nothing currently calls into this module" (true for routes, but `services.py` now shares helpers with it). Its `:22-28` claims the API and frontend display continuous-synced patients "with zero changes", but nothing in the app ever produces such a patient. `TrendsHistoryPage.jsx:10-34` is written around continuous-sync patients that the app can't create.
11. **The `SCENARIOS_DIR` absolute path** (`services.py:34`, `/workspace/scenarios/api`) means a host-run backend writes to `<current drive>:\workspace\…`, outside the repo. The host run in this audit created `C:\workspace\scenarios\api\` for the three test patients. It is unrelated to the project and safe to delete.
12. **The "Mild Decline" preset produces high classifier severities** (0.60–0.75, above the 0.15 stable cap) and an `alert` for all three test patients. That isn't necessarily wrong (the classifier is trained on synthetic data), but the wizard's gentlest non-stable preset going straight to "alert" is worth knowing before a demo.
13. **The backend image is heavy and fragile on a slow link.** `xgboost==3.2.0` on linux/amd64 pulls `nvidia_nccl_cu12` (351.5 MB) into a CPU-only image. That download was the failure point on this machine.

## 3b. Real-Pulse re-run (2026-10-06): the Pulse-dependent checks, now done

After Avast HTTPS scanning was disabled, the backend image built (`docker compose build` from a separate worktree `M2K-HF-PULSE-release` at `origin/main` `f1c8656` = `results-v1` + PR #5 "unified decide_alert()"). Inside the image: scikit-learn 1.9.0, numpy 2.4.6, pandas 3.0.6, xgboost 3.2.0 (exact pins), `/pulse/bin/PulseScenarioDriver` present, model SHA-256 matching `artifacts/results-v1`. The checks ran against a **separate container of that image** (:8010, throwaway SQLite), with a second dashboard on :3010, so the demo stack (:3000/:8000) stayed clean. Inputs were the same as §2.2 (frontend `generateTrend()`). Each patient took about 8 minutes (1 assessment + 3 projection Pulse runs).

| | P1: EF 30, BNP 2500, Mild Decline | P2: EF omitted, Mild Decline | P3: EF omitted, weight-gain trend |
|---|---|---|---|
| scenario / severity | deconditioning / 0.587 | deconditioning / 0.727 | fluid_overload / 0.665 |
| risk_score / bucket | 0.4874 / MODERATE | 0.0654 / **LOW** | 0.0 / **LOW** |
| NYHA | III | II | II |
| dominant mechanism | baseline (baseline_deficit 0.4874) | | baseline_deficit 0.0 |
| `score_provenance.alert` (old) | alert (classifier_and_simulation, conf 0.8, valid) | alert | alert |
| `status.alert` (new unified, PR #5) | **WATCH** (source moderate) | | **NONE** (source risk_scorer) |
| caveats | ECG template only | ECG template only | **EF-fallback fluid_overload caveat + ECG** |
| projections 7/14/30 (severity; risk) | 0.606 / 0.625 / 0.668; risk 0.4874 MODERATE at all three | | |
| days_to_next_stage / direction | 60 / worsening | | |
| waveform | PV loop 50 pts, ECG 149 pts, cycle 0.987 s | | |

**Step 5 verified live:** with EF omitted and a fluid_overload + LOW result (P3), the EF-fallback caveat appears in `risk_caveats`.

**Step 6 verified live:** P1 days 22 and 23 each produced a new, complete from-scratch run (severity 0.611, then 0.556). `pulse_states` = 0 rows for every patient, and the scenario file has `PatientConfiguration` with no `EngineStateFile` or `SerializeState`. **Continuous state sync is not used by the app.**

New findings from the real runs:
1. **The EF fallback hides sick patients behind a green LOW badge.** P2 has a *higher* classifier severity (0.727) than P1 (0.587), but because EF defaulted to 62%, Pulse simulates a near-normal heart → risk 0.065 LOW. P2 is deconditioning, not fluid_overload, so **no caveat warns about it**.
2. **The new unified alert (PR #5) gives NONE for P3**, the exact patient the EF-fallback caveat describes (severity 0.665, far above the stable range; the old `alert_decision()` said `alert`). The unified alert defers to the risk scorer, which the EF fallback has already blinded.
3. **P1's risk_score is 0.4874 on every run** (days 21, 22, 23 and all three projection horizons), even as classifier severity moves (0.587 → 0.611 → 0.556; projected 0.606 → 0.668). The score is entirely `baseline_deficit_score`, set by the fixed EF. Wearable trends don't move the dashboard's risk score for this patient.
4. **`scripts/docker_smoke_test.sh` only runs on macOS** (it uses `date -v`), so it fails on Windows and Linux.
5. **Memory:** each patient's 4 sequential Pulse runs grew Docker's WSL VM to about 3.8 GB on this 16 GB laptop. Create demo patients one at a time.

## 4. Re-running the Pulse-dependent checks

On a machine with working network (or once the backend image exists), from a `results-rc1` checkout with the frozen models copied into `models/`:

```
docker build --platform linux/amd64 -t m2k-hf-pulse-backend -f backend/Dockerfile .
docker run --rm -p 8010:8000 -e DATABASE_URL=sqlite:////tmp/audit.db m2k-hf-pulse-backend
```

Then repeat §2.2–2.4 against :8010. What would still need confirming: `risk_score`, `risk_bucket`, `nyha_class`, `risk_caveats` (ECG caveat always; the EF-fallback caveat for a fluid_overload + LOW + EF-omitted patient like P3), `projection.horizons` 7/14/30, `days_to_next_stage`, `waveform_data`, and `current_alert` on a successful run.
