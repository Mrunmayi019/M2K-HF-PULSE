# Demo walkthrough: the five seeded demo patients

What each demo patient (seeded by `scripts/seed_demo_patients.py`) shows on the dashboard, and **why**. Values were first read on 2026-10-06 from the demo stack (`docker compose`, merged `main` at `ed44979`, frozen `artifacts/results-v1` models, real Pulse runs). They were re-checked for v1.2 on 2026-10-08 (`main` at `4e3f0ee`, all feature flags off): all five patients reproduced the same scenario, severity, risk score, bucket, NYHA class and alert.

## Presenting each patient

**Present in fresh mode** (`PIPELINE_MODE=fresh`, the default, with every feature flag off). All values in this document's main tables come from that mode. Continuous mode gives different numbers for the same patients (see [Demoing continuous mode](#demoing-continuous-mode-and-the-reset-button)), so use it only for the short DEMO 1 reset demo described there.

Start the stack (`docker compose up -d`), seed once (`python scripts/seed_demo_patients.py`, about 5–10 minutes per patient), and open http://localhost:3000. Every step below is on the **Patient Dashboard** tab: click the patient's name in the **PATIENTS** list in the left sidebar, then read the page from top to bottom.

| Patient | What to click and point at | What appears (all flags off) | What it shows about the system, honestly |
|---|---|---|---|
| DEMO 1 - Stable (EF 58) | The hero card, then the **Forward Projection** cards. | Green **LOW RISK**, NYHA I, Twin: NONE, ML severity: NONE, "This patient is stable — no action needed beyond routine monitoring." Projections stay LOW at +7/+14/+30 days. | A normal heart with a flat trend stays quiet. That is the baseline, and it is not evidence that the system catches anything. |
| DEMO 2 - EF 30, rising HR -> acute deterioration | Hero card (red), then **Cardiac Waveform** (PV loop), then **Clinical Summary Report**. | Red **HIGH RISK**, NYHA IV, Twin: ALERT, ML severity: ALERT, "Significant deterioration detected — clinical follow-up is recommended today." | HIGH comes from the classifier choosing an Exercise-triggering label; the simulated exertion pushes MAP below 65. EF 30 alone would only give MODERATE, so the alert depends on the label more than on the size of the trend. |
| DEMO 3 - EF not measured | Hero card: both signal chips and the "Signals disagree" line, then the EF warning in **Current Condition**. | **LOW RISK**, Twin: NONE, ML severity: ALERT (0.66), "Signals disagree — review this patient.", plus the "EF not measured, healthy default used" warning. | Without a measured EF the twin simulates a healthy heart and sees nothing. The dashboard surfaces the disagreement instead of hiding it, but it cannot resolve which signal is right. |
| DEMO 4 - Fluid-overload trend | Hero card (amber), then the **Vitals** table (weight trend). | Amber **MODERATE**, NYHA III, Twin: WATCH, ML severity: ALERT, "Some signs of strain detected — monitor closely and review symptoms." | The weight gain sets the fluid_overload label, but MODERATE comes from EF 35 alone. The run itself changes nothing, so WATCH is effectively always on for EF ≤ 40. |
| DEMO 5 - Cardiac-stress trend | Hero card (red), then scroll to **Forward Projection**. | Red **HIGH RISK**, NYHA IV, Twin: ALERT, ML severity: ALERT. In the 2026-10-08 run all three projection horizons (+7/+14/+30 d) came back **failed**, so the cards have no risk bucket. | A modest cardiac_stress trend is enough for HIGH through the Exercise action. The projections fail because Pulse itself crashes at the higher severities they project (see below), and the dashboard shows them as failed rather than inventing a value. |

If a projection or assessment shows **failed**, say so. It is the designed, visible outcome of a Pulse run that did not complete, not a frozen screen.

**Why DEMO 5's projections fail.** Each projection horizon runs a separate Pulse simulation at the projected (higher) severity with the patient's label. For cardiac_stress that includes the Exercise action. For DEMO 5 (EF 40), Pulse completes these runs up to severity 0.402 and crashes from about 0.41: at 0.409, 0.418 and 0.438 the engine reports a negative right-heart volume and enters an irreversible state about 95 s into the Exercise. DEMO 5's current severity (0.401) sits just below that point. The three projections run at 0.409 (+7 d), 0.418 (+14 d) and 0.438 (+30 d) (fresh-clone check, 2026-10-09), so all three fail. This is a limit of the physiology engine for this configuration, not a dashboard bug. Details: `docs/research_flags_evaluation.md` §7.3.

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

## Demoing continuous mode and the reset button

Continuous mode carries each patient's Pulse state forward from one day to the next, instead of rebuilding the twin on every run. It is experimental and off by default.

**Show it only with DEMO 1 and the reset button.** DEMO 1 is the only demo patient whose continuous-mode results match fresh mode and stay flat. For the other four, the first continuous day differs from fresh mode and risk drifts upward on later days (table and limits below), so their continuous numbers should not be presented. To demo it:

1. Start the backend with `PIPELINE_MODE=continuous` (every other flag off), for example by adding `PIPELINE_MODE: continuous` under `pulse-backend.environment` in a compose override file. Use a fresh database volume so the seed script doesn't skip patients that already exist, and so the fresh-mode demo database is left untouched.
2. Seed the patients, then send one more daily wearable reading **for DEMO 1** (`POST /patients/{id}/wearable-sync`, dated after the newest one). Each new day starts one ~600 s Pulse encounter that resumes from the saved state, about 4–8 minutes per day.
3. On the Patient Dashboard a **Twin State** panel appears (it is hidden when every flag is off). It shows the pipeline mode, when the current state started, days in this state, `engine_lag_days` and days since the last Exercise-triggering label.
4. Click **Reset twin state**, then **Confirm reset**. The panel shows "Reset: fresh start on next run" and days in this state drops to 0. The next reading starts a new state, while all history, runs and assessments are kept.

What the 2026-10-08/09 check showed for all five (kept here as the reason to demo DEMO 1 only): day 21 is the initial run, days 22–24 are resumed runs, and the 3 extra days held the day-21 trend values.

| Patient | Day 21 (initial) | Day 22 | Day 23 | Day 24 |
|---|---|---|---|---|
| DEMO 1 | LOW / NONE | LOW / NONE | LOW / NONE | LOW / NONE |
| DEMO 2 | MODERATE 0.49 / WATCH | HIGH 0.71 / ALERT | HIGH 1.00 / ALERT (label now deconditioning) | HIGH 1.00 / ALERT (deconditioning) |
| DEMO 3 | LOW 0.02, signals disagree | LOW 0.05 | LOW 0.14 | **MODERATE 0.64 / WATCH, NYHA IV** |
| DEMO 4 | MODERATE 0.51 / WATCH | MODERATE 0.64 | HIGH 0.69 / ALERT | HIGH 0.94 / ALERT |
| DEMO 5 | MODERATE 0.49 / WATCH | MODERATE 0.56 / WATCH | HIGH 1.00 / ALERT | HIGH 1.00 / ALERT |

All 20 runs completed, and `engine_lag_days` stayed 0. After **Reset twin state** on DEMO 1, the next day started a new state: `state_days` went 4 → 0 → 1, a new `state_started_at`, and simulated time went back from 2,460 s to 660 s.

Be honest about these limits when you present it:
- **The first continuous day differs from fresh mode.** The initial run (`run_initial`) applies only the base cardiovascular modification, with no scenario extras and no Exercise. So DEMO 2 starts at 0.487 instead of fresh mode's 0.736, and DEMO 5 at 0.487 instead of 0.770, both MODERATE / WATCH. They only reach HIGH once Exercise is applied on a resumed day.
- **Exercise persists.** Once applied, it stays in the saved state. DEMO 2 stays at risk 1.00 on days 23–24 even though the label changed to deconditioning, which never adds Exercise.
- **Risk drifts upward without any new label.** DEMO 3 (deconditioning, defaulted EF) went from LOW to MODERATE / NYHA IV, and DEMO 4 (fluid_overload) from 0.51 to 0.94, over three days with the same label and no Exercise; DEMO 1 (EF 58) and a 14-day flat test patient did not drift. Where inside resume the drift comes from has not been pinned down (`docs/research_flags_evaluation.md` §7.2). Day-2+ deltas measure a different quantity than the from-scratch calibration (`src/api/continuous_state_pipeline.py` docstring), and `docs/gap_report.md` G1 flags compounding drift. Do not present continuous-mode risk as clinically calibrated.
- There is no automatic reset rule: only the button resets the state.

## Running the demo on Windows

- **Docker storage on D:.** Docker Desktop's disk image is at `D:\dockerData\DockerDesktopWSL\disk\docker_data.vhdx` (about 21 GB with these images). Keep it off C: if C: is nearly full (Docker Desktop → Settings → Resources → Advanced → Disk image location).
- **Temp and cache folders.** Point TEMP/TMP, `PIP_CACHE_DIR` and the npm cache (`npm config set cache D:\npm-cache`) at D:. Docker Desktop also downloads its own updates into `%LOCALAPPDATA%\Temp\DockerDesktopUpdates` on C: (about 600 MB); turn off automatic update checks if C: space matters.
- **Avast.** Avast Web Shield's HTTPS scanning intercepts TLS, and `docker compose build` then fails in pip with `CERTIFICATE_VERIFY_FAILED` or corrupt downloads. Turn off "Enable HTTPS scanning" before building and turn it back on afterwards.
- **Memory.** Docker had 8 GB; one Pulse run used about 0.3 GB of container memory at 100% of one CPU. Run the seed patients one at a time (the seed script already does), and keep the laptop plugged in and awake: if it sleeps, Pulse pauses and the wait can time out. Windows may grow the pagefile on C: during long runs.
