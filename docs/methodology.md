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
   compliance term) reached 90.7% test accuracy and severity MAE 0.047 (§5, current baseline) —
   comfortably past the informal >80% target the roadmap set for this model. Tier 2 was never
   load-bearing for a result the system actually needed to hit; adding it would have been
   complexity without a corresponding accuracy gap to close.

Tier 2 therefore remains exactly what it was scoped as — optional and unimplemented — not a cut
scope item disguised as a stretch goal. It is listed again in §9 as legitimate future work, since
an echo/PPG-derived compliance term is a real, literature-supported way to sharpen the digital
twin's cardiovascular personalization if a suitable dataset is later acquired.

**Update:** §12 documents a since-built, related-but-distinct extension — a real vascular-
compliance term driven by ballistocardiography (BCG), substituted for the echo/PPG data that was
still never acquired. This does not retroactively count as Tier 2 being built (BCG is a different
signal from what Tier 2 specified), but it is the closest this project has come to a real, non-EF
vascular-personalization input.

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

### 4.1 Cardiac waveform panel — ECG trace + pressure-volume (PV) loop, added 2026-08-28

Pulse's cardiovascular model is a real, mechanistic time-varying-elastance heart model — it
tracks the same underlying volume/pressure/electrical-activity signals a real cardiologist would
read off a bedside monitor, not just the 8 summary scalars this project extracted through Phase 7.
This addition surfaces two of those signals (an ECG trace and a pressure-volume loop) on the
dashboard and in the clinical summary report, without changing any existing scenario/risk logic.

**Discovery, same discipline as everything else in this section — verified empirically against
the real engine, not assumed from docs.** None of `LeftHeartPressure`/`LeftHeartVolume`/
`LeftVentricularVolume` exist as top-level `Physiology` scalars (all three fail with "Unhandled
data request"); `GasCompartment`/`LeftHeart` fails too ("Unknown gas compartment" — the heart is a
liquid, not gas, compartment). The properties that actually parsed with zero engine errors:

```
{"Category": "LiquidCompartment", "CompartmentName": "LeftHeart", "PropertyName": "Volume"}
{"Category": "LiquidCompartment", "CompartmentName": "LeftHeart", "PropertyName": "Pressure"}
{"Category": "ECG", "PropertyName": "Lead3ElectricPotential"}
```

A controlled test run (stable scenario, EF=45%) confirmed real, physiologically plausible output,
not a repeat of the `OxygenSaturation` flat-0.0 problem above: `LeftHeart-Volume(mL)` ranged
62.2–143.0 (matches real LV end-systolic/end-diastolic volume ranges), `LeftHeart-Pressure(mmHg)`
ranged 5.8–136.8 (matches real diastolic-filling-to-peak-systolic range), and the ECG trace showed
a clean, repeating QRS-like spike at the patient's simulated heart rate. A second live run through
the full production pipeline (real patient, EF=32%, `fluid_overload`) showed a larger
`LeftHeart-Volume` range (up to ~281mL) than the EF=45% test case — the expected direction for a
more dilated, lower-EF heart, a useful physiological cross-check that the signal is behaving
correctly, not just present.

**What's extracted and shown**: `src/analytics/simulation_features.py`'s `extract_waveform_data()`
takes the steady-state window from the *end* of the run (matching every `_end` feature elsewhere
in this file) — one full cardiac cycle for the PV loop, the last 3 cycles for the ECG trace (one
cycle alone reads as an ambiguous single spike; 3 reads as a recognizable rhythm strip). Stored on
`SimulationRun.waveform_data` (new nullable JSON column, 2026-08-28 — existing rows predate it and
correctly report no waveform data rather than a fabricated one), served via
`GET /patients/{id}/status`'s `waveform_data` field, rendered by
`frontend/src/components/waveform/CardiacWaveformPanel.jsx`.

**What is deliberately NOT claimed.** The dashboard/report shows only numbers derived directly
from the same waveform data by simple arithmetic (stroke volume = loop's volume range, pulse
pressure = loop's pressure range, implied HR = 60/cycle duration) — no interpretation of loop
*shape* (e.g. "this loop's morphology indicates diastolic dysfunction") is made anywhere. That
kind of claim would need real validation against echocardiographic ground truth this project
doesn't have, and is exactly the category of unvalidated clinical inference this project has
already declined to make elsewhere (Tier 3 ECG-to-hemodynamics, §3; the BNP→EF proxy, §8's
`fluid_overload` subsection) — the same standard applied consistently, not relaxed for a feature
that happens to look visually impressive.

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

**Results (held-out test set, 300 patients), current baseline:** 90.7% scenario accuracy (macro
F1 0.91), severity MAE 0.047 / RMSE 0.061. Full classification report and confusion matrix are
written to `models/phase3_eval_report.txt` on every training run (small text file, committed as
evidence; the `.joblib` model weights and `.png` plots alongside it are gitignored and regenerated
with `python3 -m src.scenario_classifier.train`). Notably, `cardiac_stress` (HFpEF-profile,
preserved EF) and `acute_deterioration` (HFrEF-profile, low EF) — the pair Phase 2's Pulse
validation (§4, `cardiac_stress` vs `acute_deterioration` table) found hardest to distinguish from
HR/MAP time series alone — are cleanly separated here (1–4 misclassifications out of ~60 each
way), because `ejection_fraction_pct` is directly available as an input feature to this model,
unlike the Pulse-output-only comparison in Phase 2.

*(Note added 2026-09-10, while investigating a "give the classifier rolling-window context"
proposal ("Option A"): this section previously stated 92.3% / MAE 0.048 / RMSE 0.063 as the
"current" result well after that number had stopped being reproducible. That original figure was
real, not a documentation error — it was the true held-out result for the 30-feature version of
this model that included `nyha_class` as an ordinal feature. Removing `nyha_ordinal` from
`CLINICAL_FEATURE_COLUMNS` (§9 "done" items, commit `064f742`, 2026-08-03) fixed a much larger
live train/inference mismatch — severity MAE 0.271 live vs. 0.048 offline, because a brand-new
patient's real NYHA class isn't knowable at inference time and was silently defaulted — at a small,
deliberately-accepted offline cost: test accuracy 92.3% → 90.7%, severity MAE effectively
unchanged (0.048 → 0.047). That trade-off and its rationale were already recorded correctly in §7
and §9 below (and in `models/model_card.md`), including the delta shown in `git show 064f742 --
models/phase3_eval_report.txt`, which is the actual committed evidence for 90.7%/0.047/0.061 — but
this §5 headline line, and the Tier-1-sufficiency argument in §1, were never updated to match and
kept citing the pre-fix number as if current. Found and corrected here after Option A's mandated
held-out re-validation (see below) compared its new numbers against this stale 92.3%/0.048/0.063
figure and couldn't reproduce it even with the unmodified, pre-Option-A feature set — reproducing
instead the exact 90.7%/0.047/0.061 / confusion matrix already sitting in
`models/phase3_eval_report.txt`. No dataset regeneration and no split-logic change were involved.
Separately, note the committed `models/phase3_eval_report.txt` as of commit `5e99cde` reads 91.3%
test accuracy — with zero code or data changes between that commit and `064f742`'s 90.7%, so
`RandomForestClassifier`/`RandomForestRegressor` with a fixed `random_state=42` is not perfectly
reproducible across different scikit-learn/numpy environments; the spread observed so far is
small and bounded (~1 point of test accuracy), known, and not investigated further.)*

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
(scenario_type) — not just on scenario_type alone, which would be MAR. Later, independent runs
reproduce the identical signature repeatedly: PerHeart's post-fix re-run (§8.4) lost 3
previously-clean patients to the exact same `exited 1` crash after a severity-model retrain
changed their predicted severity; and the live re-validation sample, expanded across three
sessions to n=50 attempted (**n=45 completed**, §9 "Statistical power" update below), now has
**5 confirmed deterministic failures** — `P1035` (`cardiac_stress`, severity 0.914), `P1476`
(`cardiac_stress`, 0.602), `P1646` (`acute_deterioration`, 0.765), `P1840` (`cardiac_stress`,
0.626), `P1978` (`acute_deterioration`, 0.675) — every one high-severity
`cardiac_stress`/`acute_deterioration`, every one failing in ~30-62s (far short of the 900s poll
ceiling), a fast subprocess crash, not a slow timeout, consistent with Mechanism 1 rather than
Mechanism 2 below. **These 5 are additional observed instances of the exact mechanism already
root-caused in "Known Engine Constraints" (§8) — not a new or different failure pattern**; that
section has the full causal trace (the actual engine log evidence, not just this statistical
signature), which this paragraph doesn't repeat.

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
92.3% offline test-set accuracy this model had at the time of this run (§5's headline number as of
this Phase 8 validation, pre-dating the `nyha_ordinal` removal fix below and §5's current
90.7% baseline).

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

### 7.Y Zigong heart-failure cohort real-outcome test — baseline-deficit mechanism only, composite
### outcome, 2026-09-11

**Scope, stated up front exactly as §7.X's is: this tests the SAME one mechanism as §7.X** —
`risk_score.py`'s `baseline_deficit_score` term, a pure function of `map_start` — against a real,
independent, second cohort (PhysioNet, DUA-signed, restricted access: "Hospitalized patients with
heart failure: integrating electronic healthcare records and external outcome data", v1.3, Zigong,
China), this time against a broader composite outcome (death-or-readmission within 6 months). It
does **not** validate the full `risk_score.py` output, Model 1, or the Pulse simulation layer —
same gap as §7.X, still open.

**Why LVEF/NYHA/BNP — all present and reported descriptively in this dataset — are not fed into
this test.** Checked before building anything: no existing function in this codebase maps
(LVEF, NYHA, BNP) → `risk_score` or severity. `risk_score.py`'s 5 acute-change features
(`hr_rise`/`map_drop`/`co_drop_pct`/`compensation_flag`/`instability_flag`) are all Pulse-simulated
encounter outputs, and this dataset is a single per-admission EHR snapshot — no encounter to
simulate. `staging.py`'s `classify_nyha()` runs the opposite direction (EF/BNP +an already-computed
`risk_score` + `instability_flag` → NYHA class, not the reverse). Model 1 needs a 21-day
ambulatory wearable-trend window this dataset structurally cannot supply — fabricating one would
be exactly the "inventing proxies" pattern §7.X already rejected for MIMIC-IV, for the same reason
(no EF there either). Building a new LVEF/NYHA/BNP proxy scorer was raised and explicitly declined
for this pass (repo owner's call, 2026-09-11) — real modeling work requiring its own citations, not
a measurement of what already exists. `map_start` (this dataset's `map` column, mean arterial
pressure, 0% missing) is the only field with an existing, unmodified, non-fabricated path into any
of this project's real-valued outputs — the same one §7.X already used, which is exactly why this
is a genuine second test of that one mechanism, not a new one.

**Cleaning** (`scripts/zigong_outcome_validation.py`), rules agreed before computing anything,
individually and combined, on n=2008 raw admissions: `pulse`==0 (1 row), `respiration`==0 (1),
`systolic.blood.pressure`==0 (3), `height`<1.0m (4), `BMI`>60 (4) — union of all five, 7 rows
dropped (some overlap across rules) → **n=2001 after cleaning**.

**Cohort:** complete-case (LVEF + NYHA + BNP + all 6 binary outcome flags present), built from the
cleaned data — **n=625** (the pre-cleaning reconnaissance figure was 626 on raw n=2008; cleaning
removed exactly one row that also happened to be in this complete-case set). **Composite outcome**
(`death.within.6.months` OR `re.admission.within.6.months`) event rate **41.3%** (258/625) —
readmission-dominated (39.7% alone) with death within the same window rare (1.6% alone), a larger
and more balanced event rate than either §7.X's 14.2% in-hospital mortality or this cohort's own
death-alone rate.

**Result** (`data/zigong_outcome_validation/summary.md` for full output):

- **AUC = 0.533 (95% CI 0.490–0.575, percentile bootstrap, 2,000 resamples, seed=42)** for
  `baseline_deficit_score` predicting the 6-month composite outcome, complete-case cohort (n=625).
  **The CI crosses 0.5 — not distinguishable from chance on this cohort.**
- **PR-AUC = 0.463 (95% CI 0.412–0.520)** against a 0.413 event-rate baseline — a small lift over
  the baseline rate, consistent with the near-chance AUC rather than contradicting it.
- **Bonus, full cleaned cohort (n=2001, not gated by LVEF/NYHA/BNP presence since `map` itself is
  0% missing):** AUC = 0.548 (95% CI 0.525–0.573) — CI just clears 0.5, but still weak; PR-AUC =
  0.457 (95% CI 0.426–0.490).
- **Calibration is not monotonic in the way §7.X's was**: decile-style binning collapsed to 4
  distinct score groups because 441/625 (70.6%) patients land at essentially the same near-floor
  score (~0.0165) — consistent with this cohort's mean admission `map` (94.7 mmHg, per the
  reconnaissance pass) sitting just above the 92.5 mmHg healthy anchor `baseline_deficit_score` is
  built around, unlike MIMIC-IV's more acutely unstable ICU population. **Likely explanation for
  the muted signal**: this mechanism was designed around a chronically-congested low resting MAP
  (`fluid_overload`'s presentation); Zigong's admission-time MAP is mostly normal-to-elevated, so
  the score has little room to differentiate most of this cohort — a population mismatch, not a
  bug in the formula.

**Side by side with §7.X, cohorts and outcomes clearly different — not averaged, not treated as
the same number:**

| | §7.X MIMIC-IV | §7.Y Zigong |
|---|---|---|
| Cohort | 17,129 ICU HF admissions | 625 complete-case HF admissions (2,001 cleaned) |
| Outcome | In-hospital mortality (14.2%) | Death-or-readmission, 6mo (41.3%) |
| AUC | **0.596** (95% CI 0.585–0.608) | **0.533** (95% CI 0.490–0.575), complete-case; 0.548 (0.525–0.573), full cleaned cohort |
| PR-AUC | not computed in §7.X | 0.463 (95% CI 0.412–0.520) vs. 0.413 baseline |

**Honest limitations of this specific test:** **this validates baseline-risk-predicts-future-
outcome only — it does NOT validate day-by-day trend/early-warning detection (Model 1's actual
production use case), which remains untested by any real data.** Additionally: hospitalized,
already-acutely-ill population at baseline capture, not this project's target outpatient/home-
monitoring population (same caveat as §7.X); the composite outcome mixes two different event types
(death, readmission) with very different rates and is not decomposed here; LVEF/NYHA/BNP are
unused despite being present, for the reasons stated above; `map` here is a single admission-time
vital, not a stable ambulatory baseline (same `map_start`-meaning caveat as §7.X); the complete-case
cohort is a non-random subset (patients who happened to get both an echo and a BNP draw) that may
not represent the full 2,001-admission cleaned population.

**Taken together with §7.X:** two independent real-world cohorts (MIMIC-IV, Zigong) now show
`baseline_deficit_score` performing near chance, and the Zigong result's root cause (this cohort's
admission-time MAP sitting mostly at or above the mechanism's own healthy anchor, rather than in
the chronically-congested-low-MAP range it was tuned to detect) suggests the mechanism may be built
for acute ICU-level instability rather than the more moderate, ward-level HF presentation this
system's actual home-monitoring use case targets — worth weighing before deciding whether this is
a fixable tuning gap (e.g. incorporating the LVEF/NYHA/BNP that `risk_score.py` currently doesn't
use at all, confirmed by direct inspection: its six inputs are exclusively Pulse-simulated
hemodynamic vitals, see the "Why LVEF/NYHA/BNP... are not fed into this test" note above) or a
permanent scope limitation.

### 7.Z Zigong cohort — Model 1 clinical-feature-component-only exploratory test (frozen wearable
### inputs), 2026-09-11

**Scope: this does NOT test Model 1 as designed.** Model 1 (severity regressor) was trained on 5
clinical features (`age`, `sex_male`, `bmi`, `ejection_fraction_pct`, `nt_probnp_pg_ml`) PLUS 24
wearable-trend features from a real 21-day ambulatory window. Zigong has no wearable time series —
one admission-time snapshot per patient. This pass loads the existing, unmodified
`models/severity_regressor.joblib` and neutralizes the 24 wearable-trend slots to this project's
own "stable"-scenario reference values (zero drift, `reference_stats.yaml`'s `wearable_baseline`,
via the real `_wearable_features()`/`build_inference_features()` code — not hand-derived), then
substitutes approximated clinical inputs: `age` = `ageCat` bin midpoint (e.g. `(59,69]` → 64, not
real continuous age), and `nt_probnp_pg_ml` = Zigong's raw `brain.natriuretic.peptide` (BNP) with
**no unit conversion** — this project has no validated BNP-to-NT-proBNP conversion, and none was
invented; different assay, different reference range, different clinical meaning, an invalid
like-for-like substitution reported as exploratory only.

**Result** (n=625, complete-case cohort, same 6-month composite outcome as §7.Y, 41.3% event
rate): **AUC = 0.478 (95% CI 0.433–0.523)**, **PR-AUC = 0.396 (95% CI 0.351–0.452)** vs. 0.413
baseline — below chance on both.

**Critical caveat, not a footnote:** the predicted severity values are nearly constant across all
625 patients (mean 0.061, std 0.0078, range 0.042–0.088). Neutralizing all 24 wearable-trend
features collapses most of this trained model's decision paths into a narrow band — the near-
chance/sub-baseline result is largely a mechanical consequence of removing the features that carry
most of this model's discriminative signal, not solely a measurement of clinical-feature
usefulness. See §7.AA for a properly-isolated test that removes this confound.

### 7.AA Zigong cohort — clinical-only Model 1 variant, newly trained (not frozen), 2026-09-11

**Scope: a genuine, unconfounded test of whether the clinical-feature component predicts real
outcomes — unlike §7.Z, there is nothing frozen here.** `scripts/train_clinical_only_variant.py`
trains a NEW model from scratch, using the exact same synthetic training data, `split_patients()`
logic, and `seed=42` as production Model 1, restricted to `CLINICAL_FEATURE_COLUMNS` only (no
wearable-trend features at all). Same RandomForest hyperparameters as the production model
(`n_estimators=300`, no depth cap). Written to clearly-separate files —
`models/scenario_classifier_clinical_only.joblib`, `models/severity_regressor_clinical_only.joblib`
— the production `.joblib` files are untouched.

**Synthetic held-out validation, same 300 test patients as production Model 1:**

| | Full Model 1 (wearable+clinical) | Clinical-only variant |
|---|---|---|
| Scenario accuracy | 90.7% | 50.3% |
| Severity MAE | 0.047 | 0.171 |
| Severity RMSE | 0.061 | 0.219 |

Dropping the 24 wearable-trend features costs ~40 points of accuracy and ~3.6× worse severity MAE
on synthetic data — the measured cost of wearable-feature removal. `stable` classification held up
best (73% precision); `cardiac_stress`/`deconditioning` (37–39% precision) were hit hardest, since
their distinguishing signal lives almost entirely in the wearable trend, not the clinical snapshot.

**Output distribution — confirmed NOT collapsed** (unlike §7.Z): std=0.230, range [0.041, 0.819]
on the synthetic test set; std=0.262, range [0.040, 0.837] on Zigong. This is a real,
non-degenerate model — the Zigong AUC below is not explainable by a frozen-feature artifact.

**Zigong result** (same n=625, cohort, outcome, and BNP/age caveats as §7.Z — restated, not
silently reused): **AUC = 0.517 (95% CI 0.473–0.562)**, **PR-AUC = 0.419 (95% CI 0.372–0.478)** vs.
0.413 baseline — still centered on chance, CI comfortably includes 0.5, but this time the number is
**trustworthy as a real measurement**, not explained away by a collapsed output. Slightly better
than §7.Z's 0.478 but not meaningfully different from chance either way.

### 7.BB Zigong-native risk model — EXPLORATORY external benchmarking, standalone, 2026-09-11

**This is a separate, standalone exploratory analysis — it does NOT feed into, replace, or get
called by `risk_score.py`, Model 1, or the Pulse simulation layer.** Its purpose is to check
whether Zigong's richer, well-populated fields (not just the 5 sparse clinical-snapshot fields
tested in §7.Z/§7.AA, or the single `map` field tested in §7.Y) can reach discrimination closer to
literature-reported readmission/mortality risk-model baselines, on the same 6-month
death-or-readmission composite outcome. **This confirms real predictive signal exists in Zigong's
population for this outcome — it does NOT mean HeartGuard AI's design is fixable by adding these
fields.** Renal chemistry, coagulation, and CBC panels are lab-draw data, not obtainable from
consumer wearables or from the structural/EF-based parameters this system's architecture is built
around. This is external benchmarking context, not a roadmap.

**Base population:** the full cleaned cohort (n=2001, same 5 cleaning rules as §7.Y), not the
complete-case n=625 — deliberately avoids restricting to patients who happened to get an echo.

**Feature selection**, checked field-by-field, not assumed: 65 of 67 candidate fields (8 vitals,
NYHA, Killip, `type.of.heart.failure`, 17 Charlson fields, 22 CBC, 7 coagulation, 5 renal
chemistry, `admission.way`, `visit.times`, plus BNP) have <15% missingness and are kept. Two are
dropped: **`LVEF`** (68.38% missing, above threshold) and **`leukemia`** (0% missing but
zero-variance — a single constant value across the whole cohort, uninformative despite being
"well-populated"). **`brain.natriuretic.peptide` (BNP) is included** — checked at 1.74% missing,
comfortably under the bar, correcting an initial assumption it would likely be dropped like LVEF.
315/2001 rows (15.7%) needed median imputation on at least one already-low-missingness field
(light imputation only — never applied to the excluded high-missingness `LVEF`).

**Split and model selection:** stratified 80/20 train/test split on the composite outcome,
`random_state=42`, performed **before** any model selection. 5-fold cross-validation on the
training portion only (`RandomForestClassifier`, small grid over `n_estimators`/`max_depth`/
`min_samples_leaf`) selected `max_depth=None, min_samples_leaf=5, n_estimators=300` (CV AUC=0.621).
The held-out test set was touched exactly once, after model selection.

**Result:**

- Train (in-sample): AUC=1.000, PR-AUC=1.000 — expected RandomForest behavior on its own training
  data with `min_samples_leaf=5` and no depth cap, not a bug; reported precisely so the held-out
  number below is read as the trustworthy one, not the in-sample one.
- **Held-out test (n=401): AUC = 0.667 (95% CI 0.611–0.721), PR-AUC = 0.605 (95% CI 0.529–0.676)**
  vs. 0.414 baseline. Train/test AUC gap = 0.333.

**Feature importances are flat and renal/coagulation-dominated — this matters for interpreting the
AUC, not just as a detail.** No single dominant predictor (`urea`, `uric.acid`,
`glomerular.filtration.rate`, `D.dimer`, `creatinine.enzymatic.method`, `brain.natriuretic.peptide`,
RDW-SD, APTT, `lymphocyte.count`, `prothrombin.activity` all cluster near ~2.3–3.1% importance).
**This pattern suggests the model is capturing general acute-illness severity (renal function,
coagulation, inflammatory markers) rather than HF-specific deterioration — a different, broader
construct than what Model 1 or `risk_score.py` are designed to measure. The AUC number alone should
not be read as "solved": the *what* being predicted here is meaningfully different from HeartGuard
AI's actual target.**

**Comparison, all real-outcome tests plus literature baselines, side by side:**

| | AUC | PR-AUC |
|---|---|---|
| §7.X `risk_score` (MIMIC-IV) | 0.596 (0.585–0.608) | not computed |
| §7.Y `risk_score` (Zigong, complete-case) | 0.533 (0.490–0.575) | 0.463 |
| §7.Y `risk_score` (Zigong, full cleaned) | 0.548 (0.525–0.573) | 0.457 |
| §7.Z frozen Model 1 (collapsed-output confound) | 0.478 (0.433–0.523) | 0.396 |
| §7.AA clinical-only variant (properly trained) | 0.517 (0.473–0.562) | 0.419 |
| **§7.BB Zigong-native risk model** | **0.667 (0.611–0.721)** | **0.605** |
| Literature: LACE index | ~0.56–0.65 | — |
| Literature: richer ML models | ~0.72–0.76 | — |

§7.BB lands at/slightly above the LACE-index range and below the richer-ML-model range — real
signal, carried by fields this project's architecture has never used and structurally cannot
obtain from a wearable-and-EF-based design.

### 7.CC MAGGIC-11 (MAGGIC-adapted, missing smoker status + HF duration) on Zigong — EXPLORATORY
### external benchmark, standalone, 2026-09-24

**This is a separate, standalone exploratory analysis — it does NOT feed into, replace, or get
called by `risk_score.py`, Model 1, or the Pulse simulation layer.** Same treatment as §7.BB.
Purpose: implement the real, published **MAGGIC** risk score (Pocock SJ, et al. "Predicting
survival in heart failure: a risk score based on 39 372 patients from 30 studies worldwide." Eur
Heart J. 2013;34(19):1404-1413) as an external benchmark and test it against the same 6-month
composite outcome used in §7.Y/§7.AA/§7.BB.

**Naming discipline, load-bearing throughout this section: the score actually tested here is never
called plain "MAGGIC."** It is always **"MAGGIC-11"** or **"MAGGIC-adapted (missing smoker status,
HF duration)."** Reasons follow directly from Steps 0–1 below.

**Step 0 — formula correctness, verified before touching any real patient data.** An existing
implementation, `src/analytics/benchmark_scores.py::compute_maggic_score()`, already existed from
earlier `scripts/benchmark_comparison.py` work — audited rather than rewritten. Its own docstring
had already flagged that only the age×EF interaction bands were independently confirmed against
the original paper; every other band (EF, BMI, creatinine, SBP-by-EF, NYHA, and the binary risk
factors) came from one unverified secondary source. Re-verified here (2026-09-24) against
independent external sources: SBP<110 (reduced-EF band) = 5 pts / SBP≥150 = 0 pts; creatinine band
edges 90/110/130/150/170/210/250 μmol/L, >250 = 8 pts; age max = 15 (EF≥40% category, oldest band);
NYHA I/II/III/IV = 0/2/6/8; EF<20% = 7 pts; BMI<15 = 6 pts, BMI≥30 = 0 pts; male=1, smoker=1,
diabetes=3, COPD=2, HF≥18mo=2, not-on-beta-blocker=3, not-on-ACEI/ARB=1 — **all confirmed matching
the existing code exactly.** Three hand-picked test patients (low/moderate/high risk) were
hand-calculated against these bands and added as real pytest unit tests
(`tests/test_maggic_score.py`, same pattern as `tests/test_risk_score.py`'s boundary-case tests) —
all three matched the code's output exactly across all 13 components (low-risk: 3 points;
moderate: 24; high-risk: 56 — the high-risk total exceeds the ~50–52 range secondary sources cite
for MAGGIC's points-to-mortality lookup table, expected since that table only tabulates scores
actually observed in the derivation cohort, not a mathematical ceiling on the point-sum formula).
**Conclusion: the existing MAGGIC formula implementation is arithmetically correct.** Test suite:
240/240 passing (236 prior + 4 new).

**Step 1 — field availability on Zigong, checked individually, not assumed.** Of MAGGIC's 13
variables: **11 are present or reliably derivable** (age via `ageCat` bin-midpoint, an
approximation flagged as in §7.Z/§7.AA; sex, BMI, systolic BP, LVEF (68.32% missing), creatinine
(1.15% missing, already in μmol/L — MAGGIC's native unit, no conversion needed), diabetes, COPD,
and NYHA class, all 0% missing; **beta-blocker and ACEI/ARB use are not columns in `dat.csv` at
all, but were found derivable from `dat_md.csv`'s medication list** — matched by drug name
(`Metoprolol Succinate Sustained-release tablet`/`metoprolol tartrate injection` for beta-blocker;
`Benazepril hydrochloride tablet`/`Valsartan Dispersible tablet` for ACEI/ARB); 2007/2008 patients
have ≥1 drug record, so a non-match is a confident true-negative, not missing data (38.0%/38.4% of
the cohort flagged on each, respectively). **2 of 13 are entirely absent from this dataset with no
derivation path: current smoker status, and whether HF was first diagnosed ≥18 months ago** —
checked directly against all 166 columns in `dataDictionary.csv` and against `dat_md.csv`; neither
exists in any form.

**Step 2 — handling, decided from Step 1's findings, no defaults used.** Because the 2 missing
fields are entirely absent (not merely partially missing), they are **excluded, not defaulted or
assumed** — `compute_maggic_score()` is reused unmodified with `current_smoker=False` and
`hf_duration_18mo_plus=False`, the one parameter value for each that makes its own point
contribution exactly zero (not a guess that patients are non-smokers or recently diagnosed; both
keys are stripped from the reported component breakdown so a 0 is never misread as measured). The
resulting **MAGGIC-11** score is a genuine 11-of-13-variable score, not the validated 13-variable
one. All 11 remaining components use **real per-patient Zigong values** — a stronger real-world
test than the original `scripts/benchmark_comparison.py` (which used 6 fixed constants on
synthetic data). Complete-case cohort (all 11 fields + a drug record present, no imputation,
cleaned `n=2001` base per the same 5 rules as §7.Y): **n=622** — closely matching §7.Y/§7.AA's
~625.

**Step 3 — result** (`scripts/zigong_maggic11_validation.py`, n=622, same 6-month
death-or-readmission composite outcome as §7.Y/§7.AA/§7.BB, event rate 41.8%):

- **AUC = 0.604 (95% CI 0.559–0.649)**, **PR-AUC = 0.496 (95% CI 0.443–0.558)** vs. 0.418 baseline.
- Calibration is reasonably monotonic across score deciles: observed event rate rises from ~28.8%
  in the lowest-score decile to ~50–55% in the highest, with one small inversion mid-range — not a
  perfectly clean staircase, but directionally consistent, not just a summary-statistic artifact.

**Interpreting this number, explicitly, as instructed:** because 2 of 13 predictors are missing
(current smoker status — an established independent MAGGIC risk factor — and HF-diagnosis
duration), **MAGGIC-11 is expected to underperform published full-MAGGIC studies even before
considering any population difference — so a gap versus the literature's 0.70–0.80 range should be
partly attributed to the missing fields themselves, not solely to population mismatch.** Seen in
that light, **AUC=0.604 is a stronger and more interesting result than a bare comparison to
0.70–0.80 would suggest**: a real, externally-published, non-hand-tuned score reaches this
discrimination on a real cohort despite missing two of its own inputs, landing within/near the
LACE-index range (0.56–0.65) on the very first same-cohort, same-outcome test this project has run
against it.

**Full comparison, all real-outcome tests plus literature, side by side — cohorts/outcomes/scores
clearly different, never averaged into one number:**

| | AUC | PR-AUC |
|---|---|---|
| §7.X `risk_score` (MIMIC-IV) | 0.596 (0.585–0.608) | not computed |
| §7.Y `risk_score` (Zigong, complete-case) | 0.533 (0.490–0.575) | 0.463 |
| §7.Y `risk_score` (Zigong, full cleaned) | 0.548 (0.525–0.573) | 0.457 |
| §7.Z frozen Model 1 (collapsed-output confound) | 0.478 (0.433–0.523) | 0.396 |
| §7.AA clinical-only variant (properly trained) | 0.517 (0.473–0.562) | 0.419 |
| §7.BB Zigong-native risk model | 0.667 (0.611–0.721) | 0.605 |
| **§7.CC MAGGIC-11 (Zigong, complete-case n=622)** | **0.604 (0.559–0.649)** | **0.496** |
| Literature: LACE index (different populations/outcomes) | ~0.56–0.65 | — |
| Literature: full 13-variable MAGGIC (different populations/outcomes) | ~0.70–0.80 | — |
| Literature: SHFM / BCN-Bio-HF (different populations/outcomes) | published, not re-derived here | — |
| Literature: richer ML models (different populations/outcomes) | ~0.72–0.76 | — |

The literature rows are **different populations and different outcomes** (MAGGIC/SHFM/BCN-Bio-HF
were derived and validated on their own cohorts against their own endpoints, not Zigong's 6-month
composite) — **this MAGGIC-11-on-Zigong result is the first same-cohort, same-outcome comparison**
this project has run against a published external score, which is what makes the gap
interpretable at all rather than just another number floating next to unrelated ones. Per the
Egyptian-validation-study precedent (MAGGIC/GWTG-HF/SHFM externally re-validated outside their
derivation population, `clinicaltrials.gov/study/NCT07194889`) — published scores routinely show
meaningfully different discrimination when moved to a new population — so a below-range result
here would not, by itself, indicate anything is coded wrong; Step 0 already ruled that out
directly.

**Flagged explicitly, prominently, not as a footnote:** MAGGIC (and MAGGIC-11) need creatinine and
NYHA class — lab-draw and clinical-encounter data, not wearable measurements. **Whatever this
result turns out to mean, it says nothing about this project's untested wearable-only
early-warning hypothesis** — the same scope boundary already stated for §7.Y.

No production code touched: `risk_score.py`, Model 1, and the Pulse simulation layer are all
unmodified by this section, exactly as `src/analytics/benchmark_scores.py` was audited, not
rewritten, at Step 0.

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

The underlying limitation remains open: a real EF measurement (echocardiogram) is the actual
fix. **A non-invasive BNP-based EF proxy was specifically investigated as a possible substitute
(2026-08-18) and ruled out — not for lack of searching, but because no defensible relationship
exists to build one from.** Constraint on the investigation: any proxy had to use only signals
measured independent of the scenario classification (age, BNP, other Tier 1 vitals) — never
`scenario_type` or anything derived from it, which would leak the label this pipeline predicts.

Checked this project's own already-cited literature first: `sinha_2024` (age cross-check only,
nothing EF/BNP-related), `bhosale_2024` (age-adjusted NT-proBNP *diagnostic* cutoffs — whether BNP
is elevated enough to indicate HF at all, not a continuous EF estimate), and Ohte et al.
(`docs/data_provenance.md`'s citation table, listed as `TODO — not yet extracted`, zero usable
content in this repo). None support a proxy formula.

Then checked the broader cardiology literature independently (JACC, PMC, several HFrEF/HFpEF
cohort studies), not just this project's citations. **Consistent finding across every source
checked: EF category is treated as the known, given input used to stratify or explain NT-proBNP
findings — never the reverse.** No paper offers a formula predicting continuous EF *from* BNP.
This directionality is not incidental — BNP is independently driven by age, renal function,
atrial fibrillation, and obesity (the same confounders that make BNP-EF correlations loose at the
individual level, §6.1/data_provenance.md), which is exactly why the literature never inverts the
relationship into an EF-predicting formula. **This is a structural feature of the clinical
literature — the relationship clinicians actually use runs EF→BNP, not BNP→EF — not a gap in how
hard this was searched, and not something a more thorough search would find.**

**Resolution: the flat healthy-population-mean fallback stays as the documented, honest current
state.** No proxy was implemented, since implementing one without a real citable basis would mean
fabricating coefficients — exactly what this project's citation discipline exists to prevent (see
the MAGGIC benchmark's own age-band sourcing caution, `src/analytics/benchmark_scores.py`, for the
same principle applied elsewhere). The `risk_caveats` messaging fix (§8.5.1 of
`docs/real_world_data_integration.md`) remains the correct, currently-available mitigation:
naming the mechanism accurately, not hiding it behind a spuriously-precise proxy. **This
specific question — a BNP-based EF proxy — is now closed; a real EF measurement (echocardiogram)
remains the only path to actually resolving the underlying limitation, not attempted here.**

**Note: this is a distinct, separate limitation from the "Fluid_overload scenario lacks a
volume-loading mechanism" entry immediately below** — that one is about the scenario's own
hemodynamic response to severity being structurally weak; this one is specifically about EF
falling back to a healthy default when unmeasured. Do not conflate the two.

### Fluid_overload scenario lacks a volume-loading mechanism, diagnosed 2026-09-01

Found during the continuous-state-sync investigation (`docs/continuous_state_sync_status.md`,
2026-08-30 session, root-caused 2026-09-01) while checking why a real patient's forward
projection showed a flat `risk_score` across projected severities 0.946-1.0. This entry provides
the confirmed mechanistic root cause behind §6.1's existing observation that Pulse's
`fluid_overload` scenario generation barely varies `map_start`/hemodynamics with severity — that
note flagged the symptom; this is the traced cause.

#### Mechanism

`fluid_overload`'s scenario definition (`src/patient_builder/scenario_file.py`,
`_scenario_actions()`) applies a single `CardiovascularMechanicsModification` action with
`VenousComplianceMultiplier = max(0.5, 1 - 0.4*severity)`, and nothing else — no `Exercise`
action, no volume-loading action of any kind. Confirmed via direct comparison against
`acute_deterioration` at the same EF (using the same `ef_to_cardiovascular_modifiers()` core
values): that scenario additionally applies a `HeartRateMultiplier` and an `Exercise` action —
the actual driver of its meaningful `hr_rise`/`map_drop`/`co_drop_pct` response to severity.
`fluid_overload` has neither.

#### Root cause

Reducing venous compliance alone, with no accompanying increase in total circulating volume,
mobilizes pooled blood into active circulation (a recruitment effect via Frank-Starling) rather
than representing genuine fluid/volume overload. Every multiplier moves in the clinically correct
direction as severity rises (compliance and resistance both fall) — **this is not a sign error,
it is a structural gap in what the scenario models.** Confirmed on a real patient (EF=32,
`fluid_overload`) across three projected severities (0.946, 0.984, 1.0): simulated HR fell, MAP
rose, and CO rose — the *improving* direction, despite increasing severity. `acute_score`
(risk_score.py) was 0.0 at every horizon as a direct consequence.

#### Why this matters

This is the underlying reason `baseline_deficit_score`/`max()` (§6.1) had to be added as a
compensating mechanism in the first place — it patches around this scenario-generation weakness
via a baseline-MAP floor, rather than the weakness being resolved at the source.

#### Why not fixed now

Correctly representing `fluid_overload` would require adding a real volume-loading mechanism
(e.g. a Pulse action that increases total circulating blood volume, not just reduces venous
compliance) to the scenario definition. This is scenario-design rework, not a quick parameter
fix, with real downstream costs: patient stability at high severity would need re-verification
(interacts with the already-characterized Exercise-instability findings above), the 30-patient
Phase 2 validation would need re-running, and the severity regressor would likely need retraining
against the updated scenario behavior. Out of scope for the continuous-state-sync branch and for
the session that found it.

#### Current mitigation

`baseline_deficit_score`/`max()` (§6.1, `risk_score.py`) is already in place and validated: it
correctly catches high-risk `fluid_overload` patients via the baseline-MAP floor mechanism even
though the scenario's own severity response is weak. **This is a working safeguard, not a gap in
patient safety** — just an architectural inefficiency worth fixing properly at the source someday.

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

### `severity` and `risk_score` are not on comparable scales — found 2026-09-10, RESOLVED same day

Found while resolving `docs/synthetic_deterioration_stress_test.md`'s threshold question (that
document has the full investigation). `severity` is ML Model 1's raw regression output (§5);
`risk_score` is the downstream, Pulse-simulation-derived weighted score (§6.1). Both are bounded
to [0, 1], and it is tempting to treat that as "the same scale" — **they are not**, at least for
`acute_deterioration`, computed on the real 117-row Phase 4 dataset
(`data/simulation_runs/features_dataset.csv`, n=12 for this scenario type):

| | severity | risk_score |
|---|---|---|
| mean | 0.385 | 0.655 |
| **min** | **0.046** | **0.491** |
| max | 0.846 | 0.760 |
| correlation | — | 0.685 |

`risk_score`'s floor for this scenario type (0.491) sits above `severity`'s own mean (0.385) —
`risk_score` saturates high almost as soon as any `Exercise`-driven stress occurs (the same
structural property §6.1 already documents), while `severity` spans a much wider, lower-centered
range by construction (uniform-ish per `generate_patients.py`'s `_assign_scenario()`).

**Live production site found affected, now fixed, not just flagged.**
`src/analytics/projection.py`'s `project_severity()` previously asserted "severity and risk_score
share the same 0-1 range by construction" and applied a rate pre-converted via
`deterioration_rate.py`'s `SD_RATE_TO_RISK_SCORE_PER_DAY` directly onto `current_severity` — called
live from `src/api/services.py`'s production pipeline. **Fix:** `project_severity()` now takes the
raw, scale-agnostic `composite_rate` (population-SD-equivalents/day) and converts it internally via
a new, separately-defined `SD_RATE_TO_SEVERITY_PER_DAY` constant — the same "raw rate in, scale-
specific conversion inside the consuming function" pattern `deterioration_rate.days_to_next_stage()`
already used correctly for `risk_score`. `services.py` now passes `composite_rate` unconverted
(`project_physiology(..., composite_rate=rate_info["composite_rate"])`), removing its
`SD_RATE_TO_RISK_SCORE_PER_DAY` import entirely — that constant is no longer reachable from the
severity-projection path at all.

**This is a structural fix, not a numerical one — stated plainly, not implied.**
`SD_RATE_TO_SEVERITY_PER_DAY` starts at the same placeholder value (0.05) as its risk_score
counterpart, because no real severity-trajectory calibration data exists to pick a different
number (same status as the original constant: an explicitly hand-tuned engineering placeholder,
not a clinical citation). What changed is that the two calibrations are now independently named
and can never be silently conflated again by construction — a future recalibration of one cannot
accidentally move the other. Regression-tested (`tests/test_projection.py`'s
`TestSeverityRiskScoreScaleIndependence`): monkeypatching `SD_RATE_TO_SEVERITY_PER_DAY` changes
`project_severity()`'s output; monkeypatching `SD_RATE_TO_RISK_SCORE_PER_DAY` does not.

**Fusion remains explicitly out of scope, not silently deferred.** `severity` and `risk_score`
are never combined into one number anywhere in this fix — real outcome-calibration data would be
needed to validate a fused score, and none exists. Instead, `src/analytics/score_reporting.py`
(new) makes this explicit at the output layer: `score_provenance(classifier_severity,
pulse_risk_score)` returns `{"classifier_severity", "pulse_risk_score", "source"}`, where
`source` is `"not_fused"` whenever both are present (the only state reachable today — a
`RiskAssessment` row only ever exists once both the classifier and Pulse have run
successfully; `"classifier_only"`/`"pulse_only"` are modeled for future partial-failure states
not yet surfaced through the API). Wired onto `RiskAssessment` as a computed property and exposed
via `RiskAssessmentPayload.score_provenance` in the API response.

**The borrowed 0.65 threshold removed from severity reporting entirely.** No code in this
pipeline ever actually thresholded `severity` at 0.65 in production (confirmed by grepping every
`MODERATE_HIGH_BOUNDARY`/`0.65` reference in the codebase — see the audit below); the borrowed-
threshold mistake was confined to `docs/synthetic_deterioration_stress_test.md`'s own analysis
script, already caught and fixed there before this sprint. To give `severity` a descriptive label
without inventing or borrowing a cutoff, `score_reporting.py` also adds `severity_band()`, using
only `STABLE_SEVERITY_CAP` (0.15, now a named constant in `generate_patients.py`, promoted from a
bare `severity * 0.15` literal in `_assign_scenario()`) — the one real, non-arbitrary reference
point this project's own training data provides (validated in
`docs/synthetic_deterioration_stress_test.md` as "the day a trajectory first clearly exceeds what
`stable` looks like"). Returns exactly two labels, `"within_stable_range"` /
`"exceeds_stable_range"` — deliberately no third tier, since a finer banding would need another
cutoff and no further non-arbitrary reference point currently exists. Exposed via
`RiskAssessmentPayload.severity_band`, with its Pydantic field description stating explicitly it
is not a clinical alert threshold and should not be treated as equivalent to `risk_bucket`.

**Full audit of every `0.65`/`MODERATE_HIGH_BOUNDARY` reference in the codebase, each checked
individually — only one needed a code fix (`project_severity()`, above):**
- `src/analytics/risk_score.py`'s own `MODERATE_HIGH_BOUNDARY = 0.65` definition, and every
  consumer of it (`src/analytics/deterioration_rate.py`'s `days_to_next_stage()`,
  `src/analytics/staging.py`'s NYHA gate, `tests/test_risk_score.py`) — all apply it exclusively
  to `risk_score` on `risk_score`'s own native scale. This is `risk_score.py`'s own pre-existing,
  already-tested, already-caveated-in-its-own-module design ("an engineering choice... not a
  clinical citation," §6.1) — not the bug, and not touched by this fix. Dismantling
  `risk_bucket`'s own tertile system was never in scope here.
- `scripts/model1_extended_eval.py`'s `risk_score`-vs-`true_severity` scatter/correlation already
  computes correlation **per scenario type**, not pooled, and is labeled "PROXY — not real
  outcomes" — the methodologically correct way to compare the two, consistent with (not
  contradicted by) the 0.685 acute_deterioration correlation found above. No change needed.
- `scripts/benchmark_comparison.py`'s MAGGIC-tertile comment references `risk_score.py`'s framing
  stylistically; no numeric use of 0.65. No change needed.
- `src/api/services.py`'s/`schemas.py`'s `fluid_overload` caveat strings and
  `scripts/perheart_real_data_replay.py`'s side-by-side `describe()` printout mention `severity`
  and `risk_score` together but never combine or threshold them numerically — informational text
  only. No change needed.
- `frontend/src/components/lab/SimulationLabPage.jsx` displays `severity` and `risk_score` next to
  each other in one UI line — a display juxtaposition, not a computation. Not changed (frontend
  work was out of scope for this sprint); flagged here since a viewer could visually read the two
  numbers as more comparable than they are, now that `severity_band`/`score_provenance` exist as
  the more honest alternative to show instead.

**A separate question, stated explicitly so it is never conflated with the audit above: is
`MODERATE_HIGH_BOUNDARY=0.65` itself validated against real outcomes, or just correctly scoped to
`risk_score`'s own scale?** The audit confirms every consumer applies it correctly (right scale,
no cross-quantity bug) — that is a plumbing fact, not a clinical validity fact, and the two must
not be read as the same claim. **It is not validated against real outcomes. It is `risk_score.py`'s
own explicitly self-labeled placeholder**, unchanged by this sprint: the constant's own code
comment says "Engineering choice (roughly a tertile split of the 0-1 score), not a clinical
citation" (`risk_score.py`, the line immediately above its definition), and §6.1 above states the
same thing in prose. Unlike `SD_RATE_TO_RISK_SCORE_PER_DAY`/`SD_RATE_TO_SEVERITY_PER_DAY`, it is
not even tracked in `docs/data_provenance.md`'s constant ledger alongside this project's other
named `assumed_default` values. The closest thing this project has to a real-outcome check on any
part of `risk_score` is §7.X's MIMIC-IV test of the `baseline_deficit_score` sub-score specifically
against in-hospital mortality — AUC 0.596 (95% CI 0.585–0.608), barely above chance discrimination,
and that test evaluates whether the sub-score's *magnitude* tracks mortality risk at all, not
whether 0.35/0.65 are the right places to draw LOW/MODERATE/HIGH lines. So: **honestly labeled as
unvalidated where it was defined, correctly scoped everywhere it is used, and not clinically
confirmed by anything else in this project either** — the same "not derived from real data"
category `project_severity()`'s old behavior was in, differing only in that `risk_score.py` never
asserted otherwise (`project_severity()`'s old docstring incorrectly *asserted* the two scales
matched; `risk_score.py`'s comment has always correctly disclaimed itself). Do not treat
`risk_bucket`'s correctness-of-plumbing as evidence of the boundary's clinical meaning.

**Verification:** 176/176 tests pass (`tests/test_projection.py`'s scale-independence tests,
`tests/test_score_reporting.py` (new), and a live-API integration assertion in `tests/test_api.py`
confirming `severity_band`/`score_provenance` actually appear correctly in a real pipeline
response, not just in unit isolation).

### Sprint 2 (2026-09-10): score production and alert decision are now architecturally separate

Everything below is a structural/robustness layer built on Sprint 1's fix, not a threshold
validation — every new threshold-like constant introduced here remains exactly as unvalidated as
`SD_RATE_TO_SEVERITY_PER_DAY` was, flagged the same way, for the same reason (blocked on real
outcome data, Sprint 3+5, still open). Full API-facing detail also lives in
`src/api/schemas.py`'s `score_provenance` field description.

**1. Score production vs. alert decision, now structurally separate, not just conceptually
separate.** `project_severity()`, ML Model 1, and `risk_score.py` only ever produce a number —
none of them decide alert/no-alert, and now neither does anything else that produces a score.
`src/analytics/score_reporting.py`'s new `alert_decision(severity, confidence, simulation_status)`
is the one place that decision is made. Its internal logic (severity exceeds
`STABLE_SEVERITY_CAP` AND confidence clears `MIN_CONFIDENCE_FOR_ALERT`) is an unvalidated
placeholder — this sprint changed *where* the decision is made, not *how well-founded* it is.

**2. Every severity-bearing output now carries `confidence` + `simulation_status`.**
- `simulation_status` (`"valid"|"unstable"|"not_run"`): `"unstable"` covers both an outright
  Pulse failure and a **successful** run that landed in/near the documented acute_deterioration
  crash zone (severity 0.6–0.85, `src/pulse_runner/runner.py`'s `is_known_unstable_configuration()`
  — reused from the BCG-validation work's own crash-range constant, not reimplemented). A "lucky"
  pass inside that zone is deliberately still labeled `"unstable"`, not `"valid"` — succeeding
  once doesn't make a documented ~50%-failure-rate configuration a reliable data point.
- `confidence` (0–1): derived purely from `simulation_status` via `CONFIDENCE_BY_STATUS` —
  `unstable` (0.3) < `not_run`/classifier-only (0.5) < `valid` (0.8). **Two different things are
  true here and must not be blurred into one:** the *ordering* (`Pulse-confirmed-valid` highest,
  classifier-only in the middle, `Pulse-unstable-or-failed` lowest) was specified as this sprint's
  own scope; **the three specific numeric values (0.3, 0.5, 0.8) were not** — they were chosen
  by whoever implemented this (an engineering placeholder satisfying the requested ordering with
  round numbers), not specified in the sprint scope and not empirically derived or learned by any
  model. Neither the ordering nor the specific numbers have been validated against real outcome
  data; recalibrating either remains blocked on data this project does not have (Sprint 3+5).
- Exposed via `src/analytics/score_reporting.py`'s `build_score_report()`, which **extends**
  Sprint 1's `score_provenance()` output (every key it returned is still present, unchanged) with
  `severity_score`, `severity_band`, `alert`, `confidence`, `simulation_status` — one field
  growing, not a competing parallel structure. Wired onto `RiskAssessment.score_provenance`
  (same field name, same API response key) and `src/api/schemas.py`'s
  `RiskAssessmentPayload.score_provenance`.

**3. Pulse crash-zone pre-flight guardrail — flags, never silently skips.**
`src/pulse_runner/runner.py`'s new `run_pulse_with_preflight()` wraps (does not modify) the
existing `run_pulse()` — that function's own signature and behavior are untouched, since it has
many already-tested production callers. Before running, if `(scenario_type, severity)` is in the
documented crash zone, it emits a `RuntimeWarning` ("entering known-unstable Pulse
configuration...") and **still runs by default** — only `skip_if_unstable=True`, explicitly
opted into by the caller, actually skips the run. `simulation_status` is then set to `"unstable"`
based on the pre-flight flag alone, independent of whether the run happens to succeed (point 2
above). Wired into both real Pulse call sites — `src/api/services.py`'s main assessment pipeline
and `src/analytics/projection.py`'s `_run_at_severity()` (the 7/14/30-day re-simulations, which
can land in the same zone just as easily as the initial assessment) — both now go through the
same wrapper, sharing one crash-zone check rather than each needing its own.

**4. Temporal persistence (hysteresis) — structure built, values explicitly unvalidated.**
`src/analytics/score_reporting.py`'s `hysteresis_alert_states()` requires `ENTER_N` (2)
consecutive days ≥ `ENTER_THRESHOLD` (`STABLE_SEVERITY_CAP`, the same non-arbitrary reference
point `severity_band()`/`alert_decision()` already use) before flipping `no_alert → alert`, and
`EXIT_N` (2) consecutive days < `EXIT_THRESHOLD` (`STABLE_SEVERITY_CAP × 0.8`, an unvalidated
20%-deadband engineering choice) before flipping back. All four constants are named, documented,
and explicitly flagged unvalidated in the module docstring — same discipline as
`SD_RATE_TO_SEVERITY_PER_DAY`.

**Retroactively applied to `docs/synthetic_deterioration_stress_test.md`'s real trajectories
(subject 14, subject 102) — reported honestly, not massaged to look like a win: at the actual
`STABLE_SEVERITY_CAP` reference threshold, hysteresis has NO suppression effect on either
subject's documented non-monotonic dips.** Both trajectories clear `ENTER_THRESHOLD` (0.15) by a
wide margin on the very first day tested (severity 0.37/0.25 vs. threshold 0.15) and never
approach it again afterward — the lowest subsequent value in either trajectory (subject 14's
day-9 dip, 0.3422) is still more than double the threshold. Alert state enters almost immediately
(day 7 for both, the second consecutive qualifying day) and never exits for the rest of the
21-day window — the dips are real but occur far above the threshold, not near it, so there is
nothing for the entry/exit deadband to suppress at this specific reference point.
This is a genuine negative finding about *this threshold on this data*, not evidence the
mechanism itself is broken: a second test using an illustrative threshold placed near subject 14's
actual day-9 dip confirms the same hysteresis logic correctly holds the alert state through a
transient single-day dip when the threshold is close enough to the data for a deadband to matter
(`tests/test_score_reporting.py`'s `TestHysteresisOnStressTestData`). **Separately, and
explicitly out of scope for this mechanism:** subject 14's day 6–10 `scenario_type`
misclassification (`"fluid_overload"` instead of `"acute_deterioration"`) is a categorical-field
error, not a severity-threshold event — `hysteresis_alert_states()` operates on severity → alert
state only and has no mechanism to detect or suppress a wrong `scenario_type`; that would require
an analogous persistence layer applied to the classifier's categorical output specifically, not
attempted here.

**Verification:** 218/218 tests pass (176 Sprint-1 baseline + 40 new from this sprint + 2 more
added closing this sprint out, see below: crash-zone detection and pre-flight-wrapper behavior in
`tests/test_pulse_preflight.py`; simulation_status/confidence/alert_decision/build_score_report
and both the structural and retroactive-stress-test-data hysteresis tests in
`tests/test_score_reporting.py`). The pre-flight warning fired for real during `tests/test_api.py`'s
existing `test_pulse_failure_marks_simulation_failed` test (severity=0.8, `acute_deterioration` —
genuinely inside the crash zone), confirming the wiring end-to-end in a live pipeline test, not
just in isolation.

**Two closing checks, requested before Sprint 2 was considered done:**
1. **Confidence-value attribution corrected, not just clarified.** The `CONFIDENCE_BY_STATUS`
   *ordering* (`valid` > `not_run` > `unstable`) was specified as this sprint's scope; **the
   specific numbers 0.3/0.5/0.8 were not** — they were chosen during implementation as round
   placeholders satisfying that ordering. An earlier pass at this doc (and the code comment above
   `CONFIDENCE_BY_STATUS`) risked reading as if the exact numbers were specified rather than
   engineering-chosen; both now state this as two separate facts, not one.
2. **A constructed "lucky success inside the crash zone" test added**
   (`tests/test_pulse_preflight.py`'s `TestLuckySuccessInsideCrashZone`), since no such case
   exists in the real data collected this session — all 4 representative points that landed in
   the documented zone (day16/day20, both subjects) failed; none succeeded. Confirms the real,
   unmocked `run_pulse_with_preflight() → determine_simulation_status()` composition still
   reports `"unstable"` even when `pulse_succeeded=True`, contrasted against the same mocked
   "success" at a severity outside the zone correctly reporting `"valid"`.

### Sprint 2.5 (2026-09-10): root-caused the scenario_type flip, added categorical persistence,
### and closed the remaining loose ends from Sprints 1-2

**1. Root cause of the day 6-10 `scenario_type` misclassification — investigated on the real
subject 14 data before building anything, not assumed.** Checked, using
`data/synthetic_deterioration_stress_test/subject14_trend.csv` and the actual trained
`models/scenario_classifier.joblib`:
- **`predict_proba()` margins** (`fluid_overload` vs. `acute_deterioration`): day 6 = 0.226, day 7
  = 0.240, day 8 = 0.150, day 9 = 0.047, day 10 = 0.147. Days 6-8 and 10 were a fairly confident
  (if wrong) call, not razor-thin uncertainty throughout — only day 9 was a genuine near-tie.
- **Feature extraction**: values matched the underlying trend data exactly at every day checked —
  no bug in `_wearable_features()`/`build_inference_features()`.
- **Scenario-mapping logic**: `.predict()` correctly returns the argmax of a genuinely close
  probability distribution every time — no bug in the classifier→label mapping either.
- **The actual cause**: `generate_wearable_trends.py`'s `_trend_curve()` accelerates
  `acute_deterioration`'s progression as `frac**2` — deliberately small early on ("accelerates
  near the end rather than drifting linearly," that function's own comment). At low signal
  magnitude, the resulting HR/weight/SpO2 deltas are proportionally closer to a mild
  `fluid_overload` profile (weight-dominant per `SCENARIO_SIGNAL_DELTAS`) than to
  `acute_deterioration`'s own (HR/steps/HRV-dominant, but not yet ramped up). **Confirmed by
  contrast, not just theorized**: subject 102's own day-9 margin (`acute_deterioration` 0.377 vs.
  `fluid_overload` 0.357, margin 0.020 — narrower than subject 14's, but favoring the correct
  class) shows this is genuine, patient-specific feature-space overlap at low signal magnitude,
  not a fixed artifact that should have gone the same way for both subjects.

**2. Categorical persistence added — `src/analytics/score_reporting.py`'s new
`scenario_type_persistence()`, separate from severity's `hysteresis_alert_states()` because a
category isn't a threshold-crossing number.** Requires `SCENARIO_TYPE_PERSISTENCE_N` (6)
consecutive agreeing days before accepting a `scenario_type` (initial confirmation or a change).
**Empirically derived, not guessed** — swept N=4..10 against subject 14's real 5-day
`fluid_overload` streak AND a constructed 15-day genuine, permanent `stable`→`acute_deterioration`
change (not from either real subject's data, and long enough to exceed every N tested, so a large
N can't trivially "pass" by never running long enough to matter):

| N | Suppresses the real 5-day misclassification? | Confirms the constructed genuine change? |
|---|---|---|
| 4, 5 | No — confirms the wrong value | Yes (lag = N−1 days) |
| **6 (chosen)** | **Yes — never confirmed** | **Yes (5-day lag)** |
| 7, 8, 10 | Yes | Yes (longer lag) |

N=5 exactly matching the streak length still confirms it — the general principle (**N must
exceed the longest observed spurious streak, not just match it**) is sound and empirically
demonstrated; N=6 itself rests on a single observed spurious-streak length (n=1 real case), not a
statistically robust bound. **This is a real, structural tradeoff, not a free fix**: every
increase in N that suppresses a longer spurious streak also delays every genuine change's
confirmation by exactly that many more days.

**3. `STABLE_SEVERITY_CAP` explicitly labeled, not left as an ambiguous "reference"/"marker."**
Stated plainly, in both `generate_patients.py`'s and `score_reporting.py`'s own comments: **it is
an ENGINEERING CONSTANT, not a clinical threshold.** It originated as a synthetic-data-generation
parameter and is reused elsewhere only because it's the one non-arbitrary number already in this
codebase — not because 0.15 carries clinical meaning about real heart failure severity.

**4. Genuine-recovery hysteresis test added** (`tests/test_score_reporting.py`'s
`test_genuine_sustained_recovery_clears_alert_state` and
`test_recovery_then_relapse_re_enters_alert`) — a sustained improvement (2+ consecutive days below
`EXIT_THRESHOLD`, not a transient one-day dip) correctly clears `"alert"` back to `"no_alert"`,
and a later sustained relapse correctly re-enters `"alert"` — confirming
`hysteresis_alert_states()` is a real two-way mechanism, not a one-way latch, as the positive-case
complement to the existing dip-suppression test.

**5. `threshold_clinically_validated: false` added as an explicit field** on every
`build_score_report()` output (and `RiskAssessmentPayload.score_provenance` in the API schema) —
a fixed, always-present statement that none of this project's thresholds (`STABLE_SEVERITY_CAP`,
`MIN_CONFIDENCE_FOR_ALERT`, `CONFIDENCE_BY_STATUS`, `ENTER_THRESHOLD`/`EXIT_THRESHOLD`,
`SCENARIO_TYPE_PERSISTENCE_N`, or `risk_score.py`'s own `LOW_HIGH_BOUNDARY`/
`MODERATE_HIGH_BOUNDARY`) has been checked against real outcome data — so a caller never has to
infer this from scattered docstrings.

**6. Future-calibration interface defined, deliberately not populated** —
`src/analytics/outcome_calibration.py` (new): `LongitudinalObservation` (patient_id, timestamp,
free-form `measurements` dict), `KnownOutcome` (event_type, event_date,
days_from_observation_to_event, source), and `CalibrationRecord` pairing the two. No real patient
data, no ingestion/storage/ordering logic — purely the contract a future Sprint 3/5 calibration
pass would need to fit/validate every placeholder constant named in point 5 above against whether
it actually predicts real outcomes. That design work (ingestion, ordering, deduplication) is
explicitly left to whoever does it once a real dataset is identified, not stubbed out
speculatively here.

**Verification:** 236/236 tests pass (218 Sprint-2 baseline + 18 new: root-cause-informed
`TestScenarioTypePersistence` including the full N-sweep, the two new genuine-recovery hysteresis
tests, `threshold_clinically_validated` presence checks, and `tests/test_outcome_calibration.py`
(new) confirming the calibration contract's dataclasses are well-formed and immutable).

### Option A (2026-09-10): attempted rolling-window curvature features for the scenario
### classifier — regressed on held-out validation, reverted

**Proposal:** give `_wearable_features()` additive `{vital}_early7_slope`/`{vital}_late7_slope`
sub-window fits (over the same first-7/last-7 spans as the existing `first7_mean`/`last7_mean`),
on top of — not replacing — the existing whole-window `slope`, specifically to make the
`frac**2` acceleration behind point 1 above (Sprint 2.5's day 6-10 root cause) directly visible
to the model as a feature, rather than something a single whole-window linear fit averages away.

**Held-out re-validation (same 300 test patients, same `seed=42` split, verified identical
patient-ID membership before trusting the comparison) regressed:** accuracy flat (90.7% → 90.7%),
but severity MAE 0.0473 → 0.0506 (+7%) and RMSE 0.0613 → 0.0646 (+5%); `acute_deterioration`
recall/F1 dropped 0.88/0.89 → 0.83/0.87. Reverted per this project's own stated bar (held-out
performance is the gate; a regression there isn't kept regardless of the motivating theory) —
`_wearable_features()` is back to the original four-aggregate-per-vital form, no
`.joblib`/`phase3_eval_report.txt` artifacts were touched.

**Refined finding on the regression's cause, from a per-patient breakdown of the 3 net new
`acute_deterioration` misclassifications:** the added curvature features did **not** worsen the
specific day 6-10 confusion they targeted — patients misclassified as `fluid_overload` stayed
flat at 6 before and after (some individual patients cycled in and out of that bucket, but the
count didn't move). What they introduced instead was a **new, severity-gated failure mode**: all
4 newly-wrong patients (net 3, after one unrelated improvement) are low-severity
(0.091–0.163, mean 0.143) against a 0.579 mean for patients still classified correctly, and their
`early7_slope`/`late7_slope` ratios are flat-to-reversed (≈1.0, one case 0.78) versus 1.7–2.3×
acceleration for correctly-classified higher-severity peers. At low severity, `frac**2`'s
acceleration genuinely hasn't bent the curve yet by day 21 — so `early7_slope`/`late7_slope`,
each a linear fit over only 7 points (far noisier than the original 21-point whole-window
`slope`), carry mostly noise rather than the intended curvature signal in exactly that region,
and that noise is what pushed borderline-severity patients toward whichever neighboring class
they already sat closest to (fluid_overload, cardiac_stress, or deconditioning — no single
target). **This refines rather than confirms Sprint 2.5's physiological-ambiguity theory**: the
ambiguity is real, but it's severity-gated (a signal-to-noise problem: no reliable acceleration
signal exists yet to extract, at any window granularity) rather than day-gated (a windowing
problem, where a differently-shaped feature could recover a signal that's genuinely present but
hidden by aggregation) — so narrower sub-window slopes were not the right lever for it.

## 9. Future Work

Everything below is a real candidate for continued work, not a padded wishlist — each item is
either an explicit Phase 9 stretch goal from the original roadmap that Phases 0-8 deliberately
didn't need to solve, or a next step toward the team's stated goal of turning this system into a
research paper once the pipeline is validated end-to-end (§7/§8).

**Directly motivated by the continuous-state-sync investigation (2026-08-30/09-01,
`docs/continuous_state_sync_status.md`):**
- **Fluid_overload scenario lacks a volume-loading mechanism** — full mechanism, root cause, and
  why it isn't fixed yet in §8's new entry of the same name. Not started; needs a real
  volume-loading Pulse action added to the scenario definition, plus re-running Phase 2 validation
  and likely retraining the severity regressor. Currently safely mitigated by
  `baseline_deficit_score`/`max()` (§6.1), not a patient-safety gap.

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
- **DONE — expanded the batch validation from n=5/scenario to n=10/scenario (n=50 attempted),
  across three sessions (2026-08-12, 2026-08-17, 2026-08-18), using
  `scripts/nyha_fix_live_revalidation.py`'s `--resume-from` to top up incrementally rather than
  re-running from scratch each time (n=5→n=20→n=27→n=45 completed).** Final, current numbers —
  recomputed fresh at the actual achieved n each time, never reused from a smaller prior run:
  **n=45/50 completed (90%)**, live severity MAE **0.0264** [95% bootstrap CI 0.0194, 0.0352,
  2000 resamples], scenario accuracy **1.0000** [95% CI 1.0000, 1.0000]. Consistent across every
  expansion step (n=20: MAE 0.0275 [0.0188, 0.0394]; n=27: MAE 0.0247 [0.0171, 0.0336]; n=45: MAE
  0.0264 [0.0194, 0.0352]) — the point estimate has stayed in a tight ~0.025-0.028 band the whole
  way, well below the pre-fix 0.271 and in the same range as the 0.047 offline benchmark, so this
  reads as a stable, real result rather than one that happened to look good at a smaller n.
  **n=45, not n=50, is the reportable number** — 5 of the 50 sampled patients failed
  deterministically. **These failures are consistent with, not additional to, the
  Exercise-action instability already characterized in "Known Engine Constraints" (§8)** — same
  mechanism, same crash signature, not a new bug (see the Mechanism 1 discussion above for the
  specific 5 patient IDs, and §8 for the full root-cause trace). Full run data:
  `data/validation_runs/20260818_104827_nyha_fix_revalidation/` (this session's top-up) and
  `combined_results.csv` there for the full merged n=50-attempted set.

**Deferred engineering (Phase 9, roadmap-defined):**
- **Tier 2 personalization** (echo/PPG-derived vascular compliance) — see §3 for exactly why it
  was never load-bearing for Phases 0-7's results; still a legitimate accuracy lever if a suitable
  echo/PPG dataset is acquired.
- **Self-calibrating baseline** — currently a patient's Pulse-input parameters are set once at
  onboarding and never adjusted; comparing the twin's predicted vitals against a patient's actual
  incoming wearable readings and iteratively correcting the baseline would make the simulation
  converge toward that specific patient over time, rather than staying fixed at intake values.
  **Design constraint, discovered not hypothesized (§12/`docs/bcg_validation_note.md`):
  correcting `HeartRateBaseline` alone is a known-bad approach** — tested on both real BCG-dataset
  patients, forcing HR baseline toward the real value reduced simulated stroke-volume accuracy in
  both cases (less diastolic filling time at the corrected, higher HR), while barely moving CO
  accuracy. Any implementation of this item must jointly adjust HR baseline together with the
  circuit-level compliance/resistance parameters identified as the dominant SV/CO driver in that
  validation, not HR in isolation.
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

## 12. Real-Patient BCG Validation (Single-Patient Extension)

**Status: done, two patients.** Full methodology (subject selection/rejection reasoning, BCG
feature extraction, citations, results, all limitations) is in `docs/bcg_validation_note.md` —
this section summarizes the headline findings only; that document carries the evidence.

Every result in §5-§7 above is validated against synthetic data, offline batch simulation, or
MIMIC-IV vitals alone (§7.X) — never against a real patient with real echo-measured EF/SV *and* a
personalization-grade physiological waveform. This extension closes a narrow slice of that gap:
subjects 14 and 102 from the Zhan et al. (2025) Multi-Pathology Ballistocardiogram Dataset
(figshare 10.6084/m9.figshare.28416896) were each run through the full `patient_builder` →
`ef_to_cardiovascular_modifiers` → `run_pulse()` pipeline with real demographics/EF, plus a new
`bcg_to_cardiovascular_modifiers()` (`src/patient_builder/patient_file.py`) mapping each subject's
own extracted R-J interval and I-J/J-K amplitude to `VenousComplianceMultiplier`/
`SystemicComplianceMultiplier` — the Tier 2 vascular-compliance personalization §3 scoped but never
built, substituting ballistocardiography for the echo/PPG data that was never acquired (BCG is a
different mechanical signal, used because it's what this dataset provides, not claimed as
equivalent — see the validation note's Limitations).

**Headline findings:**
- **Both patients' simulated resting SV/CO undershoot real echo-measured values by roughly
  45-55%** (subject 14: SV 0.58x, CO 0.54x; subject 102: SV 0.87x, CO 0.55x, using its
  clinical-sheet HR since its own session HR was independently found unreliable — see below). Root
  cause was traced stage by stage, not just attributed to "the engine doesn't take SV as input":
  **71.3% of subject 14's shortfall comes from Pulse's generic anthropometric SV baseline itself**
  (Age/Height/Weight/Sex alone, before any EF or BCG input), **28.7% from the
  `ChronicVentricularSystolicDysfunction` condition's fixed elastance cut**, and **0% from the
  continuous `StrokeVolumeMultiplier`** in this comparison (it fires later than the point compared).
  A height-isolation counterfactual (same age/weight, 160cm vs. 175cm) confirmed the anthropometric
  baseline does **not** scale with height — Pulse's own "outside typical range" warnings are
  decoupled from the actual SV shortfall, not its cause.
- **HR-baseline non-personalization, demonstrated across two patients with opposite outcomes.**
  `build_patient_file()` deliberately never sets a patient-specific HR baseline (same
  "modify-inputs-not-outputs" design as blood pressure, §4). Subject 14's simulated HR (72.27)
  happened to land close to its real 77 bpm (0.94x) — a coincidence, not personalization accuracy.
  Subject 102 makes this explicit: using its reliable ground truth (xlsx HR 115, not its own
  unreliable 52.8 bpm session value — see below) gives a much worse 0.63x ratio for the *same*
  underlying non-personalization, confirming the first patient's closeness was luck, not signal.
- **n=2 BCG reference points produced a structural, not clinical, null result on one term each
  run — demonstrated symmetrically.** `bcg_to_cardiovascular_modifiers()` has no population
  reference (only 2 subjects' BCG data exist in this project), so each run uses the *other*
  subject's measurements as its single reference point. Result: subject 14's run left
  `SystemicComplianceMultiplier` inert (1.0) while `VenousComplianceMultiplier` was active (0.901);
  subject 102's run (referenced against subject 14) showed the exact mirror image
  (`VenousComplianceMultiplier` inert at 1.0, `SystemicComplianceMultiplier` active at 0.95). This
  is a known consequence of n=2, not evidence either BCG feature is clinically uninformative.
- **One data-quality finding with no resolution:** subject 102's own XJ-session HR (52.8 bpm,
  R-R-derived) showed an unexplained 2.15x mismatch against its own clinical-sheet HR (115 bpm),
  confirmed real (via the dataset's own rendered signal plot) rather than a sample-rate bug in this
  project's extraction, and not reproduced in three other subjects' cross-checks. The source paper
  offers no explanation. Subject 102's clinical-sheet HR was used as ground truth for its HR
  comparison instead of its own session value — a deliberate, documented asymmetry from subject
  14's validation (see the note for the full reasoning).

**Scope, stated as plainly as §7.X does for the MIMIC-IV work above:** this is a two-patient
pipeline-mechanics check, not a cohort validation, and does not validate ML Model 1 (no
wearable-trend window exists for a single-session dataset — `scenario_type`/severity were assigned
manually from real EF/diagnosis) or the R-J-to-compliance/amplitude-to-compliance literature
mappings against outcomes (single-study citations, not independently validated here). See
`docs/bcg_validation_note.md`'s Limitations section for the full list, including the M-mode-vs-
Simpson's-biplane EF measurement-method inconsistency across this project's data sources.
