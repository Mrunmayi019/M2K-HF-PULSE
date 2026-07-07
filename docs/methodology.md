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
- Simulation dataset: self-generated via Pulse batch runs (Phase 4, not yet started)

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

TODO — Phase 3 (scenario classifier) and Phase 5 (risk scorer), not started.

## 6. Risk Scoring Logic, With Clinical Citations

TODO — Phase 5. Primary model is the hand-tuned interpretable weighted score (locked decision);
XGBoost on the Pulse batch dataset is secondary/experimental only.

## 7. Validation Approach and Results

**Phase 1** (data synthesis): see `tests/test_data_synthesis.py` (15 checks: schema, clinical
correlation direction, trend shapes).

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
- Small simulation dataset planned for the risk scorer (Phase 4, not yet run).
- No medication-effect modeling in Pulse scenarios.
- Simulations run under `arm64`→`amd64` Docker emulation on this development machine; each
  simulated scenario takes ~2 minutes wall-clock (vs. Pulse's own ~30s reported internally),
  which will matter for Phase 4's planned 150+ batch runs.

## 5. ML Model Design, Training, Evaluation

TODO — Phase 3 (scenario classifier) and Phase 5 (risk scorer), not started.

## 6. Risk Scoring Logic, With Clinical Citations

TODO — Phase 5. Primary model is the hand-tuned interpretable weighted score (locked decision);
XGBoost on the Pulse batch dataset is secondary/experimental only.

## 7. Validation Approach and Results

TODO. Phase 1 data-synthesis validation lives in `tests/test_data_synthesis.py` for now — this
section will summarize those results once the full dataset is generated.

## 8. Limitations

TODO — write honestly at the end, per CLAUDE.md conventions. Known ones already flagged in the
planning doc: no real clinical validation, wearable sensor error not modeled, small simulation
dataset for the risk scorer, no medication-effect modeling in Pulse scenarios.

## 9. Future Work

TODO. Tier 3 (ECG-derived BP/contractility) belongs here only — never implement it (locked decision).
