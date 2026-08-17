# Methodology

**Personalised Digital Twin for Early Heart Failure Deterioration Detection**

Status: skeleton — filled in incrementally as each roadmap phase completes, not written
retroactively before submission. The decisions already locked (personalization tiers, scenario
taxonomy, dataset strategy, primary risk scorer choice) are stated where each is used below (§3,
§6) and in `docs/data_provenance.md` — this document explains *why* those decisions were made and
how each phase was executed, not just what the decisions are.

## 1. Problem Statement

Heart failure (HF) affects an estimated 64 million people worldwide, and its defining clinical
feature is that it is progressive: patients decline gradually, not instantaneously. Despite this,
roughly half of HF patients are re-hospitalized within 6 months of discharge — not because
deterioration is undetectable in principle, but because it is missed in practice. Three structural
gaps in current monitoring explain why:

1. **Monitoring is episodic, not continuous.** Patients are typically only assessed at clinic
   visits spaced 4-6 weeks apart. A patient can move from a stable state to a crisis well within
   that window with no clinical observation in between.
2. **Consumer wearables report numbers, not physiology.** A smartwatch can show "resting HR: 95
   today," but has no model of what that number means for a specific patient's cardiovascular
   state — whether it reflects benign daily variation or an early compensatory response to
   worsening cardiac output. The measurement is real; the interpretation is missing.
3. **No existing home-monitoring system projects a patient's trajectory forward.** Threshold-based
   alerts (e.g. "SpO2 < 92%") only fire after a value has already crossed into an abnormal range —
   they describe where a patient is, not where they are heading.

The consequence, from the patient's side, is a daily judgment call with no good options: a
55-year-old HF patient who wakes up slightly breathless with a marginally elevated heart rate has
no way to distinguish "this is a bad day" from "this is the start of decompensation" — so they
either under-react (and risk a preventable hospitalization) or over-react (and generate an
unnecessary ER visit). By the time overt symptoms bring a patient back into contact with the
health system, significant physiological decline has typically already occurred, and treatment is
reactive rather than preventive.

This project (working title: *Personalised Digital Twin for Early Heart Failure Deterioration
Detection*) addresses this gap by building a patient-specific digital twin: a validated
physiology simulation (Kitware Pulse), personalized to an individual patient's clinical baseline
(EF, NT-proBNP, demographics) and driven forward by their own rolling wearable trend data, used to
answer the question a wearable alone cannot — *given this patient's trajectory so far, what is
their body likely to do next, and how urgent is it?* Sections 3-6 below detail how each modeling
decision (personalization tier scope, scenario taxonomy, primary risk scorer choice) was made in
service of that question, and Section 7 documents what has actually been validated to support it,
as opposed to what remains a design intention.

## 2. Data Sources and Provenance

See `docs/data_provenance.md` for the full parameter-level table. Summary:
- Clinical baselines: synthetic, derived from cited papers + Kaggle datasets (never real patient data)
- Wearable trends: synthetic, 3 modes — `stable`, `deteriorating`, `recovering`
- Simulation dataset: self-generated via Pulse batch runs (Phase 4, done — see §5 and §7)

## 3. Personalization Tier Design and Justification

This project's locked Phase 0 decision: Tier 1 (demographics + EF + BNP + wearables) is core,
Tier 2 (echo PPG) optional/stretch, Tier 3 (ECG-derived BP/contractility) permanently cut.

**Why Tier 2 stayed unbuilt, not just deprioritized:** Tier 2 was scoped as an *optional* add-on
from the start — echocardiography-derived PPG features feeding a vascular-compliance estimate,
layered on top of Tier 1 rather than replacing it. Two things kept it out of the delivered system,
both confirmed by what actually shipped rather than a schedule guess:

1. **No echo/PPG dataset was ever acquired.** `docs/data_provenance.md`'s "Real datasets acquired"
   table lists exactly four sources — `mimic_bigquery_extract`, `andrewmvd_kaggle`,
   `fedesoriano_kaggle`, `nhanes_kaggle` — none of which contain echocardiographic or PPG
   waveform data. Building Tier 2 would have meant synthesizing vascular-compliance values with no
   real-data grounding at all, which conflicts with this project's own stated dataset strategy
   (§2): every synthetic parameter traces to a cited real distribution, and no substitute source
   for echo/PPG was ever sourced or vetted.
2. **Tier 1 alone already met the project's own accuracy targets.** The scenario classifier
   trained on Tier 1 features (clinical snapshot + wearable-trend aggregates, no vascular-
   compliance term) reached 92.3% test accuracy and severity MAE 0.048 (§5) — comfortably past the
   informal >80% target the roadmap set for this model. Tier 2 was never load-bearing for a result
   the system actually needed to hit; adding it would have been complexity without a corresponding
   accuracy gap to close.

Tier 2 therefore remains exactly what it was scoped as — optional and unimplemented — not a cut
scope item disguised as a stretch goal. It is listed again in §9 as legitimate future work, since
an echo/PPG-derived compliance term is a real, literature-supported way to sharpen the digital
twin's cardiovascular personalization if a suitable dataset is later acquired.

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

**Features** (one row per patient, 29 columns total): the clinical snapshot from
`patients.csv` (`age`, `sex`, `bmi`, `ejection_fraction_pct`, `nt_probnp_pg_ml`), plus per-vital
wearable-trend aggregates from the 21-day window in `wearable_trends.csv` — first-7-day mean,
last-7-day mean, delta, and linear slope, for each of `resting_hr_bpm, spo2_pct, weight_kg,
steps_per_day, sleep_hours, hrv_rmssd_ms`. This mirrors the real deployment input (a clinical
report + a rolling wearable window), not raw simulation internals. (`nyha_class` as an ordinal was
originally included here too; removed after diagnosis in §7/§8 below — see §9 "done" items.)

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

### Missingness — mechanism, not just a completion rate

Every completion-rate number in this document (Phase 4's 117/150, Phase 8's 25/25, PerHeart's
16/16 then 13/16 post-fix, §8.3's concurrency-escalation failures) has so far been reported as a
rate. That undersells what four independent runs, across three different datasets and two
different execution paths (direct in-process `run_pulse()` calls and HTTP calls against the live
API), consistently show: **Pulse failures here are not one phenomenon, they're two, with opposite
statistical character and opposite practical implications.**

**Mechanism 1 — engine-level crash (`PulseScenarioDriver exited 1`), MNAR with respect to
severity.** In Phase 4's 150-run batch, 33 failed; the *dominant* failure signature was a crash
(30/33), not the 180s timeout (3/33) that gets most of this document's attention. Crashes
concentrate almost entirely in `cardiac_stress` (15/30 failed) and `acute_deterioration` (18/30
failed) — the only two scenarios with an `Exercise` action (§4) — and *within* those two scenario
types, the failed patients' own severity is high: mean 0.75 (`cardiac_stress`) and 0.72
(`acute_deterioration`) vs. a dataset-wide mean around 0.4-0.5. This is missing-not-at-random
(MNAR), not missing-at-random (MAR): the probability a run is missing depends on the value that
run *would have produced* (high severity), even after conditioning on the observed covariate
(scenario_type) — not just on scenario_type alone, which would be MAR. Three later, independent
runs reproduce the identical signature: PerHeart's post-fix re-run (§8.4) lost 3 previously-clean
patients to the exact same `exited 1` crash after a severity-model retrain changed their predicted
severity; and this session's expanded live re-validation's one failure so far (`P1978`,
`acute_deterioration`, true severity 0.675 — squarely in Phase 4's documented 0.6-0.85 crash
range) failed in 61.6s, far short of the 900s poll ceiling — a fast subprocess crash, not a slow
timeout, consistent with Mechanism 1 rather than Mechanism 2 below.

**Mechanism 2 — resource contention (`httpx.ReadTimeout`, 180s Pulse timeout), MAR with respect to
concurrency, not severity.** §8.3's concurrency escalation (9 workers → 4 → 2) found a completely
different failure driver: at 9 workers, 5/11 patients hit `ReadTimeout` (SQLAlchemy connection-pool
exhaustion) and 6/11 hit the 180s timeout (genuine CPU contention, independent of the pool issue);
at 4 workers, the pool failures vanished but 8/11 still hit the timeout; at 2 workers, zero
failures across every patient processed at that level since (30+ across both PerHeart runs, plus
this session's live re-validation to date). Whether a given patient's run failed here depended on
how many *other* patients were concurrently in flight — an observed system-state covariate — not
on that patient's own severity or scenario type. This is MAR (conditional on concurrency level),
arguably closer to MCAR once concurrency is held fixed at a safe level, and it is why 2-worker
concurrency was adopted as the standing default for every subsequent real-data run in this project
(`scripts/perheart_real_data_replay.py`, `scripts/nyha_fix_live_revalidation.py`).

**Why the distinction matters for any paper claim drawn from a completion rate:**

1. **They call for different fixes.** Mechanism 2 is already solved (cap concurrency at 2 — an
   infrastructure/scheduling fix). Mechanism 1 is not: it is a property of the Pulse engine itself
   at high `Exercise` intensity, present even at the lowest concurrency tested (Phase 4 ran
   in-process with no HTTP/DB layer at all and still saw it). Fixing it would mean either
   root-causing the engine instability directly (out of scope — see `PUBLICATION_TODO.md` P2's
   180s-timeout item, which this extends to non-timeout crashes too) or explicitly bounding paper
   claims to the severity range Pulse can reliably simulate for these two scenario types.
2. **MNAR missingness biases held-out evaluation, not just shrinks it.** Because Mechanism 1's
   missingness depends on the target variable itself, the *observed* `cardiac_stress`/
   `acute_deterioration` training and test rows are not a random sample of those scenarios' true
   severity distributions — they are skewed toward the lower-to-moderate end by construction. A
   held-out test accuracy/MAE computed only on the patients that happened to complete (as every
   metric in this document necessarily is) should not be assumed to generalize to the
   underrepresented high-severity population for these two scenario types specifically. This is a
   stronger and more precise claim than "the sample is small" (§8's existing bullet on this) — it
   is a directional bias, not just added variance.
3. **A bare completion rate conflates the two.** PerHeart's post-fix "13/16 (81%)" is entirely
   Mechanism 1 (3 crashes, 2-worker concurrency held constant, §8.4) — reporting it next to, say, a
   9-worker run's failure rate without noting the mechanism difference would misleadingly suggest
   a single "real-world reliability" number, when the two failure sources have nothing in common
   except both surfacing as `simulation_status="failed"`.

## 6. Risk Scoring Logic, With Clinical Citations

Per this project's locked Phase 0 decision, the primary risk scorer is a hand-tuned, interpretable
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

**Fixed.** `compute_risk_score()` gained a 6th input, `map_start` (already computed by
`analyze_simulation()` for every run, just not previously passed through), and a new
`baseline_deficit_score` sub-score using the same MAP anchors as `map_drop`. The final score is
`max(acute_score, baseline_deficit_score)` — a deliberate design choice (risk is driven by
whichever mechanism, acute or chronic, is worse) that leaves the 5 acute weights above completely
unchanged rather than diluting them into a 6-term reweight. Post-fix, `fluid_overload`'s mean
`risk_score` rose from 0.000 to 0.501 (close to its mean true severity of 0.580) and `risk_bucket`
shifted from 30/30 `LOW` to 29/30 `MODERATE`. Fine-grained ranking *within* `fluid_overload` is
still weak (r=−0.05) because Pulse's own scenario generation barely varies `map_start` with
severity for this scenario type — a separate, smaller, scenario-generation-level limitation, not a
regression of this fix. Full writeup: `models/model_card.md`,
`src/analytics/risk_score.py`'s module docstring.

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

**Phase 8** (full-pipeline batch validation, `scripts/validate_phase8.py`): 25 synthetic patients
(5 stratified per scenario type, `data/synthetic/patients.csv` rows `patient_id`s in
`data/validation_runs/20260709_063540/results.csv`) were run through the **live API** — not a
direct `run_pulse()` call like Phases 2/4 above — via `POST /patients` → `/clinical-report` → 21×
`/wearable-sync` (each patient's real synthetic 21-day wearable window, replayed day by day) →
`GET /status`, inside the Pulse Docker container, with zero mocking. This is the first time the
full production code path (ML Model 1 → `patient_builder` → `run_pulse()` → `simulation_features`
→ `risk_score` + `staging` → `deterioration_rate` → `project_physiology`, all orchestrated by
`src/api/services.py`) was exercised across a batch rather than a single hand-run patient.

**Headline result: 25/25 completed, zero crashes/timeouts.** This is notably better than Phase 4's
117/150 (78%) — including two patients above Phase 4's documented crash thresholds
(`cardiac_stress` at severity 0.831, `acute_deterioration` at severity 0.894, both ~0.2-0.3 above
where Phase 4 saw failures cluster). With n=5 per scenario here vs. n=30 in Phase 4, this reads as
a favorable small-sample draw rather than evidence the underlying Pulse instability (§4, §5) is
resolved — it does not contradict Phase 4's finding, just doesn't reproduce it at this sample size.

**Scenario classification agreement: 100% (25/25)** — the live classifier output matched each
patient's true `scenario_type` on every patient, consistent with (and slightly better than) the
offline 92.3% test-set accuracy (§5).

**Severity MAE: 0.271 — a real, diagnosed discrepancy from the offline 0.048 MAE, not just
expected live-vs-test noise.** Inspecting the per-patient predictions
(`data/validation_runs/20260709_063540/results.csv`) shows predicted severities compressed into a
narrow ~0.02-0.19 band for nearly every patient, regardless of true severity spanning 0.001-0.964
— most visibly in `fluid_overload` (true severities up to 0.964, every prediction still ~0.15-0.18)
and `acute_deterioration` (true up to 0.894, predictions ~0.17-0.19). Root cause, traced to
`src/scenario_classifier/features.py`: `build_features()` (used for offline training) computes
`nyha_ordinal` from each patient's real, varied `nyha_class` (I-IV); `build_inference_features()`
(used by the live pipeline, `src/api/services.py`'s `ml_row` dict) never includes `nyha_class` at
all, so it silently defaults to `"I"` (`build_inference_features` docstring: "a brand-new patient
won't have one yet"). Every single live-pipeline patient therefore gets the most-benign-possible
NYHA ordinal as an input feature regardless of their true class — a real train/inference feature
skew, not a bug in the classical sense: at genuine live-inference time, a NYHA class truly isn't
known yet (it's what `staging.py` computes *from* this pipeline's own output), so there's no
leakage-free way to give the live path what the offline training data had. This is a legitimate
structural gap between the modeling assumption ("nyha_ordinal is a fair feature") and the
deployment constraint ("nyha_ordinal doesn't exist yet at prediction time") that batch offline
evaluation on `patients.csv` alone could never have surfaced — only running the real pipeline did.
Notably, this did **not** measurably hurt scenario-type classification (100% agreement above),
only the continuous severity regression. **Fixed** — see §9 ("done" items): `nyha_ordinal` was
removed from the feature set entirely and both models retrained; live severity MAE re-measured at
0.008 post-fix (`models/model_card.md`), closing this gap.

**Risk bucket distribution vs. §6.1's offline expectations** — 4 of 5 scenario types reproduced the
documented pattern closely: `stable` and `deconditioning` were 5/5 `LOW` as expected;
`fluid_overload` was 5/5 `LOW` despite true severities up to 0.964 — an exact, independent
reproduction of §6.1's documented blind spot on real live-pipeline data, not just the offline
117-row batch; `cardiac_stress` was 4/5 `MODERATE` + 1/5 `HIGH` (0 `LOW`), matching the offline
"80% MODERATE / 20% HIGH" finding almost exactly. `acute_deterioration` was the one scenario that
didn't cleanly reproduce the offline pattern — 2 `HIGH`, 1 `MODERATE`, 2 `LOW`, with `risk_score`
not tracking true severity monotonically within this small sample (e.g. one severity-0.220 patient
scored `HIGH` while a severity-0.894 patient scored only `MODERATE`). Given the offline
within-scenario correlation for `acute_deterioration` was already the weakest of the improving
group (0.70, §6.1) and n=5 is small, this reads as expected noise rather than a new finding, but
is flagged rather than smoothed over.

**Timing:** total summed per-patient wall-clock was 8854s across 25 patients (mean 354s/patient ≈
5.9 min, each patient making up to 4 real Pulse calls sequentially within its own request); actual
elapsed wall-clock for the whole run was shorter than that sum, since `--workers 4` (the default)
ran 4 patients' pipelines concurrently.

### 7.X MIMIC-IV real-outcome test — baseline-deficit mechanism only, 2026-08-17

**Scope, stated up front so this cannot be misread as broader than it is: this tests exactly one
mechanism — `risk_score.py`'s `baseline_deficit_score` term, a pure function of `map_start` — against
real in-hospital mortality in a real MIMIC-IV cohort. It does NOT validate the full `risk_score.py`
output, the wearable-trend ML scenario classifier (Model 1), or the Pulse simulation layer. Those
remain untested against real-world outcomes** — this is additive to, not a substitute for, that
larger gap (§8/§9's "real clinical validation" item, still open for anything beyond this narrow
slice).

**Why the scope is this narrow, not broader.** This project's PhysioNet/BigQuery MIMIC-IV access
was confirmed dataset-wide (`physionet-data.mimiciv_3_1_hosp`/`mimiciv_3_1_icu`/
`mimiciv_3_1_derived`, project `ai-inventory-project`) via a schema-only `INFORMATION_SCHEMA`
check, no patient data pulled at that stage — see `docs/data_provenance.md`'s
`mimic_bigquery_extract` row. Checking what's actually derivable before building anything ruled
out the full pipeline:
- **Ejection fraction has no usable structured source.** A chartevents item exists
  (`mimiciv_3_1_icu.d_items.itemid = 227008`, "Ejection Fraction") but an aggregate count found
  **zero patients** with it actually charted. Real EF only exists in free-text echo reports, which
  live in the separate MIMIC-IV-Note resource (its own PhysioNet credentialing, not confirmed
  available here).
- **The 21-day ambulatory wearable-trend window Model 1 was trained on has no equivalent.**
  `steps_per_day`/`sleep_hours`/`hrv_rmssd_ms` are consumer-wearable metrics never captured in an
  EHR at all. And decisively: median hospital stay in this cohort is 3 days; only 2.9% of all
  546,028 hospital admissions even reach 21 days — so even HR/SpO2/weight can't honestly fill a
  21-day *ambulatory pre-crisis* window; what exists is a few days of *acute inpatient* vitals, a
  different measurement regime and a different population state entirely.

Running Model 1 → Pulse → the full `risk_score.py` on this data would have meant fabricating EF
(100% fallback) and most of the wearable-trend features on a windowing assumption the data
structurally can't support — rejected as exactly the "inventing proxies" this project's citation
discipline exists to avoid (`docs/data_provenance.md`). What MAP alone offers instead: it's a
single real, directly measured vital, available for essentially any ICU-admitted patient, and
`baseline_deficit_score` is a pure function of it — no Pulse simulation, no EF, no wearable window
required. That's the entire reason this specific mechanism, and only this one, was chosen for a
real-outcome test in this pass.

**Cohort** (`scripts/mimic_outcome_extraction.sql`, full query and inclusion criteria there):
HF admissions (ICD-9 `428.x` / ICD-10 `I50.x`) with ≥1 real MAP reading strictly within the first
24h of admission (the `map_start` guardrail — no later-stay vitals, to avoid predicting an
admission's outcome from data recorded after the fact). NT-proBNP was deliberately excluded
(diagnostic, not predictive, in an inpatient context — including it would confound a
single-mechanism test) and `discharge_location` was never selected as a feature (outcome-adjacent).
Not filtered by outcome. Because `mimiciv_3_1_derived.vitalsign` is an ICU-derived table, this
cohort is implicitly ICU-admitted HF patients, not every HF admission hospital-wide.

**Result** (`scripts/mimic_outcome_validation.py`, full output in
`data/mimic_outcome_validation/summary.md`):

- **n = 17,129 admissions, 13,047 unique patients** — exact count, no extrapolation. In-hospital
  mortality (event) rate 14.2% (2,430 deaths).
- **AUC = 0.596 (95% CI 0.585–0.608, percentile bootstrap, 2,000 resamples, seed=42)** for
  `baseline_deficit_score` alone predicting `hospital_expire_flag`. Modest, real, and clearly above
  chance (0.5) — for one hand-tuned component evaluated in isolation, not the full risk scorer.
- **Calibration is monotonic across score deciles**: observed mortality rises from 8.9% in the
  lowest-`baseline_deficit_score` decile to 21.2% in the highest, without inversions —
  directionally consistent behavior, not just a summary-statistic artifact.

**Honest limitations of this specific test** (see the summary doc for the full list):
population mismatch (an acutely ill, already-hospitalized ICU cohort — not this project's target
outpatient/home-monitoring population; a first-24h ICU MAP reflects that acute presentation, not a
stable ambulatory baseline); `map_start` here is a real measured value, whereas everywhere else in
this project it's a Pulse-simulated patient's baseline — same formula, different data-generating
process; admission-level rather than patient-level sampling (13,047 patients across 17,129
admissions mildly violates the AUC CI's independence assumption, uncorrected in this pass); and
only in-hospital mortality was tested — post-discharge mortality (`patients.dod`) and 30/90-day HF
readmission are flagged as future work, not pursued here.

## 8. Limitations

### Known Engine Constraints — the 180s Pulse-subprocess timeout, diagnosed 2026-08-17

**Finding: on this host, the timeout is not cleanly explained by either of the two hypotheses this
project previously had for it — session-length degradation, or the known high-severity
`Exercise`-action crash pattern. A third, more mundane explanation fits the evidence better: for
at least some scenario/severity combinations, the underlying Pulse call's real execution time
lands right at the 180s ceiling regardless of session freshness, making success/failure a matter
of small timing jitter rather than a deeper fault.**

**Method.** `src/api/services.py` calls `run_pulse(..., timeout_sec=180)` — this is the exact
ceiling being tested. Two admissions that failed with this timeout in the prior n=30 live
re-validation run (`data/validation_runs/20260812_184726_nyha_fix_revalidation/combined_results.csv`)
were re-attempted, one at a time, immediately after a **clean Docker Desktop restart** (the app
fully quit — confirmed by `docker ps` returning a connection error mid-shutdown, not just
`docker compose restart`ing containers — then relaunched and the stack brought back up healthy)
on a session that had only been running ~1 hour (not the multi-hour sustained load the original
degradation finding required):

| Patient | Scenario | Severity | Prior run (same session as the degradation finding) | This session, post-clean-restart |
|---|---|---|---|---|
| P0247 | `acute_deterioration` | 0.264 | **failed**, wall_clock_s=183.9 | **complete**, wall_clock_s=180.4 |
| P1043 | `fluid_overload` | 0.637 | **failed**, wall_clock_s=183.2 | **complete**, wall_clock_s=180.3 |

(Timestamps: this session's re-attempts ran 2026-08-17 ~13:41:50–13:45:00 IST (P0247) and
~13:45:26–13:48:26 IST (P1043); `scripts/reattempt_single_patient.py`'s per-10s status-poll log is
the source for the exact `wall_clock_s` figures above, and both runs' `error_message` was `None`.)

**Interpretation.** Neither original hypothesis fits cleanly:
- **Not (a) "resolved by the restart"** — if the prior failures were caused by resource
  degradation accumulated over a long session, a clean restart on a fresh (~1h-old) session should
  have produced a large timing improvement. It didn't: 180.3–180.4s here vs. 183.2–183.9s before —
  a ~3s difference, well within normal run-to-run jitter, not a meaningful recovery.
- **Not (b) "the known high-severity `Exercise`-action crash pattern"** — that mechanism
  (`docs/methodology.md`'s missingness section) is a **crash** (`PulseScenarioDriver exited 1`),
  concentrated in `cardiac_stress`/`acute_deterioration` scenarios *with an `Exercise` action*
  above ~0.45-0.6 severity, and fails fast. `P1043` is `fluid_overload` — a scenario type with no
  `Exercise` action at all (`src/patient_builder/scenario_file.py`) — and neither patient failed
  fast; both ran the full ~180s before resolving one way or the other. This is a different
  mechanism from the crash pattern, not a re-confirmation of it.
- **(c) — the actual finding**: both re-attempts landed within 0.1s of each other (180.3s,
  180.4s), and within ~3s of the original failures (183.2s, 183.9s) — a tight cluster right at the
  180s ceiling across two different scenario types and severities. This is consistent with these
  specific scenario/severity combinations simply taking close to 180s of real wall-clock time to
  simulate under this host's `arm64`→`amd64` emulation, independent of session freshness — meaning
  `timeout_sec=180` has very little margin here, and whether a given call lands on the "complete"
  or "failed" side of that line is sensitive to ordinary host-load jitter, not a sign of
  progressive degradation or a scenario-specific engine crash.
- **Not the same host as the original degradation finding, worth stating explicitly**: the
  original WSL2-level degradation observation (`data/validation_runs/20260812_184726_nyha_fix_revalidation/summary.md`)
  was made on a Windows/WSL2 Docker Desktop host; this session's host is macOS (Apple Silicon,
  Docker Desktop's native virtualization, not WSL2). This re-attempt neither confirms nor refutes
  the WSL2-specific degradation hypothesis on its original platform — it only establishes that on
  *this* platform, timeouts occur even on a fresh session, which is a related but distinct finding.

**n=2 caveat, stated plainly**: this is two re-attempts, not a powered experiment. It's enough to
rule out "clean restart reliably fixes it" as a strong effect on this host, and enough to show the
failure isn't confined to the known crash-prone scenario/severity combinations — but not enough to
rule out degradation being a *contributing* factor at a smaller magnitude, or to fully characterize
the timing distribution. Treat this as a diagnosis of the dominant mechanism on this host, not a
closed investigation.

**Practical consequence for Steps 2/3 of this session's batch**: timeouts should be expected to
recur at a low but nonzero rate during the PerHeart re-run and live-revalidation top-up — not
because Docker/the session is degraded, but because at least some scenario/severity combinations
are intrinsically close to the 180s ceiling on this host. This is flagged explicitly per your
instruction not to let a partial run's cause go unstated: any failures in Steps 2/3 with
`wall_clock_s` in the ~178-190s range should be attributed to this timing-margin issue, not
assumed to indicate degradation or a data problem.

### Known Engine Constraints — Exercise-action instability at high severity, root-caused 2026-08-17

**This is a characterized, root-caused limitation, not an unexamined observation.** Every prior
mention of this failure mode in this project (Phase 4's batch results, the missingness analysis
above) described it structurally — which scenario types and severities it clusters in — without
tracing the actual failure mechanism or testing whether it was something this project's own
scenario-construction code controlled. This session did both: pulled the real Pulse engine logs
for independent crashes, and tested four concrete interventions against a reproducible control.
The conclusion is a genuine, evidenced boundary characterization, not a restated guess.

#### Mechanism

Pulled the live `.log` file Pulse itself writes on failure (`src/pulse_runner/runner.py`'s
`_expected_paths()` — a file this project's own crash-detection code already scans for fatal
markers, but had not previously been read for the actual causal chain) for three independent
crashes. All three show the identical sequence:

```
t=60s   CardiovascularMechanicsModification (disease/severity modifiers) fires
t=60s   Exercise fires -- SAME simulated instant, zero AdvanceTime gap between them
t=60.02-84.6s   Fatigue -> Hypoxia + Hypoglycemia -> Tachycardia -> Tachypnea
t=~148-150s     Renal Hypoperfusion -> CardiovascularCollapse ("low blood pressure and the
                vasculature has collapsed") -> BrainOxygenDeficit
t=~154s   FATAL: "Can't transport with a negative volume included. Node = [Left|Right]Heart.
          Volume = [-1769.85 | -3825.99 | -4541.67] mL"
t=~154s   [Event IrreversibleState 1] Patient has entered irreversible state
```

**This is explicitly a hard numerical divergence in Pulse's own circulatory transport solver, not
a soft warning or a data-quality artifact.** The engine's own `[FATAL]`-tagged log line reports a
simulated heart chamber's blood volume going thousands of milliliters *negative* — a physically
impossible state the solver cannot recover from, immediately followed by the engine's own
`IrreversibleState` event and process termination (`PulseScenarioDriver exited 1`, the exact
signature `src/pulse_runner/runner.py`'s crash detection already catches, just without previously
knowing *why*).

#### Reproducibility — deterministic, not stochastic

Three independent crashes (different patients, different exact severities: 0.582, 0.731, 0.884;
scenario types `cardiac_stress` and `acute_deterioration`) all reached `IrreversibleState` within a
**154.1-154.32s** window — a 0.22-second spread across independently-run simulations. This tight
clustering is evidence of a deterministic failure given these inputs, not stochastic/numerical
noise that happens to fail sometimes — consistent with a real physiological boundary being
crossed at a repeatable point in the simulated timeline, not a flaky engine.

#### Hypotheses tested and ruled out

Using one fully reproducible crashing case as a control (a `acute_deterioration`, severity=0.731
patient — `StrokeVolumeMultiplier=0.817`, `SystemicResistanceMultiplier=SystemicComplianceMultiplier=0.89`,
`VenousComplianceMultiplier=0.634`, `HeartRateMultiplier=1.293`, `Exercise Intensity=0.439`), four
interventions were tested by directly constructing and running modified Pulse scenario JSON
(`PulseScenarioDriver` invoked directly inside the container, bypassing the API, for controlled
single-variable tests):

| Intervention | Result |
|---|---|
| Control (exact reproduction) | crashes @ 154.32s |
| 60s stabilization gap inserted between disease modifiers and Exercise | **still crashes**, @ 212.02s — delayed by ~60s, i.e. by ~exactly the gap length |
| 120s gap | **still crashes**, @ 272.92s — delayed by ~120s, same pattern |
| Exercise intensity ramped gradually in 4 steps (0.11→0.22→0.33→0.439 over 2 min, after a 60s gap) | **still crashes**, @ 301.14s |
| Exercise action alone, same intensity (0.439), disease modifiers and `ChronicVentricularSystolicDysfunction` condition both removed | **completes clean**, full 660s |
| Disease modifiers + condition alone, no Exercise action | **completes clean**, full 660s |
| Exercise intensity halved (0.439→0.2195), disease modifiers unchanged, same simultaneous timing as control | **completes clean**, full 660s |

**Ruled out: timing/stabilization gaps.** Both the 60s and 120s gaps only postponed the crash by
almost exactly the gap length (212.02s ≈ 154.32s + 60s minus a few seconds; 272.92s ≈ 154.32s +
120s minus a few seconds), not prevented it. This rules out an instantaneous step-change "shock" as
the cause — the system doesn't fail because the two stressors arrive simultaneously, it fails
because it cannot *sustain* their combined steady-state demand, however gently that demand is
approached.

**Ruled out: gradual ramping.** The 4-step ramp (which combines a gap AND gradual intensity
increase) also just delayed the crash further (301.14s) rather than preventing it — reinforcing the
same conclusion: this is a sustained-load problem, not an onset-shock problem.

**Ruled out: either stressor alone.** Exercise at the *exact* crash-causing intensity (0.439) runs
cleanly on a structurally normal heart (no disease modifiers). The disease-modified state runs
cleanly with no exertion at all. **Only the combination — a moderately-reduced-EF-driven
cardiovascular state plus a nontrivial sustained exercise demand — is unsustainable.** This
directly confirms the compounding-stressors hypothesis, with an actual isolation experiment behind
it rather than an assumption.

**Confirmed (not ruled out): intensity-dependence, but not via a fixed constant.** Halving Exercise
intensity at the control patient's exact disease severity did prevent the crash. But testing the
same intervention on a second, independently-crashing patient (`cardiac_stress`, severity=0.582,
`StrokeVolumeMultiplier=0.767`, `SystemicResistanceMultiplier=SystemicComplianceMultiplier=0.86`,
`HeartRateMultiplier=1.175`, original `Exercise Intensity=0.5`) found a **different, lower**
threshold:

| Patient | Severity | Scenario | Crashes at | Safe at |
|---|---|---|---|---|
| 1 (control) | 0.731 | `acute_deterioration` | 0.439 (original) | 0.2195 (half) |
| 2 | 0.582 | `cardiac_stress` | 0.5 (original), 0.35, **0.25** | 0.125 (quarter) |

**Patient 1's safe threshold is approximately 0.22; patient 2's is somewhere between 0.125 and
0.25 — clearly lower than patient 1's, despite patient 2's disease modifiers being nominally less
aggressive** (higher `StrokeVolumeMultiplier`, less-reduced resistance/compliance). **The safe
Exercise intensity threshold is patient/severity-dependent, not a single fixed constant** — this
project's actual `MAX_EXERCISE_INTENSITY=0.5` cap (`src/patient_builder/scenario_file.py`) sits
above both patients' crash points, and no single lower constant tested is confirmed safe for both.

**This is evidence of the shape of the constraint, not a complete map of it.** n=2 patients, 2
severities, 2 scenario types (of the 2 that use `Exercise` at all) is enough to establish that the
threshold moves with severity/patient body in a nontrivial way, and enough to rule out the simpler
hypotheses above — it is not enough to derive a safe universal constant or a validated
severity-adaptive formula. A systematic sweep (below) would be needed for that, and was not
attempted here per the explicit scope of this session's investigation.

#### Practical handling for the batch pipeline — no cap currently applied beyond `MAX_EXERCISE_INTENSITY=0.5`

**No additional intensity cap or crash-avoidance logic has been added as a result of this
investigation** — per the explicit instruction this section was written under, no fix was
attempted or implemented this session. The existing `MAX_EXERCISE_INTENSITY=0.5` constant already
in `scenario_file.py` predates this investigation and was set for a different reason (engine
stability at a coarser level, per that constant's own existing comment) — it is not a validated
safe threshold in light of this session's finding that both test patients crashed at or below it.

**Current failure handling, unchanged by this investigation**: `src/pulse_runner/batch_runner.py`
catches `PulseExecutionError` per-run, records `status="failed"` with the error string, and
continues the batch (`failed_runs.csv`) — no retry, no intensity adjustment. The live API path
(`src/api/services.py`) does the same per-patient (`SimulationRun.status="failed"`). Validation
scripts that do retry once (e.g. `scripts/perheart_real_data_replay.py`'s `attempt=2` pattern)
retry the *identical* scenario — given this session's finding that the failure is deterministic
(three independent crashes landing within a 0.22s window), **that retry is not expected to help for
this specific failure mode**, and empirically hasn't: every crash observed this session that fits
this pattern failed identically on retry. This is a real gap between what the retry logic assumes
(transient failure) and what this investigation found (deterministic failure) — worth knowing, not
itself a fix.

**If a conservative cap is applied in the future**, it must be labeled explicitly as an
**operational mitigation** (a value chosen to reduce crash *frequency* in practice), **not a
derived safe threshold** — this investigation did not establish one. The known tradeoff: any cap
low enough to sit safely below patient 2's proven-unsafe 0.25 (i.e., informed by this session's
data, something meaningfully below 0.125 for real margin) would compress the Exercise-driven
HR/CO signal across the entire top end of the `cardiac_stress`/`acute_deterioration` severity
range — weakening exactly the signal these two scenarios exist to provide, since severity
discrimination in both partly relies on the magnitude of exercise-driven hemodynamic response.

#### Future work — a well-scoped systematic sweep, not attempted here

To actually characterize the safe boundary (rather than two anecdotes) would need a sweep across:
**severity** (the affected range is roughly 0.45-1.0 per the missingness analysis above, e.g. 6
points), **scenario type** (`cardiac_stress` and `acute_deterioration`, the only 2 with `Exercise`
— 2 values), **patient profile** (age/sex/BMI combinations affect body composition and therefore
the crash threshold, per this session's n=2 finding that nominally-milder modifiers didn't mean a
higher threshold — at least 4-6 representative profiles), and **intensity** (a binary-search-style
sweep per severity/scenario/profile combination, ~4-5 Pulse calls to bracket a threshold to
reasonable precision). Rough scope: 6 severities × 2 scenarios × 5 profiles × ~5 calls to bracket
≈ 300 Pulse calls. At this session's observed per-call timing (~150-300s for a completing run, up
to ~300s for one that crashes), that's roughly **12-25 hours of real Docker/Pulse wall-clock time**
at the empirically-safe low concurrency this project already uses for batch work — a real,
schedulable follow-up, not a vague "someday," but deliberately out of scope for this session's
diagnostic pass.

### `fluid_overload` Risk-Score Limitation — EF Tier-1 Fallback Masking, diagnosed 2026-08-17

**The `fluid_overload` fix (`baseline_deficit_score`, §6.1) doesn't transfer to a real patient
whose ejection fraction is unmeasured and Tier-1-fallback-defaulted.** Root-caused, not just
observed, via a live re-run of the one real PerHeart `fluid_overload` case (`docs/
real_world_data_integration.md` §8.5) — not inferred from the code alone.

#### Mechanism

`baseline_deficit_score` (§6.1) needs the Pulse-simulated body to reflect a congested, diseased
structural state, which needs a real, disease-appropriate `ejection_fraction_pct` input
(`ef_to_cardiovascular_modifiers()`, `src/patient_builder/patient_file.py`). When EF is unmeasured
and Tier-1-fallback-defaults to the healthy-population mean (`apply_tier1_fallback()`,
`src/api/services.py`), Pulse simulates a structurally *normal* heart instead — so `map_start`
comes out at/near the healthy baseline regardless of what the wearable-trend classifier assigns as
`scenario_type`/`severity`, and `baseline_deficit_score` has nothing to detect.

#### Evidence

Confirmed directly against the live API's `/report` output for PerHeart's user_27
(`fluid_overload`, severity 0.518): `ejection_fraction_pct: 62.0` — an exact match to
`reference_stats.yaml`'s `ejection_fraction.healthy.mean` (62), not a coincidence. `risk_score`
and every `component_scores` entry read exactly `0.0`. Cross-run comparison confirmed zero change
from the pre-fix baseline: run 2 (pre-fix) and run 3 (post-fix) both show this same patient at
`risk_score=0.000`/`LOW`, to 4 decimal places — the fix had no measurable effect on this real case
(`docs/real_world_data_integration.md` §8.5).

#### Boundary characterization — confirmed narrow, not assumed

Checked against both real-world and synthetic data, not asserted: PerHeart's cohort has exactly
**one** `fluid_overload` case across all 3 runs to date (user_27) — every other completed patient
is `cardiac_stress`/`stable`, scenarios this mechanism doesn't touch. The 2,000-patient synthetic
batch has **zero** null-EF rows (synthetic patients always carry a real, generated EF), so this
masking condition cannot occur there via the normal pipeline. This is the honest current shape of
the data, not an artificially narrow check.

#### Practical handling — messaging fix applied, underlying limitation still open

**What was fixed this session (§8.5.1 of `docs/real_world_data_integration.md`): the
`risk_caveats` message now names this exact mechanism** (`src/api/services.py`'s
`EF_FALLBACK_MASKS_FLUID_OVERLOAD_CAVEAT_MESSAGE`) instead of showing the stale, generic pre-fix
warning — verified firing correctly against a live re-run of user_27. **This is messaging only, an
operational mitigation for interpretability, not a fix for the underlying limitation.** A real bug
was found and fixed in the process (`ef_is_fallback` was being wrongly re-derived downstream
instead of reusing the already-stored value — full account in that same section).

#### Future work

The underlying limitation remains open: a real EF measurement (echocardiogram) or a validated
non-invasive EF proxy is the actual fix, and was not attempted here — scope and feasibility not
assessed as part of this pass.
- **The live-pipeline severity regressor underperforms its offline benchmark by a diagnosed, real
  margin: MAE 0.271 live vs. 0.048 offline (§7, Phase 8 batch validation).** Root cause:
  `build_inference_features()` (`src/scenario_classifier/features.py`) always defaults
  `nyha_ordinal` to the most-benign class (`"I"`) at live-inference time, because a genuinely new
  patient's NYHA class isn't known until *after* this pipeline runs — whereas offline training used
  each patient's real, varied `nyha_class`. Scenario-type classification was unaffected (100%
  agreement across 25 live patients); only the continuous severity value is degraded. Not
  discoverable from offline batch evaluation alone — see §9 for the concrete fix this points to.
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

Everything below is a real candidate for continued work, not a padded wishlist — each item is
either an explicit Phase 9 stretch goal from the original roadmap that Phases 0-8 deliberately
didn't need to solve, or a next step toward the team's stated goal of turning this system into a
research paper once the pipeline is validated end-to-end (§7/§8).

**Directly motivated by the Phase 8 validation findings (§7, §8):**
- **DONE — retrained the severity regressor (and classifier — one shared feature matrix, see §5)
  without `nyha_ordinal`.** The diagnosed 0.271-vs-0.048 MAE gap was a train/inference
  feature-availability mismatch, not noise; removing the feature entirely (rather than defaulting
  it at inference time) closed it. Offline cost was small: test accuracy 92.3% → 90.7%, severity
  MAE unchanged (0.048 → 0.047). Re-validated live against 5 real synthetic patients with known
  ground-truth severity (one per scenario type): **live severity MAE 0.008** (down from 0.271),
  scenario classification 5/5 correct — see `models/model_card.md` and
  `data/validation_runs/nyha_fix_live_revalidation.csv`. This was independently motivated by, and
  fixes, the same signature reproduced on real PerHeart data
  (`docs/real_world_data_integration.md` §8.2). Done with the repo owner's explicit sign-off,
  satisfying the hold noted in the previous revision of this section.
- **Expand the batch validation beyond n=5/scenario** — `acute_deterioration`'s risk-bucket
  distribution didn't cleanly reproduce the offline pattern at this sample size (§7); a larger
  batch (e.g. matching Phase 4's n=30/scenario) would distinguish real signal from small-sample
  noise before this becomes a claim in a paper. **Not done yet because it costs several more hours
  of Docker wall-clock time (Phase 4's 150-run batch took ~90 min even parallelized) for a
  confirmatory result, not a new finding — worth scheduling deliberately rather than run ad hoc.**

**Deferred engineering (Phase 9, roadmap-defined):**
- **Tier 2 personalization** (echo/PPG-derived vascular compliance) — see §3 for exactly why it
  was never load-bearing for Phases 0-7's results; still a legitimate accuracy lever if a suitable
  echo/PPG dataset is acquired.
- **Self-calibrating baseline** — currently a patient's Pulse-input parameters are set once at
  onboarding and never adjusted; comparing the twin's predicted vitals against a patient's actual
  incoming wearable readings and iteratively correcting the baseline would make the simulation
  converge toward that specific patient over time, rather than staying fixed at intake values.
- **Real task queue (Celery/Redis)** in place of FastAPI's `BackgroundTasks` thread pool — see the
  Limitations entry in §8; only matters at a patient volume beyond this prototype's scale.
- **Full-stack containerization** (`Dockerfile`/`docker-compose.yml` covering the API, database,
  and frontend together, not just the Pulse engine) and **basic CI** (running the existing 135+
  pytest suite on every push) — neither changes system behavior, both materially improve the
  project's reproducibility and credibility as an artifact, including for a research-paper
  submission's own review process.

**Clinical and modeling scope, deferred deliberately:**
- **Tier 3 (ECG-derived blood pressure/contractility) — locked out permanently, not deferred.**
  This is listed here only for completeness, per the Phase 0 locked decision: it should never be
  implemented, because the underlying ECG-to-hemodynamics formulas were never validated against a
  real dataset in this project and would introduce unfounded precision into the pipeline.
- **Medication-effect modeling** — diuretics, beta-blockers, and ACE inhibitors materially change
  HF physiology and are not represented in any current Pulse scenario; nearly all real HF patients
  are on at least one of these, so this is one of the more consequential gaps for real-world
  applicability (see also the medication-modeling Limitation in §8).
- **Real clinical validation** — every result documented in §5-§7 (aside from §7.X's narrow
  MIMIC-IV baseline-deficit test, 2026-08-17) is validated against synthetic data, offline batch
  simulation, or a single manually-run live pipeline, never against real patient outcomes. §7.X
  closes a real slice of this for one mechanism, using a retrospective ICU cohort — it does not
  close the rest: the full risk scorer, the wearable-trend ML classifier, and the Pulse simulation
  layer remain untested against real-world outcomes, and even §7.X's own population (retrospective,
  already-hospitalized ICU patients) doesn't match this project's target outpatient/home-monitoring
  use case. A partnership with a cardiology department to compare the twin's risk/staging output
  against actual clinician assessments and real deterioration events *in that target population,
  prospectively* is still the single most important next step before any claim in this project
  could support a peer-reviewed research paper rather than a systems-engineering demonstration.
  Two concrete extensions of the MIMIC-IV angle specifically, not pursued in this pass: (a)
  post-discharge mortality via `patients.dod` (needs confirming MIMIC-IV's per-patient date-shifting
  preserves valid day-deltas before relying on it) and (b) 30/90-day HF-cause readmission via
  repeat `hadm_id`s per `subject_id` (needs an ICD-based definition of "HF-caused" readmission,
  more design work than the in-hospital-mortality outcome used here).
- **Extending beyond heart failure** — the same wearable-trend → scenario-classification →
  Pulse-simulation → risk-scoring architecture is not HF-specific in its mechanics; COPD,
  post-surgical recovery monitoring, and diabetes management were identified as plausible targets
  for the same pipeline, contingent on defining an analogous scenario taxonomy and risk formula for
  each condition — not attempted here.

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

## 11. Frontend Extension — Trends & History, Simulation Lab, Reports, Settings

**Status: done.** Full detail, including exactly what was verified and how, is in
`docs/frontend_extension_validation.md` — this section summarizes the design decisions; that
document carries the evidence.

Phase 7 (§10) shipped a 5-item sidebar, but only "Patient Dashboard" was wired to real content —
the other four items were static labels with no click handler. This phase makes all five
functional:

- **Trends & History** — a risk-score-over-time chart, a full assessment history table, and
  per-vital trend charts over the synced wearable window. Needed one small backend addition,
  `GET /patients/{id}/wearable-history` (`src/api/routes.py`), since the only prior read path for
  wearable data was `StatusResponse.latest_wearable` — a single most-recent row, not the series a
  trend chart needs. New reusable `TrendChart` component (hand-built SVG, not a charting library
  dependency) with a hover crosshair + tooltip, matching this project's existing "small,
  dependency-light frontend" convention (§10: "plain fetch/hooks (no React Query — kept
  dependencies minimal)").
- **Simulation Lab** — a patient-creation wizard (demographics → optional clinical report → a
  21-day wearable trend) that drives the real API end to end, so a new patient can be created from
  the UI itself rather than only via `curl`/Swagger/a throwaway script. The 21-day trend is
  generated client-side (`frontend/src/utils/syntheticTrend.js`, linear interpolation between a
  start/end vitals snapshot with light noise, 4 presets) — explicitly a UI convenience for demoing
  the pipeline, not a replacement for `src/data_synthesis/`'s cited, real-data-grounded population
  generator. The same page also surfaces the selected patient's raw `component_scores` breakdown
  (`hr_rise`, `map_drop`, `co_drop_pct`, `compensation_flag`, `instability_flag`) as meters —
  the same 5 features `risk_score.py` consumes (§6.1), now visible rather than only present in the
  API response.
- **Reports** — a master-detail view across all patients, reusing the existing `DoctorReportCard`
  component (copy/download already built in Phase 7) rather than duplicating its report-text logic.
- **Settings** — a working dark/light/system theme toggle (persisted, respects
  `prefers-color-scheme` when unset) and a live "Test Connection" check against the real backend
  (round-trip latency, not just a static URL display).

**Dark mode implementation note.** The existing palette used `--navy`/`--navy2` for two unrelated
things: body text color, and the fixed-dark backgrounds of surfaces meant to stay dark in *both*
themes (the sidebar, the doctor-report card, primary buttons). New `--text`/`--text2` tokens were
added specifically so flipping the theme changes only text color, not those intentionally-fixed
dark surfaces. Manual dark-mode QA caught and fixed one real bug this introduced risk for: three
SVG elements (`TrendChart`'s gridlines/dot-rings, `SeverityGauge`'s track circle) had hardcoded
light-mode hex strokes that rendered as blown-out bright lines against the dark background —
switched to the new CSS custom properties. Full detail in
`docs/frontend_extension_validation.md` §4.1.

**Verification.** `npm run build`/`npm run lint` clean; `pytest tests/` at 137/137 (135 + 2 new
`GET /wearable-history` checks); manual, real-browser click-through of all 5 tabs in both themes
against the live `docker compose` stack, including a full no-mocking test of the Simulation Lab
wizard (a real patient created purely through UI form interaction, confirmed reaching the same
`collecting → pending → running` state machine §10 already documents); zero browser console
errors. See `docs/frontend_extension_validation.md` for the full evidence trail, including a
real, unrelated infrastructure bug this work depended on fixing first (§4.2 of that document: the
background pipeline crashing with `FileNotFoundError` on a fresh `docker compose up --build`
because the trained `.joblib` models are gitignored and not volume-mounted, only baked in at image
build time — now also captured in `docs/running_the_stack.md`'s Troubleshooting section).
