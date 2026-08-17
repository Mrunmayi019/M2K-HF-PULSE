# MIMIC-IV real-outcome test: baseline_deficit_score mechanism only

**Scope**: this tests ONE mechanism in `src/analytics/risk_score.py` -- `baseline_deficit_score = f(map_start)` -- against real in-hospital mortality. It does NOT validate the full risk scorer, the wearable-trend ML classifier, or the Pulse simulation layer; none of those have a non-fabricated input in MIMIC-IV. See `scripts/mimic_outcome_extraction.sql` for the exact cohort query and `docs/methodology.md` for the full writeup.

## Cohort

- n = 17129 admissions (13047 unique patients) -- **exact count, no extrapolation.**
- In-hospital mortality (event) rate: 14.2% (2430 deaths)
- map_start: mean of real MAP readings strictly within the first 24h of admission (mean 77.6 mmHg, sd 11.8, median 23 readings/admission)
- Age: mean 70.2 (sd 13.9); sex: 54.5% male

## Discrimination (AUC)

- AUC = 0.596 (95% CI 0.585-0.608, percentile bootstrap, 2000 resamples, seed=42) for baseline_deficit_score predicting hospital_expire_flag.
- AUC 0.5 = no better than chance; 1.0 = perfect discrimination. This is ONE hand-tuned component's discrimination, evaluated in isolation -- not the full risk_score.py output (which also weighs acute hemodynamic change from a Pulse-simulated encounter that has no equivalent here).

## Calibration (decile bins)

```
   n  mean_score  observed_mortality_rate
3428      0.0569                   0.0893
1711      0.3025                   0.1198
1723      0.4345                   0.1155
1703      0.5423                   0.1339
1712      0.6380                   0.1379
1713      0.7327                   0.1413
1713      0.8289                   0.1675
3426      0.9735                   0.2122
```

## Honest limitations of this specific test

- **Population mismatch**: this cohort is ICU-admitted MIMIC-IV patients (vitalsign, the MAP source, is an ICU-derived table) -- an acutely ill, already-hospitalized population, not this project's target outpatient/home-monitoring use case. A baseline MAP measured during an ICU stay reflects that acute presentation, not a stable ambulatory baseline.
- **map_start's real-world meaning differs from its synthetic/Pulse-simulated use elsewhere in this project**: in the synthetic pipeline, map_start is a Pulse-simulated patient's baseline before a scenario encounter; here it's a real, directly measured first-24h ICU MAP. Same formula, different data-generating process.
- **Admission-level, not patient-level, sampling**: a subject_id can contribute more than one admission (13,047 unique patients across 17,129 admissions here), which mildly violates the independence assumption behind the AUC CI -- not corrected for in this pass.
- **NT-proBNP and discharge_location were deliberately excluded** from this test (see module docstring) -- this is a narrower test than 'everything MIMIC could offer', by design.
- **hospital_expire_flag is in-hospital mortality only** -- no post-discharge (dod-based) or readmission outcome was pursued in this pass (flagged as future work).