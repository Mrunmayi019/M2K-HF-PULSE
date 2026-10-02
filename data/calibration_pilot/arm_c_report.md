# Calibration pilot — Arm C (direct-set)

Run 2026-10-02 on `kitware/pulse:4.3.1`, as pre-registered in `pilot_success_criteria.md`,
Amendment 2 (commit `dbf04ca`, made before any Arm C run). Script:
`scripts/calibration_pilot_arm_c.py`. Every tuning run is kept in `arm_c_results.csv`; the `final`
column marks the run used per patient. Raw run files: `arm_c/gu<idx>/run<n>/`.

**Runs.**
- **14 tuning runs over 6 patients. None crashed.** No fatal markers, and every patient could be
  started.
- One run was not settled: patient 136 run 2 (3.73% drift). It was not a final run.
- **Aborted first attempt:** a script bug (a numpy boolean that couldn't be written to JSON)
  stopped the first attempt after its first Pulse run, patient 295 run 1, which itself completed
  with EF 24.61. The status file was not written. The bug was fixed and Arm C was restarted from
  scratch, and the rerun of that run gave the same EF 24.61. The log of the aborted attempt is
  `arm_c_run_stdout_aborted_attempt1.txt`.

**Settings used.**

| Patient | Condition | HR set | BP real → used | Final SV | Runs | Final twin EF (target) |
|---|---|---|---|---|---|---|
| 295 | on | 78.0 | 127.5/67.5 → **120**/67.5 | 1.000 | 1 | 24.61 (25) |
| 136 | on | 54.5 | 101/63 (unchanged) | 1.069 | 4 | **37.85 (40) — target not reached** |
| 120 | off | 91.5 | 130.5/90 → **120/80** | 1.150 | 3 | 57.90 (58) |
| 56 | on | 58.5 | 128.5/79.5 → **120**/79.5 | 0.800 | 2 | 25.38 (25) |
| 242 | on | 97.25 | 115.25/78.875 (unchanged) | 1.187 | 3 | 32.67 (33) |
| 264 | off | 85.0 | 91/63 (unchanged) | 1.029 | 1 | 56.62 (56) |

## 1. Arm A-prod vs Arm C (final runs)

Errors are (twin − real)/real. MAP uses the formula (2·DBP + SBP)/3 on the twin's own pressures.
Real SV = CO_td / HR_vitals. The overall number is the mean absolute % error across EF, HR, MAP,
SV and CO_td.

| Set | Patient | Arm | EF | HR | MAP (formula) | SV | CO vs CO_td | CO vs CO_fick | Overall |
|---|---|---|---|---|---|---|---|---|---|
| original | 295 | A-prod | +1.0% | −9.2% | −15.7% | +42.2% | **+29.1%** | −5.2% | 19.4 |
| | | Arm C | −1.5% | −0.4% | −17.9% | +45.3% | **+44.7%** | +6.3% | 22.0 |
| original | 136 | A-prod | −32.2% | +30.7% | −2.2% | −19.5% | **+5.2%** | +57.8% | 18.0 |
| | | Arm C | −5.4% | −6.6% | −14.8% | +1.6% | **−5.2%** | +42.3% | 6.7 |
| original | 120 | A-prod | −6.0% | −21.5% | −15.7% | +82.1% | **+42.9%** | +59.4% | 33.6 |
| | | Arm C | −0.2% | −7.7% | −10.9% | +77.3% | **+63.7%** | +82.6% | 32.0 |
| consistent | 56 | A-prod | +8.8% | +21.5% | −22.6% | −8.2% | **+11.5%** | +5.1% | 14.5 |
| | | Arm C | +1.5% | −4.1% | −23.2% | −0.8% | **−4.9%** | −10.4% | 6.9 |
| consistent | 242 | A-prod | −23.5% | −27.2% | −18.9% | +49.9% | **+9.2%** | +4.8% | 25.7 |
| | | Arm C | −1.0% | −20.1% | −18.2% | +67.3% | **+33.7%** | +28.3% | 28.1 |
| consistent | 264 | A-prod | +0.1% | −15.4% | +20.3% | +79.1% | **+51.5%** | +50.3% | 33.3 |
| | | Arm C | +1.1% | −1.2% | +0.1% | +48.8% | **+47.0%** | +45.8% | 19.6 |

EF, HR and MAP are inputs to Arm C, so improvement on them is expected and is not evidence by
itself (Amendment 2 e). CO and SV were held out.

## 2. Primary rule (Amendment 2 c)

Arm C counts as closer for a patient if its |CO error vs CO_td| is smaller than Arm A-prod's.

| Set | 295 / 56 | 136 / 242 | 120 / 264 | Arm C closer | Extra crashes | **Rule** |
|---|---|---|---|---|---|---|
| original (295, 136, 120) | 44.7 vs 29.1: no | 5.17 vs 5.21: yes | 63.7 vs 42.9: no | 1 of 3 | none | **not met** |
| consistent (56, 242, 264) | 4.9 vs 11.5: yes | 33.7 vs 9.2: no | 47.0 vs 51.5: yes | 2 of 3 | none | **met** |

Patient 136's "yes" rests on a difference of 0.04 percentage points (5.17% vs 5.21%), in the
opposite direction (−5.2% vs +5.2%). Arm A's stored twin CO is rounded to 3 decimals, which can
move its error by at most 0.011 points, so the ordering is not a rounding artifact.

## 3. Observations

1. **Where Arm C is closer.**
   - On CO: patients 56, 264 and, by 0.04 points, 136.
   - On SV: patients 136 (+1.6% vs −19.5%), 120 (+77.3% vs +82.1%), 56 (−0.8% vs −8.2%) and
     264 (+48.8% vs +79.1%).
   - On the overall number: 136, 120, 56 and 264.
2. **Where Arm C is further.**
   - On CO: patients 295 (+44.7% vs +29.1%), 120 (+63.7% vs +42.9%) and 242 (+33.7% vs +9.2%).
   - On SV: 295 (+45.3% vs +42.2%) and 242 (+67.3% vs +49.9%).
   - On the overall number: 295 (22.0 vs 19.4) and 242 (28.1 vs 25.7).
   - Twin CO is above CO_td for 4 of 6 patients in Arm C (295, 120, 242, 264) and below for 2
     (136, 56).
3. **Did the set HR hold?**

   | | Set | Final run |
   |---|---|---|
   | Within 1.2% | 295: 78.0 | 77.7 |
   | | 264: 85.0 | 84.0 |
   | Within 4–8% | 56: 58.5 | 56.1 |
   | | 136: 54.5 | 50.9 |
   | | 120: 91.5 | 84.5 |
   | 20% below | **242: 97.25** | **77.7** |

   Across 136's four tuning runs, twin HR ran from 46.0 to 56.6 and fell as SV rose. Patient
   242's HR also fell with SV: 82.4, 73.5, 77.7.
4. **Did the set blood pressure hold?**
   - **With the condition off:** systolic/diastolic stayed close. Patient 120 was set to 120/80
     and gave 122.2/77.2; patient 264 was set to 91/63 and gave 91.4/62.9.
   - **With the condition on:** both were well below the set pair.

     | Patient | Set | Twin |
     |---|---|---|
     | 295 | 120/67.5 | 101.8/56.9 |
     | 136 | 101/63 | 88.5/52.5 |
     | 56 | 120/79.5 | 96.6/62.1 |
     | 242 | 115.25/78.9 | 103.2/60.1 |

   - Formula MAP error with the condition on was −14.8% to −23.2%, against −2.2% to −22.6% in
     Arm A-prod for the same patients.
5. **EF target.**
   - **Patient 136 did not reach ±2 points in 4 runs.** Its runs gave 47.53, 29.63 (not settled),
     37.85 and 42.88. The closest, run 3 (37.85, gap −2.15), is the final.
   - The first-guess SV from the knob scan (1.2255) gave EF 47.53 for patient 136, against the
     scan's 38.6 at SV 1.2 on patient 120's body with default HR and BP.
   - The other 5 patients reached ±2 points in 1–3 runs.
6. **Crashes.** None of the 14 runs crashed, and every patient could be started.
