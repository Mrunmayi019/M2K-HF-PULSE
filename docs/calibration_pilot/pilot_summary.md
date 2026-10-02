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

A simpler arm was added afterwards: **Arm C, "direct-set"**, pre-registered as Amendment 2. Its
CO rule passed in one patient set and failed in the other, and its mean CO error was larger than
the production twin's (33.2% vs 24.9%). **Arm C is not adopted** (see "Arm C" below).

## What was run

- **48 Pulse 4.3.1 runs, all in Docker, one at a time. None crashed.** Every run in the scan and
  the BP check settled, meaning ≤ 2% drift between the last two 60 s windows; one Arm C tuning run
  did not, and it was not a final run.
  - **Arm A:** 9 runs (`arm_a_report.md`).
  - **Knob scan:** 14 runs (`sensitivity_report.md`).
  - **Blood-pressure check:** 11 runs (`bp_check_report.md`).
  - **Arm C:** 14 tuning runs (`arm_c_report.md`). One extra Arm C run was thrown away when a
    script bug aborted the first attempt; its rerun gave the same result.
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

## Arm C: direct-set twins (not adopted)

**How the twins were built** (pre-registered in Amendment 2):
- Each patient's own body was used (with the BMI clamp, age 60), and each twin was given the
  patient's own resting HR and blood pressure as Pulse baselines.
- Blood pressure was moved to the nearest pair Pulse accepts: systolic capped at 120 for 295, 120
  and 56, and diastolic at 80 for 120.
- The weak-heart condition was on for EF ≤ 40.
- StrokeVolumeMultiplier was tuned by bisection, at most 4 runs per patient, until twin EF was
  within 2 points of echo EF. Patient 136 did not get there: the closest was 37.85 against 40.
- Cardiac output and stroke volume were held out and used only for scoring.

**Arm A-prod (production twin) vs Arm C, % error against the real value:**

| Patient | Arm | EF | HR | MAP (formula) | SV | CO vs CO_td | CO vs CO_fick |
|---|---|---|---|---|---|---|---|
| 295 | A-prod / C | +1.0 / −1.5 | −9.2 / −0.4 | −15.7 / −17.9 | +42.2 / +45.3 | **+29.1 / +44.7** | −5.2 / +6.3 |
| 136 | A-prod / C | −32.2 / −5.4 | +30.7 / −6.6 | −2.2 / −14.8 | −19.5 / +1.6 | **+5.2 / −5.2** | +57.8 / +42.3 |
| 120 | A-prod / C | −6.0 / −0.2 | −21.5 / −7.7 | −15.7 / −10.9 | +82.1 / +77.3 | **+42.9 / +63.7** | +59.4 / +82.6 |
| 56 | A-prod / C | +8.8 / +1.5 | +21.5 / −4.1 | −22.6 / −23.2 | −8.2 / −0.8 | **+11.5 / −4.9** | +5.1 / −10.4 |
| 242 | A-prod / C | −23.5 / −1.0 | −27.2 / −20.1 | −18.9 / −18.2 | +49.9 / +67.3 | **+9.2 / +33.7** | +4.8 / +28.3 |
| 264 | A-prod / C | +0.1 / +1.1 | −15.4 / −1.2 | +20.3 / +0.1 | +79.1 / +48.8 | **+51.5 / +47.0** | +50.3 / +45.8 |

Mean absolute error across the 6 patients:

| | CO vs CO_td | CO vs CO_fick | SV |
|---|---|---|---|
| Arm A-prod | 24.9% | 30.4% | 46.8% |
| Arm C | 33.2% | 36.0% | 40.2% |

Source: `arm_c_report.md`, `arm_c_results.csv`, `arm_a_results.csv`.

**What improved.**
- EF and HR, as expected, because they were set directly. EF is within 2.2 points for all 6.
- Stroke volume was closer for 4 of 6 patients (136, 120, 56, 264).
- CO vs CO_td was closer for 3 of 6: 56, 264, and 136 by only 0.04 points.

**What got worse.**
- CO vs CO_td was further off for 295, 120 and 242. For 242 it went from +9.2% to +33.7%.
- Mean absolute CO_td error rose from 24.9% to 33.2%.
- The pre-registered CO rule was met in the consistent set (2 of 3) and not in the original set
  (1 of 3).

**Set HR did not always hold.**
- Patient 242 was set to 97.25 and ran at 77.7.
- Patient 136 was set to 54.5 and ran at 50.9. Across its tuning runs HR ranged from 46.0 to 56.6,
  falling as StrokeVolumeMultiplier rose.
- The others stayed within about 8% of the set value.

**Set blood pressure did not hold with the condition on.** For the 4 patients with the weak-heart
condition, the twin's systolic ended 12.1–23.4 mmHg and its diastolic 10.6–18.7 mmHg below the
set pair (for example, 295 was set to 120/67.5 and ran at 101.8/56.9). Formula-MAP errors stayed between −14.8% and −23.2%. With
the condition off (120 and 264), the set pair held within about 3 mmHg.

**Limits specific to Arm C.**
- 6 patients, with one final run each.
- The starting guesses came from a scan on one body (patient 120).
- Age assumed 60.
- One patient (136) missed the EF target.

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
