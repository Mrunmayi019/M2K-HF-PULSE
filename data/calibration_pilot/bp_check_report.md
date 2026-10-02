# Calibration pilot — blood-pressure lever check

Run 2026-10-02 on `kitware/pulse:4.3.1`. Script: `scripts/calibration_pilot_bp_check.py`.
Full data: `bp_check.csv`, `bp_check/<run_id>/`.

**Setup.**
- **Patient:** Gu patient 120's body, at rest. The same timing and settle check as the knob scan:
  60 s stabilization, then the modification, then 180 s, with metrics from the last 60 s.
- **Blood-pressure baselines:** added to the patient JSON after the unchanged
  `build_patient_file()`, as `SystolicArterialPressureBaseline` / `DiastolicArterialPressureBaseline`.
- **Result: 11 runs, none crashed, all settled** (largest drift 1.52%). No fatal markers. The only
  engine warning was the usual "BMI 25.9 overweight" message.

## Part 0 — what the Pulse 4.3.1 source says

**a) Patient-file blood-pressure fields** (`Patient.proto`, checked in `SetupPatient.cpp:349-529`):
`SystolicArterialPressureBaseline`, `DiastolicArterialPressureBaseline`,
`MeanArterialPressureBaseline` and `PulsePressureBaseline`.

- **If systolic and diastolic are both given,** the mean and pulse-pressure fields are ignored
  (Pulse logs a warning) and Pulse sets MAP = (SBP + 2·DBP)/3.
- **If only one or two of the fields are given,** Pulse derives the rest. Missing values default to
  114/73.5.
- **Accepted ranges:** systolic 90–120 mmHg and diastolic 60–80 mmHg, and diastolic must be at most
  0.75 × systolic. The lowest accepted pair is therefore 90/60 and the highest 120/80; both have a
  ratio of 0.667. There is no separate range for the mean, because it is derived from the pair.

**b) Outside the range,** Pulse logs an error ("Hypertension/Hypotension must be modeled by
adding/using a condition"), `SetupPatient` fails, and **the engine refuses to start.** Nothing is
clamped.

**c) The condition is applied after the tuning.** The order is:
1. `TuneCircuit()` tunes the circulation to the systolic, diastolic and HR baselines.
2. The engine settles at rest, and `AtSteadyState()` overwrites the baselines with the values it
   actually reached.
3. Only then does it call `ChronicHeartFailure()` (left-heart elastance ×0.27,
   `CardiovascularModel.cpp:841-849`).
4. A second stabilization runs, with no re-tuning.

The logs match this. For example, in `B_on_bp_high` Pulse tuned to 120/80, settled at MAP 101.1,
and after the condition the MAP was 83.5.

**Note on "MAP".** Pulse's `MeanArterialPressure` output is a time average of the arterial pressure
wave. It is not the (2·DBP + SBP)/3 formula used for the real MAP in `pilot_patients.csv`. For the
same run they differ: `A_off_bp_high` has a Pulse MAP of 101.2, but its own systolic/diastolic of
120.3/80.0 give a formula MAP of 93.5. Both are reported below. The formula version is
like-for-like with the real value.

## Runs (last 60 s)

| Run | Condition | Setting | EF % | EDV | ESV | SV mL | MAP (Pulse) | MAP (formula) | SBP/DBP | CO L/min | HR | Settled |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A_off_bp_low | off | BP 90/60 | 57.4 | 116.9 | 49.8 | 67.1 | 76.5 | 70.3 | 90.2/60.4 | 4.81 | 71.6 | yes |
| A_off_bp_high | off | BP 120/80 | 53.4 | 136.7 | 63.7 | 73.0 | 101.2 | 93.5 | 120.3/80.0 | 5.24 | 71.7 | yes |
| B_on_bp_low | on | BP 90/60 | 28.2 | 199.8 | 143.4 | 56.4 | 63.7 | 59.9 | 77.2/51.2 | 3.99 | 70.7 | yes |
| B_on_bp_high | on | BP 120/80 | 24.2 | 250.6 | 190.0 | 60.6 | 83.6 | 78.5 | 102.1/66.8 | 4.33 | 71.4 | yes |
| C_off_ar_1.3 | off | ArterialResistance 1.3 | 53.8 | 135.4 | 62.6 | 72.8 | 95.2 | 87.6 | 114.5/74.2 | 5.25 | 72.1 | yes |
| C_off_vr_1.3 | off | VenousResistance 1.3 | 51.9 | 125.2 | 60.2 | 65.0 | 94.9 | 87.9 | 112.4/75.7 | 4.97 | 76.4 | yes |
| C_off_hrm_1.2 | off | HeartRateMultiplier 1.2 | 51.5 | 126.4 | 61.3 | 65.1 | 95.3 | 88.3 | 112.9/76.0 | 5.35 | 82.2 | yes |
| D_on_sr_1.3 | on | SystemicResistance 1.3 | 26.3 | 241.9 | 178.2 | 63.7 | 78.9 | 73.5 | 98.1/61.2 | 3.78 | 59.4 | yes |
| D_on_ar_1.3 | on | ArterialResistance 1.3 | 23.6 | 247.2 | 188.9 | 58.3 | 78.3 | 73.8 | 96.3/62.5 | 4.23 | 72.6 | yes |
| E_off | off | HR 90 + BP 120/80 + SV 0.8 | 44.5 | 137.7 | 76.3 | 61.3 | 96.5 | 89.4 | 116.3/76.0 | 5.33 | 86.9 | yes |
| E_on | on | HR 90 + BP 120/80 + SV 1.2 | 34.3 | 214.3 | 140.8 | 73.5 | 82.8 | 75.8 | 106.8/60.3 | 5.21 | 70.8 | yes |

For reference, the knob scan's baselines on the same body were: condition off, MAP 95.2 (formula
87.3), HR 71.8; condition on, MAP 78.4 (formula 73.4), HR 70.7.

## Answers

**1. What MAP range can the twin reach?** These are the extremes seen across all 34 twin runs so
far (Arm A, the scan and this check). They are observed values, not proven limits.

| | MAP (Pulse) | MAP (formula) | Lowest from | Highest from |
|---|---|---|---|---|
| Condition OFF | 76.5 – 101.2 | 70.3 – 93.5 | BP baseline 90/60 | BP baseline 120/80 |
| Condition ON | 63.7 – 83.6 | 59.9 – 78.5 | BP baseline 90/60 + condition | BP baseline 120/80 + condition |

**2. Which lever does it?** The blood-pressure baseline in the patient file, and that is the only
lever. Each knob moved Pulse MAP by less than 1% relative to its baseline:

| Knob | Condition | Pulse MAP change |
|---|---|---|
| ArterialResistance 1.3 | off | −0.02% |
| VenousResistance 1.3 | off | −0.3% |
| HeartRateMultiplier 1.2 | off | +0.2% |
| SystemicResistance 1.3 | on | +0.7% |
| ArterialResistance 1.3 | on | −0.1% |

Together with the scan, no tested knob raised MAP by more than 1.1%.

Other findings from these runs:
- The condition lowered MAP by 16–17% from wherever the baseline put it: 101.1 → 83.6 at 120/80,
  and 76.4 → 63.7 at 90/60.
- The baseline also shifted EF slightly: 57.4 vs 53.4 with the condition off, and 28.2 vs 24.2
  with it on (low vs high pair).
- HeartRateMultiplier 1.2 raised HR from 72 to 82.2, which is +14.5%, not +20%.
- SystemicResistance 1.3 with the condition on lowered HR to 59.4.

**3. In the E runs, did HR and MAP stay near what was set once the pump knob was applied?** The
"before knob" values are from the engine log at the end of stabilization. The "last 60 s" values
are with the knob applied.

| Run | Value | Set | Before knob | Last 60 s |
|---|---|---|---|---|
| E_off (SV 0.8) | HR | 90 | 90.0 | 86.9 (−3.5% vs set) |
| | MAP (Pulse) | — | 100.7 | 96.5 (−4.2%) |
| | MAP (formula) | 93.3 | — | 89.4 (−4.2% vs set) |
| | SBP/DBP | 120/80 | — | 116.3/76.0 |
| E_on (SV 1.2) | HR | 90 | 90.1 | **70.8 (−21.4% vs set)** |
| | MAP (Pulse) | — | 82.0 | 82.8 (+0.9% vs before knob; the condition had already lowered it from 100.7) |
| | MAP (formula) | 93.3 | — | **75.8 (−18.8% vs set)** |
| | SBP/DBP | 120/80 | — | 106.8/60.3 |

With the condition off, HR and MAP stayed within about 4% of the set values. With the condition
on, they did not: HR fell from 90 to 70.8 once SV 1.2 was applied, and MAP was already about 18%
below the set pair before the knob.

**4. Are the six pilot patients' real values inside what the twin reached?**

Rules for the table:
- **Condition each patient's EF needs.** Twin EF was 42.8–64.9 with the condition off and
  23.6–49.6 with it on. So EF 25–40 needs the condition on, and EF 56–58 needs it off.
- **MAP and HR** are checked against the range seen with that condition.
- **HR with the condition off:** the HR baseline was reproduced (55 → 54.8, 90 → 89.6, and 90 →
  86.9 with SV 0.8), so Pulse's settable range of 50–110 is used.
- **HR with the condition on:** the only test of a set HR (E_on) did not hold, so the observed
  range of 52.4–72.6 is used.
- **Limits of this table:** each variable is judged on its own. No single run reached a patient's
  EF, HR and MAP together. All ranges come from patient 120's body, plus the Arm A runs at default
  settings for the other bodies.

| Set | Patient | Condition needed | Real EF (echo) | EF inside? | Real HR | HR inside? | Real MAP (formula) | MAP inside, formula (ON 59.9–78.5 / OFF 70.3–93.5) | MAP inside, Pulse mean (ON 63.7–83.6 / OFF 76.5–101.2) |
|---|---|---|---|---|---|---|---|---|---|
| original | 295 | on | 25 | yes | 78.0 | **no** | 87.5 | **no** | **no** |
| original | 136 | on | 40 | yes | 54.5 | yes | 75.7 | yes | yes |
| original | 120 | off | 58 | yes | 91.5 | yes | 103.5 | **no** | **no** |
| consistent | 56 | on | 25 | yes | 58.5 | yes | 95.8 | **no** | **no** |
| consistent | 242 | on | 33 | yes | 97.25 | **no** | 91.0 | **no** | **no** |
| consistent | 264 | off | 56 | yes | 85.0 | yes | 72.3 | yes | **no** |

On MRI EF instead of echo EF, the result changes for 295 (MRI 20.7, below the 23.6 minimum: no) and
56 (MRI 23.4, also below: no). For 136 (30.5), 120 (28.4), 242 (31.8) and 264 (49.4), MRI EF is
inside the range.
