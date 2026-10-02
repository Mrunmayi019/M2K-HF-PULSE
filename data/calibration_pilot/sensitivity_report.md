# Calibration pilot — knob sensitivity scan (Part 4)

Run 2026-10-02 on `kitware/pulse:4.3.1`. Script: `scripts/calibration_pilot_sensitivity_scan.py`.
Full data: `sensitivity_scan.csv`, `sensitivity/<run_id>/`. This is a one-knob-at-a-time scan, not
the 81-run grid.

**Setup.**
- **Patient:** every run uses Gu patient 120's demographics (Female, 163 cm, 68.9 kg, age assumed
  60, no weight clamp), at rest with no scenario actions, built by the unchanged
  `build_patient_file()` / `build_scenario_file("stable", 0, …)`.
- **Modifiers:** applied as one `CardiovascularMechanicsModification` (`Incremental: true`, the same
  shape production uses) right after the 60 s stabilization, then the run advances 180 s.
- **HR runs:** use `hr_baseline_bpm`. Both 55 and 90 are inside Pulse 4.3.1's accepted range of
  50–110, so neither was clamped. Pulse logged 55 bpm as "bradycardic", which is an informational
  message, not an error.
- **Metrics:** taken from the last 60 s. EF, EDV and ESV are per-beat means from
  `LeftHeart-Volume(mL)`, and SV = CO / HR. A run is flagged "not settled" if any output differs by
  more than 2% between the last 60 s and the 60 s before it.
- **Condition-OFF baseline:** not rerun. It is the existing Arm A-prod run for patient 120, which
  has the same patient and no modifiers but is a 180 s run, so its windows are t=120–180 and
  t=60–120 instead of t=180–240 and t=120–180.

**Result: 0 of 14 runs crashed, and all 15 rows (14 runs plus the reused baseline) are settled**
(largest drift 1.73%). No log line matched `runner.FATAL_LOG_MARKERS`. The only engine warning in
every run was "BMI 25.9 is overweight, no guarantees of model validity".

## Absolute values (last 60 s)

| Run | Condition | Setting | EF % | EDV mL | ESV mL | SV mL | MAP mmHg | CO L/min | HR bpm | Settled (max drift) |
|---|---|---|---|---|---|---|---|---|---|---|
| off_baseline | off | none (reused A-prod 120) | 54.5 | 133.9 | 60.9 | 73.0 | 95.2 | 5.25 | 71.8 | yes (0.16%) |
| on_baseline | **on** | none | 25.2 | 240.7 | 180.0 | 60.7 | 78.4 | 4.29 | 70.7 | yes (0.35%) |
| off_sv_0.6 | off | StrokeVolume 0.6 | 42.8 | 153.4 | 87.7 | 65.7 | 85.5 | 4.56 | 69.4 | yes (1.68%) |
| off_sv_0.8 | off | StrokeVolume 0.8 | 49.8 | 142.4 | 71.4 | 70.9 | 91.7 | 4.95 | 69.7 | yes (1.44%) |
| off_sv_1.2 | off | StrokeVolume 1.2 | 64.9 | 129.2 | 45.4 | 83.8 | 95.5 | 5.52 | 65.9 | yes (0.48%) |
| off_sr_0.7 | off | SystemicResistance 0.7 | 60.7 | 142.6 | 56.1 | 86.6 | 83.0 | 6.13 | 70.8 | yes (1.73%) |
| off_sr_1.3 | off | SystemicResistance 1.3 | 55.3 | 136.3 | 60.9 | 75.4 | 95.8 | 4.55 | 60.4 | yes (1.02%) |
| off_sc_0.7 | off | SystemicCompliance 0.7 | 64.2 | 178.2 | 63.9 | 114.4 | 96.2 | 6.08 | 53.1 | yes (0.61%) |
| off_sc_1.3 | off | SystemicCompliance 1.3 | 54.2 | 116.8 | 53.5 | 63.3 | 81.8 | 4.42 | 69.9 | yes (1.68%) |
| off_vc_0.6 | off | VenousCompliance 0.6 | 59.8 | 155.2 | 62.4 | 92.7 | 95.8 | 5.70 | 61.4 | yes (0.90%) |
| off_vc_1.4 | off | VenousCompliance 1.4 | 54.0 | 124.1 | 57.1 | 67.0 | 89.1 | 4.77 | 71.2 | yes (1.54%) |
| off_hr_55 | off | HR baseline 55 | 59.0 | 145.3 | 59.6 | 85.6 | 95.5 | 4.69 | 54.8 | yes (0.16%) |
| off_hr_90 | off | HR baseline 90 | 50.1 | 125.0 | 62.4 | 62.7 | 94.5 | 5.62 | 89.6 | yes (0.16%) |
| on_sv_1.2 | **on** | StrokeVolume 1.2 | 38.6 | 212.9 | 130.7 | 82.3 | 79.0 | 4.80 | 58.3 | yes (0.78%) |
| on_sv_1.4 | **on** | StrokeVolume 1.4 | 49.6 | 196.1 | 98.9 | 97.2 | 79.2 | 5.10 | 52.4 | yes (0.72%) |

## % change from the reference run

The reference is the condition-OFF baseline for condition-OFF runs and for `on_baseline`, and
`on_baseline` for the two condition-ON StrokeVolume runs.

| Run | vs | EF | EDV | ESV | SV | MAP | CO | HR |
|---|---|---|---|---|---|---|---|---|
| on_baseline | off_baseline | −53.8 | +79.8 | +195.8 | −16.9 | −17.6 | −18.2 | −1.6 |
| off_sv_0.6 | off_baseline | −21.5 | +14.6 | +44.1 | −10.0 | −10.2 | −13.1 | −3.4 |
| off_sv_0.8 | off_baseline | −8.7 | +6.3 | +17.4 | −2.9 | −3.7 | −5.7 | −2.9 |
| off_sv_1.2 | off_baseline | +19.0 | −3.5 | −25.4 | +14.8 | +0.3 | +5.3 | −8.3 |
| off_sr_0.7 | off_baseline | +11.3 | +6.5 | −7.9 | +18.5 | −12.8 | +16.8 | −1.5 |
| off_sr_1.3 | off_baseline | +1.4 | +1.8 | 0.0 | +3.3 | +0.7 | −13.2 | −15.9 |
| off_sc_0.7 | off_baseline | +17.6 | +33.1 | +4.9 | +56.6 | +1.1 | +15.9 | −26.0 |
| off_sc_1.3 | off_baseline | −0.6 | −12.8 | −12.1 | −13.3 | −14.1 | −15.7 | −2.7 |
| off_vc_0.6 | off_baseline | +9.6 | +15.9 | +2.6 | +27.0 | +0.6 | +8.6 | −14.5 |
| off_vc_1.4 | off_baseline | −1.0 | −7.3 | −6.2 | −8.2 | −6.4 | −9.1 | −0.9 |
| off_hr_55 | off_baseline | +8.1 | +8.5 | −2.0 | +17.3 | +0.3 | −10.6 | −23.7 |
| off_hr_90 | off_baseline | −8.1 | −6.6 | +2.5 | −14.2 | −0.8 | +7.1 | +24.8 |
| on_sv_1.2 | on_baseline | +53.2 | −11.6 | −27.4 | +35.5 | +0.7 | +11.8 | −17.5 |
| on_sv_1.4 | on_baseline | +96.5 | −18.6 | −45.1 | +60.1 | +1.1 | +18.7 | −25.8 |

## Observations

1. **What moves EF.**
   - The condition moved EF the most: −53.8%, from 54.5% to 25.2%.
   - StrokeVolumeMultiplier moved EF in the same direction as the knob: 0.6 gave −21.5%, 0.8 gave
     −8.7% and 1.2 gave +19.0%. With the condition on, 1.2 gave +53.2% and 1.4 gave +96.5%
     relative to `on_baseline`.
   - Other settings changing EF by 8% or more: SystemicCompliance 0.7 (+17.6%),
     SystemicResistance 0.7 (+11.3%), VenousCompliance 0.6 (+9.6%) and HR baseline 55/90
     (+8.1% / −8.1%).
2. **What moves MAP.**
   - Settings that lowered MAP by more than 10%: the condition (−17.6%), SystemicCompliance 1.3
     (−14.1%), SystemicResistance 0.7 (−12.8%) and StrokeVolume 0.6 (−10.2%).
   - SystemicResistance 1.3 changed MAP by only +0.7%, while CO fell 13.2% and HR fell 15.9% in the
     same run.
   - No tested setting raised MAP by more than 1.1%.
   - The HR baseline runs changed MAP by less than 1%.
3. **EF between 30 and 45.** Two settings reached it: `off_sv_0.6` (42.8%) and `on_sv_1.2` (38.6%).
   `on_sv_1.4` gave 49.6% and `on_baseline` 25.2%, so the condition-ON runs span 25.2–49.6% across
   StrokeVolume 1.0–1.4.
4. **HR moved without an HR setting.** In several runs HR changed even though no HR setting was
   applied. The largest changes were SystemicCompliance 0.7 (−26.0%), SystemicResistance 1.3
   (−15.9%) and VenousCompliance 0.6 (−14.5%), plus −17.5% and −25.8% for condition-ON
   StrokeVolume 1.2 and 1.4.
5. **HR baseline was reproduced.** Setting HR baseline to 55 and 90 gave twin HR of 54.8 and 89.6.
6. **Crashes.** None of the 14 runs crashed.
