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
sample of synthetic patients through Pulse in parallel and `src/simulation_features.py` extracts a
fixed feature set from each run — see §5 continuation below and §7 for full results.

Phase 5 (risk scorer) is not started.

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

**Feature extraction** (`src/simulation_features.py`, per run): `hr_start/end/rise`,
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

TODO — Phase 5. Primary model is the hand-tuned interpretable weighted score (locked decision);
XGBoost on the Pulse batch dataset is secondary/experimental only.

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

## 9. Future Work

TODO. Tier 3 (ECG-derived BP/contractility) belongs here only — never implement it (locked decision).
