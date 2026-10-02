# Calibration pilot — summary (closed 2026-10-02)

Branch `experiment/calibration-pilot`. All files below are under `data/calibration_pilot/` unless a
path is given.

## The question

Would inverse calibration of Pulse knobs, following Gu et al. (npj Digital Medicine 2025), give a
twin that matches real patients better than the current formula, `ef_to_cardiovascular_modifiers()`?
The success rule (Arm B vs Arm A, cardiac output) was committed before any run, and an amendment was
committed before the second patient set was chosen (`pilot_success_criteria.md`).

**Outcome: the pilot was closed before Arm B was built.** The success rule was never evaluated.
A feasibility check found the twin could reach each patient's real EF, HR and MAP for only 1 of 6
patients, against a bar of 4 of 6 that was set in discussion but not committed beforehand (see the
closing note in `pilot_success_criteria.md`).

## What was run

- **34 Pulse 4.3.1 runs. None crashed, and every run in the scan and the BP check settled** (≤ 2%
  drift between the last two 60 s windows).
  - **Arm A:** 9 runs (`arm_a_report.md`).
  - **Knob scan:** 14 runs (`sensitivity_report.md`).
  - **Blood-pressure check:** 11 runs (`bp_check_report.md`).
- **Patients:** 6 from Gu's TriSeg dataset (`pilot_patients.csv`).
  - 3 fixed in advance: 295, 136 and 120.
  - 3 chosen by a written rule, out of 15 of 370 patients that passed: 56, 242 and 264
    (`selection_log.md`).

## Findings

1. **The production twin has only two EF settings and ignores HR.**
   - Under scenario `stable`, the formula's multipliers are computed but never reach Pulse. Only
     the weak-heart condition (EF ≤ 40) does.
   - Twin EF is therefore about 25–27% for every EF ≤ 40, and the untouched default (about 54–56%)
     above that. Patients 295 (EF 25) and 136 (EF 40) received identical settings.
   - Twin HR was 70.8–73.2 bpm in all 9 runs, while real HR was 54.5–97.3.
   - Source: `arm_a_report.md`.
2. **EF can be made continuous with StrokeVolumeMultiplier.** The twin reached EF 23.6–49.6% with
   the condition on and 42.8–64.9% with it off. The two ranges overlap, covering 23.6–64.9% in
   total. Source: `sensitivity_report.md`, `bp_check_report.md`.
3. **HR baseline works with the condition off, but did not hold with it on.**
   - Off: set 55 → 54.8, set 90 → 89.6, and set 90 → 86.9 with StrokeVolume 0.8.
   - On: set 90 held through stabilization and then fell to 70.8 once StrokeVolume 1.2 was
     applied. This was tested in one run only.
   - Source: `bp_check_report.md` (E runs).
4. **MAP is set only by the blood-pressure baseline.**
   - Pulse accepts systolic/diastolic 90/60 to 120/80.
   - The condition is applied after Pulse tunes to that baseline, with no re-tuning, and cuts MAP
     by 16–17%.
   - No tested modifier raised MAP by more than 1.1%.
   - Reached MAP, Pulse output / formula:

     | | Pulse output | Formula |
     |---|---|---|
     | Condition off | 76.5–101.2 | 70.3–93.5 |
     | Condition on | 63.7–83.6 | 59.9–78.5 |

   - Source: `bp_check_report.md`.
5. **Pulse's input limits exclude real patients.** These are in Pulse 4.3.1's `SetupPatient.cpp`.
   Outside them the engine refuses to start; it does not clamp.

   | Input | Pulse accepts | Effect on the 6 pilot patients |
   |---|---|---|
   | Systolic | 90–120 | 3 of 6 outside (295, 120, 56) |
   | Diastolic | 60–80 (and ≤ 0.75 × systolic) | 120 outside (90) |
   | BMI | 16–30 | 295 outside (30.65; the builder clamped weight to 83.26 kg) |
   | Age | 18–65 | not testable (age unreadable, assumed 60) |
   | HR baseline | 50–110 | all 6 inside |

6. **Pulse's MAP output is not the formula MAP.** Pulse reports a time average of the pressure
   wave, which ran above (2·DBP + SBP)/3 computed from the same run's own pressures. Across all 34
   runs the gap was 3.9–11.5 mmHg:

   | | Median gap | Middle half of runs |
   |---|---|---|
   | Condition off | 7.6 mmHg | 7.0–8.2 |
   | Condition on | 5.1 mmHg | 5.0–5.3 |

   For example, the run tuned to 120/80 gave 101.2 vs 93.5. The real MAP uses the formula, so
   like-for-like comparison needs the formula. `arm_a_results.csv` now carries both.
7. **Gu's own measurements disagree for some patients.**
   - CO by thermodilution vs Fick: 4.53 vs 3.02 for patient 136, and 3.40 vs 4.63 for 295.
   - Echo vs MRI EF: 58 vs 28.4 for patient 120.
   - Only 129 of 361 complete patients had the two CO measurements within 10% of each other, and
     68 also had the two EFs within 7 points.
   - Source: `pilot_patients.csv`, `selection_log.md`.

## Limits

- **6 patients and single runs.** There are no repeat runs, so there is no run-to-run spread.
  Pulse was deterministic in earlier tests, but that wasn't re-checked here.
- **One body.** The scan and the BP check used only patient 120's body. The "reach" ranges are the
  extremes seen, not proven limits, and each variable was judged on its own: no run hit a
  patient's EF, HR and MAP together.
- **Age assumed 60** for all patients, because Gu's birth dates are MATLAB datetime objects that
  scipy can't read.
- **Real values aren't simultaneous.** The cuff BP, echo EF and catheter CO weren't taken at the
  same moment.

## Not tested

- **Arm B** (calibration), so the question above is unanswered.
- **Any early-warning or trend performance.** Every run was a resting snapshot.
- **Untested settings:** knobs other than the ones listed, combinations beyond the E runs, and
  any scenario other than `stable`.

## Suggested additions to methodology.md and data_provenance.md (proposals only, not applied)

1. **`methodology.md` §4 (Pulse integration):** after the age/BMI limits at line 102, add Pulse's
   blood-pressure baseline limits (SBP 90–120, DBP 60–80, DBP ≤ 0.75·SBP) and HR baseline limits
   (50–110). State that the engine refuses to start outside them, and that the builder currently
   sets neither, so every twin runs at Pulse's default pressure (114/73.5 target).
2. **`methodology.md` §4:** record that under `scenario_type="stable"` the
   `ef_to_cardiovascular_modifiers()` multipliers are discarded, so EF above 40 has no effect on
   a stable twin. Also record that the systolic dysfunction condition is applied after Pulse's
   circulation tuning and lowers MAP by 16–17% with no re-tuning.
3. **`methodology.md` §8 (Limitations):** state that Pulse's `MeanArterialPressure` is a
   time-averaged value, 3.9–11.5 mmHg above the (2·DBP + SBP)/3 formula used for real cuff MAP in
   this pilot (median 7.6 with the condition off, 5.1 with it on). Any
   comparison of twin MAP with real MAP should use the formula on the twin's own SBP/DBP.
4. **`data_provenance.md`, "Assumed healthy resting MAP" row (92.5 mmHg, line 89):** note that its
   internal citation ("stable scenario MAP 95") is Pulse's time-averaged output. The
   formula-equivalent for the same default twin is about 87 mmHg (`bp_check_report.md`).
5. **`data_provenance.md`, new row:** the Gu et al. TriSeg dataset (MIT license,
   `data/raw/gu_triseg/`, gitignored), as used by this pilot only. Include the Sex coding
   (1 = male) and valve-grade coding found in `selection_log.md` / Amendment 1.
