# Measurement-consistent set — selection log

Rule: `docs/calibration_pilot/pilot_success_criteria.md`, Amendment 1 (c), committed before this script was run. Script: `scripts/calibration_pilot_select_consistent.py`. Source: AllPatients.mat, first snapshot per patient.

## Patients remaining after each filter

| Step | Filter | Remaining |
|---|---|---|
| 0 | All patients (first snapshot) | 370 |
| 1 | Required fields all present | 361 |
| 2 | CO_td vs CO_fick gap <= 10% of their mean | 129 |
| 3 | |echo EF - MRI EF| <= 7 points | 68 |
| 4 | 16.5 <= BMI <= 29.5 | 38 |
| 5 | 50 <= HR_vitals <= 110 bpm | 36 |
| 6 | All 4 valves known to be no worse than mild | 15 |
| 7 | Not one of 295, 136, 120 | 15 |

For information only, not used: under the looser valve reading (numeric grade ≤ 2.0 regardless of text), 16 patients would pass instead of 15.

## All 15 passing patients (sorted by echo EF)

| Index | Sex | Echo EF | MRI EF | EF gap | CO_td | CO_fick | CO gap | HR | BMI | AVr/MVr/TVr/PVr |
|---|---|---|---|---|---|---|---|---|---|---|
| 139 | Female | 10 | 13.3 | 3.3 | 3.23 | 3.53 | 8.9% | 89.5 | 22.0 | 1/2/1.5/1 |
| 254 | Male | 10 | 10.6 | 0.6 | 4.6 | 4.97 | 7.7% | 90 | 26.0 | 1/1.5/2/1 |
| 331 | Female | 12 | 13.1 | 1.1 | 2.5 | 2.61 | 4.3% | 89.5 | 21.4 | 1/2/2/2 |
| 166 | Female | 12.5 | 13.6 | 1.1 | 3.6 | 3.96 | 9.5% | 91.1667 | 26.0 | 1.5/1.5/1.5/2 |
| 14 | Male | 15 | 14.7 | 0.3 | 3.45 | 3.31 | 4.1% | 94 | 18.9 | 1/2/1.5/2 |
| 315 | Male | 23 | 17.5 | 5.5 | 3.67 | 3.97 | 7.9% | 78.875 | 26.4 | 1/2/1.5/1 |
| 56 | Male | 25 | 23.4 | 1.6 | 4.4 | 4.67 | 6.0% | 58.5 | 26.5 | 1/1.5/1.5/2 |
| 143 | Male | 30 | 31.0 | 1.0 | 4.17 | 4.46 | 6.7% | 81 | 26.4 | 1.5/1.5/1.5/1 |
| 242 | Female | 33 | 31.8 | 1.2 | 4.03 | 4.2 | 4.1% | 97.25 | 28.3 | 1/1.5/1.5/1 |
| 16 | Female | 55 | 52.2 | 2.8 | 5.33 | 5.4 | 1.3% | 91.6364 | 22.9 | 1/2/2/1.5 |
| 364 | Male | 55 | 51.4 | 3.6 | 4.37 | 4.5 | 2.9% | 84.5 | 22.6 | 1/1.5/1.5/1.5 |
| 264 | Male | 56 | 49.4 | 6.6 | 3.87 | 3.9 | 0.8% | 85 | 29.4 | 1/1.5/1.5/1 |
| 88 | Female | 60 | 59.3 | 0.7 | 5.63 | 6.05 | 7.2% | 66.5 | 21.5 | 1/1.5/2/2 |
| 45 | Male | 65 | 65.0 | 0.0 | 5.23 | 5.37 | 2.6% | 75 | 27.2 | 1.5/1.5/2/1.5 |
| 188 | Female | 75 | 69.9 | 5.1 | 4.33 | 4.75 | 9.3% | 88 | 27.5 | 1/2/1/1 |

## Picked

- **Target EF 25 → patient 56**: echo EF 25 is closest to 25 (distance 0).
- **Target EF 40 → patient 242**: echo EF 33 is closest to 40 (distance 7).
- **Target EF 58 → patient 264**: echo EF 56 is closest to 58 (distance 2); tied with 88, won on smaller CO gap (0.8%).
