# Calibration pilot — Arm A baselines (old design)

Run 2026-10-02 on branch `experiment/calibration-pilot` (from `feature/real-outcome-validation`),
`kitware/pulse:4.3.1`. The success criteria were committed before any run (`edc2d44`,
`docs/calibration_pilot/pilot_success_criteria.md`). Code: `scripts/calibration_pilot_extract_gu.py`,
`scripts/calibration_pilot_arm_a.py`. Full data: `arm_a_results.csv`, `arm_a_run_status.json`,
`arm_a_knobs.json`, `runs/<arm>/gu<idx>/`.

**Setup.** `scenario_type="stable"`, `severity=0`, `duration_min=2`: the builder's 60 s, then
120 s at rest, 180 s in total. Metrics come from the final 60 s (t = 120–180 s). Twin EF is computed
per complete beat from `LeftHeart-Volume(mL)` as (EDV − ESV)/EDV, and the table gives the mean
across beats (71–72 beats per run, SD in the CSV). Real MAP = DBP + (SBP − DBP)/3. Errors are
(twin − real)/real.

**Under scenario `stable`, `ef_to_cardiovascular_modifiers()`'s multipliers never reach Pulse.**
`_scenario_actions()` returns no actions for `stable`, so the only part of the formula that is
applied is the `ChronicVentricularSystolicDysfunction` condition (EF ≤ 40). In Arm A-prod, an EF
above 40 therefore has no effect on the twin at all. Arm A-formula adds the multipliers as a
`CardiovascularMechanicsModification` at t = 60 s, in the new pilot script only.

## Results

| Arm | Patient | Real EF | Twin EF | Err | Real MAP | Twin MAP | Err | Real CO | Twin CO | Err | Real HR | Twin HR | Err | Crashed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A-prod | 295 | 25 | 25.25 | +1.0% | 87.50 | 78.77 | −10.0% | 3.40 | 4.391 | **+29.1%** | 78.0 | 70.83 | −9.2% | no |
| A-prod | 136 | 40 | 27.12 | −32.2% | 75.67 | 79.08 | +4.5% | 4.53 | 4.766 | **+5.2%** | 54.5 | 71.26 | +30.7% | no |
| A-prod | 120 | 58 | 54.55 | −6.0% | 103.50 | 95.18 | −8.0% | 3.67 | 5.246 | **+42.9%** | 91.5 | 71.83 | −21.5% | no |
| A-formula | 295 | 25 | 25.25 | +1.0% | 87.50 | 78.77 | −10.0% | 3.40 | 4.391 | +29.1% | 78.0 | 70.83 | −9.2% | no |
| A-formula | 136 | 40 | 27.12 | −32.2% | 75.67 | 79.08 | +4.5% | 4.53 | 4.766 | +5.2% | 54.5 | 71.26 | +30.7% | no |
| A-formula | 120 | 58 | 52.47 | −9.5% | 103.50 | 95.12 | −8.1% | 3.67 | 5.474 | +49.1% | 91.5 | 73.20 | −20.0% | no |

Units: EF %, MAP mmHg, CO L/min, HR bpm.

Knobs produced by the formula (severity 0):

| Patient | Systolic dysfunction condition | SV mult | Resistance mult | Compliance mult |
|---|---|---|---|---|
| 295 | applied | 1.000 | 1.000 | 1.000 |
| 136 | applied | 1.000 | 1.000 | 1.000 |
| 120 | not applied | 0.891 | 0.935 | 0.935 |

## Observations

1. **Patients 295 (EF 25) and 136 (EF 40) received identical knobs.** Both had the condition
   applied and all multipliers at 1.000, because at severity 0 the formula sets `combined = 0`
   once the condition applies. Their twin EFs are 25.25% and 27.12%. The small difference comes
   from body size and sex, not from EF.
2. Twin HR was 70.8–73.2 bpm in all 6 runs, while the real values were 54.5, 78.0 and 91.5. No
   HR baseline is set in this design, so Pulse uses its own default.
3. Twin CO was higher than real CO for all 3 patients in Arm A-prod: +5.2%, +29.1% and +42.9%.
4. In Arm A-formula, patients 295 and 136 produced results **bit-identical** to Arm A-prod
   (`scenarioResults.csv` byte-identical). Their action is all-1.000 multipliers, which
   evidently changes nothing. For patient 120 the multipliers moved twin EF from 54.55% to 52.47%
   and CO from 5.246 to 5.474 L/min.
5. None of the 6 runs crashed, and no log line matched `runner.FATAL_LOG_MARKERS`. The only
   engine warnings were Pulse's "BMI ... overweight, no guarantees of model validity" for patients
   295 (BMI 29.5 after clamping) and 120 (BMI 25.9).

## Assumptions

- **Age is assumed to be 60 for all 3 patients.** Gu's `Birthday` (and every date field) is a
  MATLAB datetime object that scipy returns as an opaque MCOS handle, so it can't be read. 60 is
  inside Pulse's 18–65 range, so the age clamp didn't apply.
- **Patient 295's weight was clamped from 86.5 to 83.26 kg** (BMI 30.65 → 29.5) by the unchanged
  `build_patient_file()`, because Pulse rejects BMI ≥ 30.
- **Sex coding:** 1 = Male, 2 = Female, verified in `targetVals_HF.m:33-37`. The male Nadler
  equation is used for `Sex == 1`, and the female branch has `assert(Sex == 2)`.
- **Real values come from Gu's first snapshot, unrounded.** The plan's CO_td values were rounded
  for two patients: 136 is 4.53 (plan 4.5) and 120 is 3.67 (plan 3.7). The dataset values are
  used.
- **Real CO is thermodilution CO_td** (from right-heart catheterisation). **Real MAP comes from
  the non-invasive cuff (NIBP).** **Real HR is HR_vitals.** These are not necessarily measured at
  the same moment as the echo EF.

---

## Addendum — Amendment 1 (2026-10-02)

Added after Amendment 1 to `pilot_success_criteria.md` (commit `a89be0d`). The 3
"measurement-consistent" patients were selected by `scripts/calibration_pilot_select_consistent.py`
(see `selection_log.md`). They were run as Arm A-prod only, with settings identical to the original
A-prod runs: `stable`, severity 0, 60 s + 120 s, last 60 s, age assumed 60, no HR baseline set. None
needed a weight clamp. `arm_a_results.csv` now also carries twin EDV/ESV/SV and the errors against
CO_fick and SV. The original rows were recomputed from the same output files, and their existing
columns are unchanged.

Real SV = CO / HR_vitals. Twin SV = twin CO / twin HR. Twin EDV and ESV are per-beat means from
`LeftHeart-Volume(mL)`.

### Arm A-prod, all 6 patients

| Set | Patient | EF real / twin (err) | MAP real / twin (err) | CO_td / CO_fick / twin | err vs td / vs Fick | SV td / Fick / twin (mL) | SV err td / Fick | HR real / twin (err) | Twin EDV / ESV | Crashed |
|---|---|---|---|---|---|---|---|---|---|---|
| original | 295 | 25 / 25.25 (+1.0%) | 87.5 / 78.8 (−10.0%) | 3.40 / 4.63 / 4.39 | +29.1% / −5.2% | 43.6 / 59.4 / 62.0 | +42.2% / +4.4% | 78.0 / 70.8 (−9.2%) | 245.5 / 183.6 | no |
| original | 136 | 40 / 27.12 (−32.2%) | 75.7 / 79.1 (+4.5%) | 4.53 / 3.02 / 4.77 | +5.2% / +57.8% | 83.1 / 55.4 / 66.9 | −19.5% / +20.7% | 54.5 / 71.3 (+30.7%) | 246.6 / 179.8 | no |
| original | 120 | 58 / 54.55 (−6.0%) | 103.5 / 95.2 (−8.0%) | 3.67 / 3.29 / 5.25 | +42.9% / +59.4% | 40.1 / 36.0 / 73.0 | +82.1% / +103.1% | 91.5 / 71.8 (−21.5%) | 133.9 / 60.9 | no |
| consistent | 56 | 25 / 27.19 (+8.8%) | 95.8 / 79.3 (−17.3%) | 4.40 / 4.67 / 4.91 | +11.5% / +5.1% | 75.2 / 79.8 / 69.1 | −8.2% / −13.5% | 58.5 / 71.1 (+21.5%) | 254.0 / 185.0 | no |
| consistent | 242 | 33 / 25.25 (−23.5%) | 91.0 / 78.8 (−13.4%) | 4.03 / 4.20 / 4.40 | +9.2% / +4.8% | 41.4 / 43.2 / 62.1 | +49.9% / +43.9% | 97.3 / 70.8 (−27.2%) | 246.1 / 183.9 | no |
| consistent | 264 | 56 / 56.03 (+0.1%) | 72.3 / 95.4 (+31.8%) | 3.87 / 3.90 / 5.86 | +51.5% / +50.3% | 45.5 / 45.9 / 81.5 | +79.1% / +77.7% | 85.0 / 71.9 (−15.4%) | 145.5 / 64.0 | no |

Units: EF %, MAP mmHg, CO L/min. MRI EF for reference (`pilot_patients.csv`): 295 → 20.7,
136 → 30.5, 120 → 28.4, 56 → 23.4, 242 → 31.8, 264 → 49.4.

### Observations

1. Twin HR was 70.8–71.9 bpm for all 3 new patients (real 58.5, 97.25, 85.0), the same pattern as
   the original set.
2. Patients 56 (EF 25) and 242 (EF 33) both had the condition applied and no multipliers. Their
   twin EFs are 27.19% and 25.25%. Patient 264 (EF 56) had no condition and twin EF 56.03%.
3. Twin CO was above both CO_td and CO_fick for all 3 new patients: +4.8% to +51.5%.
4. For patient 120, echo EF is 58 and MRI EF is 28.4, and twin SV (73.0 mL) is about twice the
   real SV (40.1 mL from td, 36.0 mL from Fick). Patient 120 is also the scan patient in Part 4.
5. No run crashed. Engine warnings: BMI-overweight messages for 56/242/264, plus "height of 191 cm
   is outside of typical ranges - above 97th percentile (163 cm)" for patient 56. The 163 cm in
   that message is Pulse's own text, reproduced as-is.
