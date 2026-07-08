# Methodology

Status: skeleton — filled in incrementally as each roadmap phase completes, not written
retroactively before submission. See CLAUDE.md for the decisions already locked (personalization
tiers, scenario taxonomy, dataset strategy, primary risk scorer choice) — this document explains
*why* those decisions were made and how each phase was executed, not what the decisions are.

## 1. Problem Statement

TODO — pull from the presentation script's Slide 2/3 content once finalized (heart failure
readmission problem, monitoring gap between clinic visits).

## 2. Data Sources and Provenance

See `docs/data_provenance.md` for the full parameter-level table. Summary:
- Clinical baselines: synthetic, derived from cited papers + Kaggle datasets (never real patient data)
- Wearable trends: synthetic, 3 modes — `stable`, `deteriorating`, `recovering`
- Simulation dataset: self-generated via Pulse batch runs (Phase 4, done — see §5 and §7)

## 3. Personalization Tier Design and Justification

See CLAUDE.md "Locked Phase 0 Decisions" — Tier 1 (demographics + EF + BNP + wearables) is core,
Tier 2 (echo PPG) optional/stretch, Tier 3 (ECG-derived BP/contractility) permanently cut.
TODO — write the justification narrative once Tier 2 status is decided.

## 4. Pulse Integration Methodology

Phase 2 built `src/patient_builder/` and `src/pulse_runner/` alongside the existing prototype
(`src/generator.py`/`src/run.py`, left untouched). Key findings, from reading Pulse 4.3.1's actual
compiled source inside the Docker image rather than assuming from the planning doc:

- **Pulse's patient file has no direct EF/contractility input.** EF is purely a simulation output.
  Structural reduced systolic function is applied via the binary `ChronicVentricularSystolicDysfunction`
  condition (fixed 0.27x elastance cut, confirmed in `CardiovascularModel::ChronicHeartFailure()`),
  and continuous severity via the `CardiovascularMechanicsModification` action's `Modifiers`
  (`StrokeVolumeMultiplier`, `SystemicResistanceMultiplier`, etc.). See
  `ef_to_cardiovascular_modifiers()` in `src/patient_builder/patient_file.py`.
- **Pulse hard-rejects patients outside age 18–65 or BMI 16.0–30.0** (hardcoded constants in
  `SetupPatient.cpp`, not a config toggle; confirmed further by Pulse's own bundled `Overweight.json`
  sitting at exactly BMI 30.0). Our real-data-grounded population (MIMIC age mean 68.7, NHANES BMI
  often >30) frequently falls outside this. **Decision:** clamp only at the Pulse-input boundary
  (`pulse_eligible_age`/`pulse_eligible_weight_kg`), not in the underlying `patients.csv` — the
  patient's true EF/BNP/severity still drive the simulation; only the simulated body is a proxy for
  patients outside Pulse's native range. See Limitations (§8).
- **Every action must be wrapped in `{"PatientAction": {...}}`** and every condition in a
  `Conditions: {"AnyCondition": [{"PatientCondition": {...}}]}` structure — discovered by reading
  the actual protobuf JSON parse errors (`no such field: 'CardiovascularMechanicsModification'`,
  `unexpected character: '['; expected '{'`), not documented anywhere in the planning materials.
- **`CardiovascularMechanicsModification` needs `"Incremental": true`.** Without it, Pulse silently
  restabilizes after applying the modifiers, consuming simulated time beyond what the scenario's
  `AdvanceTime` actions account for, and Pulse's own internal check ("Simulation time does not
  equal expected end time") then hard-fails with exit code 1.
- **Do not stack the binary condition's fixed cut with a second EF-derived continuous cut.** Doing
  so pushed an EF=26.6 patient into genuine cardiovascular collapse during validation ("Can't
  transport with a negative volume", `IrreversibleState`) — caught correctly by
  `src/pulse_runner/runner.py`'s crash detection. Fixed by having the continuous multiplier
  represent only the *additional acute* severity when the condition is already applied (see
  `ef_to_cardiovascular_modifiers` docstring).
- **`OxygenSaturation` reads as a flat 0.0 in all our runs**, despite the engine internally
  targeting realistic values (~0.976–0.983, visible in the run log) and despite our
  `DataRequestManager` JSON being byte-identical to the prototype's own historically-working
  request (confirmed by testing with Pulse's bundled `StandardMale.json` and the exact original
  4-property request list — still 0). Since the schema is provably correct, the remaining variable
  is that this runs under `arm64` Docker emulation of the `amd64` Pulse image (platform-mismatch
  warning on every invocation) — plausibly an emulation-specific numerical artifact rather than a
  bug in our pipeline. Flagged as an open item; worth re-testing on native `amd64` if available.

## 5. ML Model Design, Training, Evaluation

**Phase 3 (scenario classifier, done).** Two `RandomForest` models
(`src/scenario_classifier/train.py`) share one feature matrix built by
`src/scenario_classifier/features.py`:

- `RandomForestClassifier` → `scenario_type` (5-class: `stable`, `fluid_overload`,
  `cardiac_stress`, `deconditioning`, `acute_deterioration`).
- `RandomForestRegressor` → `severity` (continuous, 0–1).

**Features** (one row per patient, 30 columns total): the clinical snapshot from
`patients.csv` (`age`, `sex`, `bmi`, `ejection_fraction_pct`, `nt_probnp_pg_ml`, `nyha_class` as
an ordinal), plus per-vital wearable-trend aggregates from the 21-day window in
`wearable_trends.csv` — first-7-day mean, last-7-day mean, delta, and linear slope, for each of
`resting_hr_bpm, spo2_pct, weight_kg, steps_per_day, sleep_hours, hrv_rmssd_ms`. This mirrors the
real deployment input (a clinical report + a rolling wearable window), not raw simulation
internals.

**Leakage guard:** `wearable_trends.csv`'s `trend_mode` column is derived directly from the
label and is dropped before feature construction; `scenario_type` is obviously excluded too.
`severity` is a *target*, not a feature — it legitimately drives the wearable deltas and clinical
values during data synthesis (see Phase 1, `generate_patients.py`/`generate_wearable_trends.py`),
so the model is learning to infer it from those measurable downstream effects, not being handed it
directly.

**Split:** patient-level, stratified 70/15/15 train/val/test on `n=2000` patients
(`split_patients()` in `train.py`), so all 5 classes are represented in every fold — an
unstratified 15% slice risks near-empty classes for 5-way evaluation. Random Forest hyperparameters
were left at defaults (`n_estimators=300`, no depth cap) — no tuning harness was built, since the
task didn't call for one.

**Results (held-out test set, 300 patients):** 92.3% scenario accuracy (macro F1 0.92), severity
MAE 0.048 / RMSE 0.063. Full classification report and confusion matrix are written to
`models/phase3_eval_report.txt` on every training run (small text file, committed as evidence;
the `.joblib` model weights and `.png` plots alongside it are gitignored and regenerated with
`python3 -m src.scenario_classifier.train`). Notably, `cardiac_stress` (HFpEF-profile, preserved
EF) and `acute_deterioration` (HFrEF-profile, low EF) — the pair Phase 2's Pulse validation (§4,
`cardiac_stress` vs `acute_deterioration` table) found hardest to distinguish from HR/MAP time
series alone — are cleanly separated here (1–3 misclassifications out of ~60 each way), because
`ejection_fraction_pct` is directly available as an input feature to this model, unlike the
Pulse-output-only comparison in Phase 2.

**Phase 4 (batch simulation dataset, done).** `src/pulse_runner/batch_runner.py` runs a stratified
sample of synthetic patients through Pulse in parallel and `src/analytics/simulation_features.py` extracts a
fixed feature set from each run — see §5 continuation below and §7 for full results.

**Phase 5 (risk scoring & clinical logic, done).** See §6 for the full weighted-score design,
citations, and XGBoost comparison; `models/model_card.md` for both trained models' documented
limitations.

### Phase 4 — Batch Simulation Dataset

**Composition:** unlike the original roadmap's fixed 5×10×3 severity grid, this pulls a stratified
sample directly from the existing `data/synthetic/patients.csv` population (30 patients per
scenario type = 150 total, `sample_patients()` in `batch_runner.py`) — that population already
carries real, clinically-correlated per-patient severity/EF/BNP as ground truth and already spans
the full severity range within each scenario type, so no separate grid logic was needed.

**Execution:** each patient's `patient.json`/`scenario.json` (Phase 2's `patient_builder/`,
unchanged) is run through `run_pulse()` (Phase 2's `pulse_runner/runner.py`, unchanged, including
its crash detection) via a `ProcessPoolExecutor` with 4 parallel workers — required, not optional:
individual run latency is ~110s under this machine's arm64→amd64 Docker emulation (§4), so 150 runs
sequential would be ~4.5 hours. Each result is checkpointed to
`data/simulation_runs/checkpoint.csv` as it completes, so an interrupted run doesn't lose progress
already made — added after the very first full-batch attempt ran with no incremental write and
would have lost everything had it been killed early.

**Feature extraction** (`src/analytics/simulation_features.py`, per run): `hr_start/end/rise`,
`map_start/end/drop`, `co_start/end/drop_pct`, `stroke_volume_start/end`, `compensation_flag`
(1 if stroke volume held ≥95% of its starting value through the run), and `instability_flag`
(1 if `map_end < 65` mmHg, a standard critical-care hypoperfusion threshold — see
`docs/data_provenance.md`). `OxygenSaturation` is never used (§4, §8).

**Result: 117/150 runs succeeded** (`data/simulation_runs/features_dataset.csv`), 33 failed
(`data/simulation_runs/failed_runs.csv`) — but the failures are not evenly distributed:

| Scenario | Success rate | Failure mode |
|---|---|---|
| `stable`, `deconditioning`, `fluid_overload` | 30/30 (100%) | — |
| `cardiac_stress` | 15/30 (50%) | crashes/timeouts above severity ≈0.45 |
| `acute_deterioration` | 12/30 (40%) | crashes/timeouts above severity ≈0.6–0.85 |

This lines up exactly with a finding already flagged in Phase 2 (§4): `cardiac_stress` and
`acute_deterioration` are the only two scenarios that add an `Exercise` action on top of the
EF-driven `CardiovascularMechanicsModification` multipliers, and exercise intensity above ~0.5 was
already known to destabilize the engine. At scale, across the full severity range, that
instability shows up as a real, reproducible crash/timeout rate rather than the one-off collapse
seen with a single hand-picked patient in Phase 2 validation. **Practical consequence:** the
training dataset's coverage of `cardiac_stress`/`acute_deterioration` is effectively capped at
low-to-moderate severities — high-severity examples of these two scenarios are underrepresented,
which Phase 5 needs to account for (e.g. by not expecting reliable severity regression at the
extreme end for these two types specifically).

**Feature sanity check** (within each scenario type, correlation of `severity` with `hr_rise`):
`fluid_overload` 0.81, `acute_deterioration` 0.82, `cardiac_stress` 0.63 — all strongly positive,
as expected. `deconditioning` is −0.67 (negative), which is *also* expected: deconditioning has no
`Exercise`/`HeartRateMultiplier` action by design (§4, "no acute exertion event"), so its HR
response is driven only by mild resistance/compliance modifiers, not a severity-scaled tachycardia
push. `compensation_flag` is near-universal (1) for `stable`/`fluid_overload`/`deconditioning` but
0.0 for `cardiac_stress` and 0.33 for `acute_deterioration` in the successful runs — worth noting
this flag is stricter than it might look: even the successful (lower-severity, better-EF)
`cardiac_stress` runs show real stroke-volume decline (>5%) under HR-driven stress, a genuine
diastolic-filling-time effect, not a bug — the continuous `stroke_volume_start`/`stroke_volume_end`
columns are still in the dataset for Phase 5 to use directly if a graded signal is preferred over
this binary flag.

## 6. Risk Scoring Logic, With Clinical Citations

Per the locked decision in CLAUDE.md, the primary risk scorer is a hand-tuned, interpretable
weighted score (`src/analytics/risk_score.py`); a secondary/experimental XGBoost regressor
(`src/ml_models/train_risk_scorer.py`) exists only as a comparison point, trained on the same
117-row Phase 4 dataset. Both consume the same 5 features:
`hr_rise, map_drop, co_drop_pct, compensation_flag, instability_flag`.

### 6.1 Primary — hand-tuned weighted score

Each input is normalized to 0-1 against a clinically-anchored full scale, then combined by a
hand-set weighted sum (weights sum to 1). Every anchor and weight is in
`docs/data_provenance.md`'s Reference Table and the module's own docstring/comments — summary:

| Component | Anchor | Citation |
|---|---|---|
| `hr_rise` (weight 0.15) | NEWS2 heart-rate scoring bands, applied to `hr_rise + assumed 70bpm baseline` | Royal College of Physicians, NEWS2, 2017 |
| `map_drop` (weight 0.20) | Full scale = healthy baseline (~92.5mmHg, this project's own Phase 2 validation) minus the MAP<65 instability threshold | Surviving Sepsis Campaign; Vincent & De Backer, NEJM 2013 |
| `co_drop_pct` (weight 0.20) | 30% decline = full scale (negative values, i.e. CO *rising*, clamp to zero risk) | Nohria et al., JAMA 2002; SCAI 2019 Cardiogenic Shock Stage consensus |
| `compensation_flag` (weight 0.15) | Binary — failed compensation (flag=0) contributes full weight | Frank-Starling mechanism failure, textbook hallmark of systolic dysfunction |
| `instability_flag` (weight 0.30, highest) | Binary — reuses the MAP<65 citation directly | same as `map_drop` |

`risk_bucket` thresholds (`LOW`<0.35, `MODERATE`<0.65, `HIGH`≥0.65) are an engineering choice
(roughly a tertile split), not a clinical citation — documented as such in the code.

**Validation against all 117 rows of `features_dataset.csv`:** the *pooled* correlation of
`risk_score` with `severity` is near zero (−0.06) — but this is a Simpson's-paradox-style
confound, not evidence the score is broken: different scenario types have very different baseline
risk regardless of severity, so pooling across them washes out the real relationship. Within each
scenario type: `acute_deterioration` 0.70, `cardiac_stress` 0.30, `deconditioning` 0.21 — all
positive as expected. `stable` is −0.19 (expected: severity is capped <0.15 by design, so this is
noise around a floor, not a real trend). Bucket distribution by scenario: `stable`,
`deconditioning` are 100% `LOW` (deconditioning is the mildest scenario by design — no `Exercise`
action, see §4 — so this is correct, not a bug); `cardiac_stress` is 80% `MODERATE`/20% `HIGH`
(0 `LOW`); `acute_deterioration` spans all three buckets with a majority `HIGH`.

**`fluid_overload` is a known blind spot of this formula, found during validation and worth being
explicit about:** all 30 successful `fluid_overload` runs score `LOW` regardless of severity
(0.003 to 0.99), with `risk_score` showing zero variance (undefined correlation with severity).
Inspecting the raw features explains why: `fluid_overload`'s danger is encoded as a *shifted
baseline* (MAP starts already congested at ~77-79mmHg instead of ~90-95mmHg, per §4/§7's own
Phase 2 table — `77→77`) rather than as further *acute* deterioration during the 10-minute
simulated window, since `fluid_overload` has no `Exercise` action. `hr_rise`/`map_drop` stay near
zero (nothing changes *during* the run) and `co_drop_pct` is consistently negative (CO actually
rises ~11-14%, matching Phase 2's original single-patient finding), and 78mmHg is well above the
65mmHg `instability_flag` threshold. **The formula, exactly as specified (5 within-run-delta
features), is structurally blind to a chronically-shifted-but-acutely-stable presentation like
this** — it only sees change *during* one simulated encounter, not a baseline state that's already
abnormal going in. This is a real scope limitation of the current feature set, not an
implementation bug; see §8.

### 6.2 Secondary/experimental — XGBoost

See `models/model_card.md` for the full writeup (training data, CV protocol, and — most
importantly — why n=117 with real class imbalance means this is a comparison signal only, never
the primary output). Headline numbers: 5-fold stratified CV, MAE 0.089 ± 0.020, R² 0.828 ± 0.091.

### 6.3 Rule-based clinical logic (`src/analytics/`)

- **`staging.py`** — rule-based NYHA classifier. AHA/ACC 2022 Stage B structural/biomarker
  criteria (LVEF≤40% or age-adjusted NT-proBNP above cutoff, both already in
  `data_provenance.md`/`reference_stats.yaml`) gate whether a patient has any structural basis for
  symptoms; the simulated exertion response (`risk_score`/`instability_flag`) then places a
  structurally-at-risk patient in NYHA I-IV, reusing `risk_score.py`'s own `LOW`/`MODERATE`/`HIGH`
  boundaries rather than a second set of thresholds.
- **`deterioration_rate.py`** — per-vital slopes over the 21-day wearable window (reuses
  `src/scenario_classifier/features.py`'s `np.polyfit` slope technique), normalized to
  population-SD-equivalents/day using `reference_stats.yaml`'s existing `wearable_baseline` SDs,
  combined with a sign convention matching `generate_wearable_trends.py`'s own
  `SCENARIO_SIGNAL_DELTAS` definition of "worsening" per vital. `days_to_next_stage()` converts
  this composite rate to a risk-score-equivalent daily rate via one explicit, named constant
  (`SD_RATE_TO_RISK_SCORE_PER_DAY = 0.05`) — flagged in `data_provenance.md` as an
  `assumed_default` engineering calibration, not a clinical citation, since no literature source
  exists for this specific conversion.
- **`projection.py`** — `project_severity()` linearly extrapolates severity forward using that
  same rate (clamped 0-1); `project_physiology()` re-runs the full Phase 2/4 pipeline
  (`patient_builder` → `run_pulse()` → `simulation_features` → `risk_score`) at each projected
  severity for 7/14/30-day horizons. Manually verified once inside Docker on patient `P0000`
  (`acute_deterioration`, starting severity 0.207) — see §7.

### 6.4 API orchestration (`src/api/`, Phase 6)

The FastAPI backend doesn't add new modeling logic — it's the stateful glue that turns the
Phases 1-5 pipeline (already built) into a system a client can actually call. Five SQLAlchemy
tables (`patients`, `clinical_reports`, `wearable_readings`, `simulation_runs`,
`risk_assessments`) persist what would otherwise be lost between requests — without this,
`GET /history`'s trend and `GET /projection`'s forecast can't be honestly demoed, they'd have to
be recomputed or faked on every call.

**Wearable accumulation, not immediate triggering:** `POST /patients/{id}/wearable-sync` stores
one day's reading per call (matching the roadmap PDF's own "daily wearable data" framing) and only
kicks off the assessment pipeline once a patient has 21 accumulated readings — `_wearable_features()`
(Phase 1/3) needs that fixed window. Below 21, the endpoint just stores the reading and reports a
`"collecting"` status.

**Everything Pulse-related lives in one background job, not spread across endpoints:**
`BackgroundTasks` runs `services.run_assessment_pipeline()` once the window fills — ML Model 1
(scenario classification) → `patient_builder`/`run_pulse()` (current-state simulation) →
`simulation_features` → `risk_score` + `staging` → `deterioration_rate` (same 21-day window) →
`projection.project_physiology()` (3 more Pulse calls, 7/14/30-day horizons) → one
`simulation_runs` row + one `risk_assessments` row, written together. This means every `GET`
endpoint (`/status`, `/history`, `/projection`, `/report`) is a fast DB read with zero Pulse calls
in the request path — not just `/wearable-sync` returning immediately, but the whole read side of
the API never blocks on Pulse. One background job does 4 total Pulse calls (~2min each under this
machine's arm64 emulation, §4/§8) — real wall-clock time, but entirely off the request path.

**Tier 1 fallback** (`services.apply_tier1_fallback`): a clinical report with missing EF defaults
to `reference_stats.yaml`'s healthy-population mean (62%, already `assumed_default`); missing
NT-proBNP defaults to 100 pg/mL (new `assumed_default`, see `data_provenance.md` — well under even
the youngest age band's diagnostic cutoff). Both are recorded via `ef_is_fallback`/
`bnp_is_fallback` flags on the stored report, never silently blended with a real reading.

**`risk_caveats`** on `risk_assessments`: populated with a warning whenever the detected
`scenario_type` is `fluid_overload`, directly surfacing §6.1's finding that `risk_score` is
structurally blind to that scenario's presentation. The field's OpenAPI description (visible in
`/docs`) explains why, not just that it can be null.

**Extended in Phase 7** (frontend integration, full gap list in §10): `RiskAssessment` gained
`ejection_fraction_pct`/`nt_probnp_pg_ml`/`vital_slopes` columns (values already computed in the
pipeline above, previously discarded once used) plus `scenario_type`/`severity` proxy properties
onto the already-stored `SimulationRun` fields (no duplication); `StatusResponse` gained
`latest_wearable`; a new `GET /patients` list endpoint was added; and `CORSMiddleware` was added to
`main.py` (a browser, unlike `curl`/`TestClient`, enforces CORS — this was invisible until the
frontend was actually opened and clicked through, see §10).

**Error handling:** malformed wearable vitals reject with Pydantic-driven 422s before ever
reaching Pulse. A `PulseExecutionError` inside the background job never surfaces as an HTTP
error (the triggering request already returned 202 before the job runs) — instead
`simulation_runs.status` becomes `"failed"` with `error_message` and `scenario_json_path`
recorded, discoverable via `GET /status`. A defensive global exception handler still returns 500
for genuinely unexpected errors in the synchronous request path (DB issues, etc.).

**A real environment gotcha, not a design choice:** the Pulse Docker container ships Python 3.9,
but `src/api/models.py`/`schemas.py` were first written using PEP 604 union syntax (`str | None`).
That parses fine under `from __future__ import annotations` on any Python version, but SQLAlchemy's
`Mapped[]` and Pydantic's `BaseModel` both resolve annotations at class-definition time via
`eval()`, which fails on 3.9 (`X | None` needs 3.10+) — `NameError: Could not de-stringify
annotation 'str | None'` the first time `src/api/main.py` was imported inside the container. Fixed
by using `typing.Optional[X]` in those two files specifically; plain function signatures elsewhere
in `src/api/` (never runtime-introspected) were left as `X | None`, since that's the project's
existing style everywhere else and there's nothing that resolves those annotations at runtime.

**One real integration bug this session's own test suite caught:** `project_physiology()`
(Phase 5) needs `ejection_fraction_pct` in the same patient dict it uses for
`build_patient_file()`/`build_scenario_file()`, but the API's `demo_row` (built for the demographic
fields alone) initially omitted it — a `KeyError` that only `tests/test_api.py`'s full
pipeline test surfaced, not either phase's own unit tests in isolation. Fixed by including it in
`demo_row`; a good example of why an end-to-end integration test earns its keep even when every
component underneath it is already individually tested.

## 7. Validation Approach and Results

**Phase 1** (data synthesis): see `tests/test_data_synthesis.py` (15 checks: schema, clinical
correlation direction, trend shapes).

**Phase 3** (scenario classifier): see `tests/test_scenario_classifier.py` (11 checks: feature
schema/leakage, stratified split integrity, end-to-end train/eval sanity bounds) plus the
held-out-set results in §5 above.

**Phase 4** (batch simulation dataset): see `tests/test_simulation_features.py` (11 checks:
column-matching robustness, every feature/flag's both states, `OxygenSaturation` never used) and
`tests/test_batch_runner.py` (5 checks: stratified sampling correctness, determinism, no
duplicates). The actual Docker execution itself — `_run_one()`/`run_batch()` — can only be
exercised inside the Pulse container, same as Phase 2's `scripts/validate_phase2.py`; it was
validated in two stages: a 10-patient pilot (10/10 succeeded, ~110s/run individual latency,
confirming the pipeline end-to-end before committing to the full run), then the full 150-patient
batch (117/150 succeeded — see §5 for the failure breakdown and why it's scenario/severity-specific
rather than a pipeline bug).

**Phase 5** (risk scoring & clinical logic): `tests/test_risk_score.py` (12 checks: monotonicity
per component, boundary cases, weights sum to 1), `tests/test_train_risk_scorer.py` (7 checks: CV
pipeline wiring, determinism, the exact documented class-imbalance counts), `tests/test_staging.py`
(7 checks: structural gate, all 4 NYHA classes reachable, age-adjusted cutoff, instability
override), `tests/test_deterioration_rate.py` (10 checks: slope sign conventions per vital,
stable/worsening/improving direction, days-to-next-stage edge cases), `tests/test_projection.py`
(7 checks: `project_severity()` clamping and linear extrapolation — pure math, no Docker). Plus
the 117-row `risk_score` validation in §6.1.

`project_physiology()` (the one piece of Phase 5 that needs Docker) was manually verified once on
patient `P0000` (`acute_deterioration`, starting severity 0.207, `deterioration_rate_per_day=0.03`
worsening trend) — 3 re-simulations at the 7/14/30-day projected severities (0.417/0.627/1.0,
clamped) all ran successfully, confirming the re-simulation pipeline (`patient_builder` →
`run_pulse()` → `simulation_features` → `risk_score`) is wired correctly end to end. `risk_bucket`
is `HIGH` at all three horizons, but `risk_score` itself is roughly flat (0.767 → 0.738 → 0.731)
rather than climbing further with the increasing projected severity — `hr_rise` saturates at 90
(162bpm) from the 7-day horizon onward, so the `instability_flag`/`hr_rise` components are already
at their component maximum by then; only `map_drop`'s smaller marginal contribution shifts
slightly across horizons. This is an emergent property of how `acute_deterioration`'s Pulse
mechanics respond to severity in this range (similar to other emergent, not hand-tuned, findings
in §4/§7) — the takeaway from this single verification run is that the pipeline executes
correctly, not a claim about risk trending strictly upward with severity at the high end.

**Phase 6** (FastAPI backend): `tests/test_api.py` (21 checks, `FastAPI TestClient` + an isolated
temp-file SQLite DB per test, `run_pulse()` mocked at both call sites —
`src.api.services.run_pulse` for the current-state simulation and `src.analytics.projection.run_pulse`
for the 3 projection re-simulations, since each module imported its own reference) — happy-path
and failure-path coverage for all 7 endpoints: patient creation (+ invalid-age 422), clinical
report with and without Tier 1 fallback (+ unknown-patient 404), wearable-sync malformed-vitals
422, the `"collecting"` state below the 21-day threshold, pipeline triggering at the threshold, a
mocked `PulseExecutionError` correctly landing `simulation_runs.status="failed"`, and both the
`fluid_overload`→`risk_caveats`-populated and non-`fluid_overload`→`risk_caveats`-null cases.

The full pipeline (all 4 real Pulse calls: 1 current-state + 3 projection horizons, no mocking)
was also manually verified once inside Docker: a patient with EF=32/NT-proBNP=1800 and 21 days of
wearable data with a real upward HR (+2 bpm/day) and weight (+0.2 kg/day) drift. Result, end to
end with nothing faked: ML Model 1 correctly classified this as `fluid_overload` (rising weight +
HR is literally the textbook fluid-overload signature); the pipeline completed successfully
(`simulation_status="complete"`); and — notably — **`risk_score` came back `0.0`/`LOW` with every
component at zero**, reproducing §6.1's `fluid_overload` blind-spot finding exactly, this time on
a real live run rather than the offline 117-row batch. `risk_caveats` was correctly populated with
the warning. `deterioration_direction` correctly read `"worsening"` (from the real upward trend),
`nyha_class` came back `"II"`, and the 7/14/30-day projection showed severity climbing
0.159→0.203→0.303 while `risk_score` stayed flat at `0.0`/`LOW` throughout every horizon — the
blind spot doesn't go away as projected severity increases, because the mechanism (a shifted
baseline Pulse never re-compares against) doesn't change with severity within a single run's own
start/end comparison. This is a strong, independent confirmation that the Phase 5 finding is a
real, reproducible property of the scenario/formula combination, not an artifact of the offline
batch dataset.

**Phase 7** (frontend dashboard): no automated test suite (§10 explains why), so verification was
manual but end-to-end and in an actual browser (Playwright + Chrome), not just visual inspection of
static markup. Two passes: (1) mock-data mode (`VITE_USE_MOCK=true`) — all three risk buckets
(LOW/MODERATE/HIGH), the `collecting` state, a `failed`-simulation state, and a backend-unreachable
network-error state were each rendered and screenshotted, confirming zero console/page errors and a
pixel-close match against `design_reference.html` opened directly. (2) Real backend mode — a real
patient was created via the API, given 21 real `wearable-sync` calls, and its background pipeline
(ML Model 1 → real Pulse run inside Docker → risk scoring → staging → projection) was allowed to
actually complete; the dashboard was then opened against this live backend and clicked through:
correct scenario/severity/EF/BNP/vitals rendering, the `fluid_overload` `risk_caveats` warning
correctly appearing on a real (not mocked) run, the Copy button verified to actually place the
generated report text on the system clipboard (read back and checked, not just visually confirmed),
and the manual-refresh button confirmed to re-fetch without error. This second pass is also what
caught the CORS gap in §10 — a class of bug invisible to `curl`/`TestClient`-only testing. Mobile
verified at a 390px viewport: no page-level horizontal overflow (only the Vitals table scrolls
within its own container, as designed), sections stack in a sensible single column.

**Phase 2** (Pulse integration): all 5 locked scenario types were run once each at severity ~0.5,
using real patients from `data/synthetic/patients.csv`, inside the actual Pulse Docker container
(`scripts/validate_phase2.py`). Results were physiologically sensible and clearly differentiated:

| Scenario | HR (start→end) | MAP (start→end) | Notes |
|---|---|---|---|
| `stable` | 71→70 | 95→95 | flat, as expected |
| `deconditioning` | 71→74 | 95→95 | mild drift only (no acute action — see §4) |
| `fluid_overload` | 72→72 | 77→77 | HFrEF baseline (lower MAP from the condition), CO rises ~13% |
| `cardiac_stress` | 71→164 | 95→67 | large compensatory response — healthy heart (EF 67) under exertion |
| `acute_deterioration` | 72→132 | 78→52 | HR rises but stroke volume barely moves (63→67 mL) — a failing heart (EF 26.6) unable to compensate, unlike cardiac_stress's healthy compensation |

The `cardiac_stress` vs. `acute_deterioration` contrast is the most clinically meaningful finding:
both show HR increases, but `cardiac_stress` mounts a strong cardiac-output response (5910→9948
mL/min, stroke volume holding at 60-82 mL) typical of a healthy heart under exertion, while
`acute_deterioration`'s output rises much less (4557→8972 mL/min) despite a similar HR jump,
because its stroke volume can't increase — the hallmark of decompensating systolic function. This
wasn't hand-tuned to look this way; it emerged from the EF-driven modifiers.

`deconditioning` initially used an `Exercise` action and was physiologically indistinguishable from
`cardiac_stress` (both drove HR to 150-164) — fixed by removing the acute Exercise action, since
deconditioning is meant to represent chronic reduced reserve, not an acute exertion event.

Every scenario's log was scanned by `run_pulse()`'s crash detection; no run currently triggers a
fatal marker, though `acute_deterioration` did during earlier tuning (see §4) — confirming the
detection path actually works, not just that it was written.

## 8. Limitations

- No real clinical validation yet (synthetic data only).
- Wearable sensor measurement error not modeled.
- Pulse's native operating range (age 18-65, BMI 16.0-30.0) is narrower than our real-data-grounded
  population; patients outside it are simulated via a capped-demographic proxy body (see §4) —
  their EF/BNP/severity still drive the simulation correctly, but the simulated body's age/weight
  isn't literally theirs.
- `OxygenSaturation` output is currently unreliable (reads 0.0) for reasons not yet fully isolated —
  see §4. Downstream analytics should not depend on this column until resolved.
- Small simulation dataset for the risk scorer: 117 rows, not the targeted 150 — 33 of 150 batch
  runs failed, concentrated almost entirely in `cardiac_stress` (50% failure) and
  `acute_deterioration` (60% failure) above roughly severity 0.45–0.6, because those are the only
  two scenarios that add an `Exercise` action, and exercise intensity above ~0.5 destabilizes the
  Pulse engine (§4, §5). Phase 5's secondary model should not be expected to generalize well to
  high-severity `cardiac_stress`/`acute_deterioration` cases as a result — this population is
  thin in the training data by construction, not by sampling bad luck.
- No medication-effect modeling in Pulse scenarios.
- Simulations run under `arm64`→`amd64` Docker emulation on this development machine; each
  simulated scenario takes ~110s-2 minutes wall-clock (vs. Pulse's own ~30s reported internally) —
  confirmed at both single-run scale (Phase 2) and across the full Phase 4 150-run batch, where it
  meant ~4 parallel workers were needed to keep total wall-clock to roughly 90 minutes rather than
  ~4.5 hours sequential.
- No authentication/authorization on the API — every endpoint is open, appropriate for local
  prototype use only, not for anything handling real patient data.
- `BackgroundTasks` runs the assessment pipeline in FastAPI's own thread pool, not a real task
  queue — fine at prototype scale (one pipeline per patient's 21-day window closing), but it means
  a burst of many patients completing their window simultaneously would serialize behind the
  thread pool's size rather than scale independently. Celery/Redis is explicitly a Phase 9 stretch
  goal for exactly this reason, not something Phase 6 needed to solve.
- A patient's assessment only updates once per 21-day window fill, not incrementally per new
  reading — matches `_wearable_features()`'s fixed-window design (Phase 1/3), but means the system
  can go up to 21 days without a fresh assessment for a newly-onboarded patient, which a real
  deployment would likely want to shorten (e.g. a sliding window) rather than a hard reset each time.
- `GET /patients/{id}/status` reports `simulation_status="complete"` as soon as *any* prior
  assessment exists for that patient, even while a newer run is actively in progress (it only
  checks whether a `RiskAssessment` row exists at all, not whether the *latest* `SimulationRun` has
  finished) — a pre-existing Phase 6 behavior, not something Phase 7 changed. Practical
  consequence: the frontend's "simulation running" banner is only actually observable before a
  patient's very first assessment completes; every later re-run is invisible as "running" from the
  API's perspective until it either lands a new assessment or fails.
- `GET /patients` has no pagination and the sidebar issues one additional `GET .../report` call per
  patient to populate its risk-bucket summary (no list-with-summary endpoint exists) — fine at demo
  scale, would need real pagination/a summary endpoint before this could be used with more than a
  handful of patients.
- The API's CORS policy (`allow_origins=["*"]`, added in Phase 7) is appropriate for local
  development only, same caveat as the "no authentication" limitation above.
- "Run New Simulation" in the frontend does not actually trigger a new Pulse run — Phase 6 has no
  manual-trigger endpoint (simulations only start automatically once a 21-day wearable window
  fills), so the button performs a manual refresh of the current status/report instead. A real
  on-demand trigger would be a Phase 6 API addition, not a frontend-only change.

## 9. Future Work

TODO. Tier 3 (ECG-derived BP/contractility) belongs here only — never implement it (locked decision).

## 10. Frontend Dashboard (Phase 7)

**Design source.** `frontend/design_reference.html` is a self-contained "Claude Design" export — a
bundled React app, gzip+base64-encoded inside `<script type="__bundler/...">` tags, not plain
inspectable HTML/CSS. Rather than guess the layout from a rendered screenshot, the bundle's
manifest was decoded directly (`base64` → `gzip` decompress on the `text/javascript` resources;
`json.loads` on the pre-rendered template string) to recover the exact DOM structure, CSS variables/
classes, colors, and interaction logic (ECG waveform animation, severity gauge, pulse-on-HIGH-risk
border animation, copy/download report) actually used by the reference. The resulting port is
pixel-close to the reference, confirmed by rendering both side by side and comparing screenshots.

**Design-vs-real-API gaps found and resolved.** Comparing the design against the actual Phase 6
API (not assuming it would just line up) surfaced several fields the design needs that the pipeline
computes but never returned anywhere, plus a few outright invented values. Each was resolved by
either extending the backend to expose a real computed value, or redesigning the UI element around
what's actually computed — never by fabricating a number client-side:

| Design element | Gap found | Resolution |
|---|---|---|
| Current Condition / Vitals panels | `scenario_type`, `severity`, EF, BNP, latest wearable reading computed but never returned by any endpoint | Extended `RiskAssessmentPayload`/`StatusResponse` (small additive schema/model changes, §6.4) |
| Sidebar patient list | No `GET /patients` endpoint existed (only `POST`) | Added `GET /patients` (list, no pagination — demo scale) |
| HF Stage badge (A-D) | Never computed anywhere — only NYHA I-IV exists | Omitted rather than inventing a clinical output this system never validated |
| Forward Projection per-horizon HR/MAP/CO | `ProjectionHorizon` only ever carried `projected_severity`/`risk_score`/`risk_bucket`/`status` | Redesigned cards around the real fields instead of fabricating physiological values per horizon |
| Vitals table "Simulation Output" column | No absolute simulated vitals are persisted (only within-run deltas used internally for `risk_score`) | Redesigned to a 4-column table (Metric / Today's Input / 7-Day Trend / Status), with "7-Day Trend" backed by a new addition: persisting `compute_deterioration_rate()`'s `vital_slopes` onto `RiskAssessment` (previously computed then discarded) |
| "Probability of progressing to next HF stage" bar | No probability is ever computed — only `days_to_next_stage`, a day-count from linear extrapolation | Relabeled/redesigned around the real day-count, framed as a 30-day-window progress bar |
| "Run New Simulation" button | No manual-trigger endpoint exists — Phase 6 only runs the pipeline automatically once a 21-day wearable window fills | Button performs a manual refetch of `/report` instead; disabled with an "X/21 days collected" label while `simulation_status === "collecting"` |
| Patient display name | `Patient` has no `name` field (anonymized by design) | Sidebar/hero show a deterministic ID-derived label/avatar instead of inventing a name field |
| "Digital Twin Confidence 92%" badge | No such metric is computed anywhere | Omitted, same reasoning as the HF Stage badge |

**CORS — found by actually using a browser, not `curl`.** Every backend check up to this point
(`curl`, `TestClient`, direct API calls) succeeds against the FastAPI server with no CORS
middleware, because CORS is a browser-enforced restriction — `curl` and Python's `requests`/
`httpx` simply don't apply it. The first time the actual frontend (Vite dev server, its own origin)
was opened in a real browser and clicked through, every `fetch()` failed as a generic network error
before ever reaching the server. Fixed by adding `CORSMiddleware` (`allow_origins=["*"]`) to
`src/api/main.py` — wide open since this is a local decision-support tool, not a public
multi-tenant API. This is precisely the kind of gap that only surfaces when the thing is actually
opened in a browser and clicked through, not just exercised via test client or `curl` — see §7 for
how this was verified afterward.

**State handling.** `usePatientReport` treats `simulation_status` as a small state machine, not a
single loading spinner: `collecting` (progress toward the 21-day window), `running`/`pending` with
no prior assessment (first-ever simulation for a patient), `running`/`pending` with a prior
assessment present (dimmed last-known data + a banner, not a blank screen), `failed` (surfaces
`error_message`, deliberately shows nothing else rather than stale or fabricated data), and
`complete`. A separate network/`ErrorState` (backend unreachable) is distinct from `failed`
(backend reachable, but the simulation itself failed) — conflating the two would make a down
backend look like a bad simulation, or vice versa.

**What wasn't built, on purpose.** No test suite under `frontend/` — the approved build order's 5
steps (static/mock → wire real data → loading/error states → mobile → polish) didn't include one,
unlike every prior Python phase's `pytest` suite, so none was added silently. No sidebar
hamburger/drawer toggle — the responsive pass collapses the sidebar to a static block above the
main content on narrow viewports instead, which is simpler and doesn't overlap or break anything at
390px width (verified), even though it's not literally the "collapsible drawer" language used while
planning the mobile pass.

See §7 for how all of the above was verified (mock-data static build, then a real end-to-end run:
real patient → real 21-day wearable sync → real Pulse simulation inside Docker → real ML
classification → real risk scoring, rendered correctly in an actual browser with zero console
errors).
