# Demo walkthrough: the five seeded demo patients

What each demo patient (seeded by `scripts/seed_demo_patients.py`) shows on the dashboard, and **why**. Values were read on 2026-10-06 from the demo stack (`docker compose`, merged `main` at `ed44979`, frozen `artifacts/results-v1` models, real Pulse runs).

How each column was obtained:
- **EF / NT-proBNP entered**: the seed script's input. "blank" means omitted, so the API applied the Tier-1 fallback (EF 62%).
- **Scenario / severity**: ML Model 1's prediction on the 21-day window (`GET /patients/{id}/status`).
- **Exercise fired**: whether the generated Pulse `scenario.json` contains an `Exercise` action, and at what intensity.
- **map_start**: recomputed from each run's own Pulse output (`scenarioResults.csv`) with the app's `analyze_simulation()`. Re-scoring those features with `compute_risk_score()` reproduces the stored risk score exactly for all five.
- **Alert**: `status.alert` from `decide_alert()` (level and source).

## Results

| Patient | EF entered | NT-proBNP entered | Scenario | Severity | Exercise fired | map_start (mmHg) | Risk score | Bucket | Alert (source) |
|---|---|---|---|---|---|---|---|---|---|
| DEMO 1 - Stable (EF 58) | 58 | 120 | stable | 0.120 | No | 95.2 | 0.006 | LOW | NONE (risk_scorer) |
| DEMO 2 - EF 30, rising HR -> acute deterioration | 30 | 2500 | acute_deterioration | 0.595 | **Yes**, intensity 0.357 | 79.1 | 0.736 | HIGH | ALERT (risk_scorer) |
| DEMO 3 - EF not measured | blank (62 used) | 2500 | deconditioning | 0.665 | No | 95.4 | 0.055 | LOW | NONE (risk_scorer) |
| DEMO 4 - Fluid-overload trend | 35 | 3200 | fluid_overload | 0.699 | No | 78.5 | 0.508 | MODERATE | WATCH (moderate) |
| DEMO 5 - Cardiac-stress trend | 40 | 1500 | cardiac_stress | 0.401 | **Yes**, intensity 0.401 | 79.1 | 0.770 | HIGH | ALERT (risk_scorer) |

Supporting detail (same runs):

| Patient | HR rise (bpm) | MAP drop (mmHg) | MAP end | instability_flag | acute score | baseline_deficit_score | dominant | NYHA |
|---|---|---|---|---|---|---|---|---|
| DEMO 1 | −1.2 | −0.1 | 95.3 | 0 | 0.006 | 0.000 | acute | I |
| DEMO 2 | +90.3 | 18.7 | 60.4 | 1 | 0.736 | 0.487 | acute | IV |
| DEMO 3 | −10.7 | 4.2 | 91.2 | 0 | 0.055 | 0.000 | acute | II |
| DEMO 4 | −1.9 | −0.1 | 78.6 | 0 | 0.000 | 0.508 | baseline | III |
| DEMO 5 | +63.7 | 23.4 | 55.8 | 1 | 0.770 | 0.487 | acute | IV |

## What drove each result

- **DEMO 1: neither.** A normal EF gives a healthy resting MAP (95 mmHg), and the stable label adds no Exercise, so nothing moves and the risk stays LOW.
- **DEMO 2: an Exercise-triggering label.** The classifier labelled this trend acute_deterioration, which adds Exercise. The exertion raised HR by 90 bpm and pushed MAP below 65, which produced HIGH. On its own, EF 30 would only have produced MODERATE (baseline score 0.487).
- **DEMO 3: neither.** EF wasn't measured, so the healthy 62% default gave Pulse a normal heart (MAP 95). The deconditioning label adds no Exercise, so the risk is LOW despite the highest classifier severity of the five (0.665). This is why the dashboard shows the "EF not measured, healthy default used" warning.
- **DEMO 4: EF ≤ 40.** EF 35 lowered the resting MAP to 78.5 mmHg. That baseline deficit alone (0.508) produced MODERATE; nothing changed during the run, since fluid_overload adds no Exercise.
- **DEMO 5: an Exercise-triggering label.** The cardiac_stress label adds Exercise. The exertion raised HR by 64 bpm and pushed MAP below 65, which produced HIGH. EF 40 alone would have given MODERATE (baseline score 0.487).

## What the hero card shows (fix/alert-both-signals)

The hero card shows two signals side by side:
- **Twin**, from `decide_alert()`, which flags at ALERT or WATCH.
- **ML severity**, the classifier's own signal, which flags at ALERT when severity > 0.15.

When exactly one flags, the card adds the note "ML model flags this patient; the twin's risk score
does not." (or the reverse), and the summary line becomes **"Signals disagree — review this
patient."** instead of the twin-only line.

| Patient | Twin | ML severity | Disagree | Summary line on the hero card |
|---|---|---|---|---|
| DEMO 1 | NONE | NONE (0.12) | no | This patient is stable — no action needed beyond routine monitoring. |
| DEMO 2 | ALERT | ALERT (0.59) | no | Significant deterioration detected — clinical follow-up is recommended today. |
| DEMO 3 | NONE | **ALERT (0.66)** | **yes** | **Signals disagree — review this patient.** (with the note "ML model flags this patient; the twin's risk score does not.") |
| DEMO 4 | WATCH | ALERT (0.70) | no (both flag) | Some signs of strain detected — monitor closely and review symptoms. |
| DEMO 5 | ALERT | ALERT (0.40) | no | Significant deterioration detected — clinical follow-up is recommended today. |

**DEMO 3 is the one to show for the disagreement.** Its EF wasn't measured, so the twin simulates a
normal heart and says NONE, while the classifier's severity (0.66) is well above 0.15. The card shows
both signals, the note, the neutral summary line, and the "EF not measured, healthy default used"
warning.

## The general rule these five show

Which scenario labels add Exercise is fixed in `src/patient_builder/scenario_file.py`:
- **cardiac_stress** adds Exercise at intensity = severity, capped at 0.5 (`:113-119`).
- **acute_deterioration** adds it at 0.6 × severity (`:135-145`).
- **stable**, **fluid_overload** and **deconditioning** never do.

In this demo cohort:
- **HIGH happened only when the classifier picked an Exercise-triggering label.** The exertion drives MAP under the 65 mmHg instability threshold.
- **Without Exercise, the bucket is set by EF alone,** via `map_start` and `baseline_deficit_score`: EF ≤ 40 gives about 0.49–0.51, which is MODERATE; a normal or defaulted EF gives about 0, which is LOW.
- **The wearable trend mostly matters through which label it produces,** not through the size of the change in Pulse.

This matches `docs/gap_report.md` G3/G4 and `docs/unified_alert_evaluation.md` ("WATCH is effectively always on for EF<=40 patients").

## Notes for presenting
- Same inputs can give a different label: noise in the 21-day trend matters. An earlier run with the same EF/BNP and "Mild Decline" preset but different noise was classified deconditioning at 0.587, which came out MODERATE, NYHA III. The seed script uses fixed seeds, so these five results are reproducible.
- DEMO 2 was originally labelled "EF 30, mild decline", after the input preset. It was renamed because what the dashboard shows is an acute-deterioration ALERT, not a mild decline.
- All five patients are synthetic and labelled DEMO. None represents a real person.
