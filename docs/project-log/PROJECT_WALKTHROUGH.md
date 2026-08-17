# Project Walkthrough — M2K HF-PULSE / HeartGuard AI

Personal-understanding document, not paper material — prioritizes clarity over formality.
Everything below is grounded in the current state of the repo as of 2026-08-17 (post
documentation-audit); every non-obvious claim cites the file/section it comes from so you can go
verify it directly rather than trust this summary.

---

## 1. What we're doing

**The problem**: heart failure (HF) patients decline gradually, not suddenly, but the way they're
currently monitored is episodic — a clinic visit every 4-6 weeks — so a patient can slide from
stable to crisis with nobody watching in between. Consumer wearables measure numbers (heart rate,
SpO2) but have no model of what those numbers *mean* for a specific patient's cardiovascular
state, and no existing home-monitoring system projects a patient's trajectory forward — threshold
alerts only fire after a value has already gone abnormal (`docs/methodology.md` §1).

**What this project builds**: a patient-specific "digital twin" — a real physiology simulation
(the Kitware Pulse engine), personalized to one patient's clinical baseline (ejection fraction,
NT-proBNP, demographics) and driven forward by their own rolling wearable-trend data. The system
answers a question a wearable alone can't: *given this patient's trajectory so far, what is their
body likely to do next, and how urgent is it?*

**Who it's for**: HF patients being monitored at home (or their care team), as an early-warning
layer between clinic visits — the target use case is outpatient/home monitoring, explicitly not
inpatient/ICU care (this distinction matters later, in §5's MIMIC-IV discussion).

**What the system actually produces, end to end, for one patient**: a patient submits their
demographics + a clinical report (EF, NT-proBNP) once, then daily wearable readings. After 21 days
of wearable data accumulate, the system automatically classifies what's happening to them (one of
5 physiological scenarios — see §2), simulates their cardiovascular response to that scenario in
Pulse, computes an interpretable 0-1 risk score with a clinical explanation, stages them by NYHA
functional class, and projects their risk forward 7/14/30 days. All of this surfaces in a React
dashboard as a hero risk-status card, current condition detail, vitals, a forward-projection
chart, and a copy/downloadable clinical summary report a patient could hand to a doctor.

---

## 2. How we're doing it — system overview

```
Patient demographics + clinical report (EF, NT-proBNP)
Daily wearable readings (HR, SpO2, weight, steps, sleep, HRV) x21 days
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. ML Model 1 — Scenario Classifier + Severity Regressor         │
│    in:  clinical snapshot + 21-day wearable-trend aggregates     │
│    out: scenario_type (1 of 5) + severity (0-1, continuous)      │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. Patient/Scenario Construction (patient_builder/)              │
│    in:  demographics + EF + scenario_type + severity             │
│    out: Pulse patient.json + scenario.json (Actions/Conditions)  │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. Pulse Physiology Simulation (pulse_runner/)                   │
│    in:  patient.json + scenario.json, run inside Docker          │
│    out: HR/MAP/CO/stroke-volume time series CSV + crash detect   │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. Feature Extraction (analytics/simulation_features.py)         │
│    in:  raw Pulse output CSV                                     │
│    out: hr_rise, map_drop, co_drop_pct, compensation/instability │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. Risk Scoring + Clinical Logic (analytics/)                    │
│    in:  the 5 extracted features + map_start                     │
│    out: risk_score (0-1) + risk_bucket, NYHA class,               │
│         deterioration rate, 7/14/30-day forward projection        │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. FastAPI Backend (api/) — SQLite/Postgres                      │
│    Orchestrates 1-5 as one background job once 21 days fill;     │
│    persists everything; every GET is a fast DB read, never       │
│    blocks on Pulse                                                │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 7. React Frontend (frontend/)                                    │
│    Hero risk card, current condition, vitals, projection chart,  │
│    copy/download clinical report, trends, simulation lab, etc.   │
└─────────────────────────────────────────────────────────────────┘
```

**Stage 1 — Scenario classification.** Input is a patient's clinical snapshot (age, sex, BMI, EF,
NT-proBNP) plus 21 days of wearable trend aggregates (first/last-7-day mean, delta, slope per
vital). Two RandomForest models — sharing one feature matrix — predict which of 5 physiological
scenarios (`stable`, `fluid_overload`, `cardiac_stress`, `deconditioning`, `acute_deterioration`)
the patient's trend looks like, and how severe (0-1 continuous). Output: `scenario_type` +
`severity`.

**Stage 2 — Patient/scenario construction.** Takes the classified scenario + severity + the
patient's real EF and constructs the actual input files Pulse needs: a `patient.json` (body,
demographics) and a `scenario.json` (a sequence of Pulse Actions/Conditions that drive the
simulated body's physiology to match the scenario). This is where a lot of real Pulse-specific
engineering lives — Pulse has no direct "set this patient's EF" input; disease state has to be
expressed through specific engine mechanisms (§3 below).

**Stage 3 — Pulse simulation.** Runs the actual Kitware Pulse physiology engine (a real,
research-grade cardiovascular/respiratory/renal simulator, not a toy model) inside Docker on the
constructed scenario, producing a real time-series of heart rate, blood pressure, cardiac output,
etc. Includes crash/timeout detection, since this step can and does fail for some inputs (§5).

**Stage 4 — Feature extraction.** Reduces the raw Pulse time series to 5 clinically-meaningful
deltas: how much heart rate rose, how much mean arterial pressure dropped, how much cardiac output
declined (%), whether the heart's stroke volume held up under stress (compensation), and whether
blood pressure crossed a critical-care instability threshold.

**Stage 5 — Risk scoring and clinical logic.** Those 5 features (plus a 6th, `map_start`, the
patient's baseline MAP) feed a hand-tuned, clinically-cited weighted risk score, a rule-based NYHA
staging classifier, a wearable-trend deterioration-rate calculator, and a forward-projection
module that re-runs stages 2-4 at projected future severities.

**Stage 6 — API/persistence.** A FastAPI backend stores everything across 5 database tables and
runs stages 1-5 as one background job once a patient's 21-day wearable window fills. Every
read-facing endpoint is a fast database read — nothing in the request path ever waits on Pulse.

**Stage 7 — Frontend.** A React dashboard reads from that API to show the patient's risk status,
current condition, vitals, forward projection, and a clinical summary report, plus trend charts,
a patient-creation wizard, and a reports view.

---

## 3. How each stage was actually built

### Phase 0/1 — Scaffold + synthetic data foundation

Built the repo scaffold and a correlated synthetic patient generator
(`src/data_synthesis/generate_patients.py`) + wearable-trend simulator
(`generate_wearable_trends.py`), grounded in real reference statistics (MIMIC-IV, Kaggle Chicco &
Jurman 2020, CDC NHANES — `docs/data_provenance.md`), not guessed numbers. Generates n=2000
synthetic patients with clinically-correlated EF/BNP/severity/NYHA and 3 wearable-trend modes
(`stable`, `deteriorating`, `recovering`).

**Locked decision — dataset strategy**: real/raw patient data is never committed to git; only
derived synthetic data and aggregate statistics ship in the repo (`docs/data_provenance.md`,
top of file). This is applied consistently everywhere real data touches this project, including
the later MIMIC-IV and PerHeart work (§5, §6).

**Locked decision — personalization tiers**: Tier 1 (demographics + EF + BNP + wearables) is
core; Tier 2 (echo/PPG-derived vascular compliance) is optional/stretch and was never built — no
echo/PPG dataset was ever acquired, and Tier 1 alone already hit the project's own accuracy
targets (92.3% scenario accuracy); Tier 3 (ECG-derived blood pressure/contractility) is
**permanently cut**, not deferred — the underlying ECG-to-hemodynamics formulas were never
validated against a real dataset and would introduce "unfounded precision" (`docs/methodology.md`
§3, §9).

**Locked decision — 5-scenario taxonomy**: `stable`, `fluid_overload`, `cardiac_stress`,
`deconditioning`, `acute_deterioration` — defined in `src/data_synthesis/reference_stats.yaml`'s
`scenario_types` list and used consistently through the classifier, Pulse scenario construction,
and risk scoring.

### Phase 2 — Real Pulse engine integration (`src/patient_builder/`, `src/pulse_runner/`)

Built alongside (not replacing) the original prototype (`src/generator.py`/`src/run.py`, left
untouched). Real findings from reading Pulse 4.3.1's actual compiled source, not the planning
docs:

- Pulse has **no direct EF/contractility input** — EF is purely a simulation *output*. Structural
  reduced systolic function is applied via a binary `ChronicVentricularSystolicDysfunction`
  condition (a fixed elastance cut), and continuous severity via the
  `CardiovascularMechanicsModification` action's multipliers (`ef_to_cardiovascular_modifiers()`,
  `src/patient_builder/patient_file.py`).
- Pulse **hard-rejects patients outside age 18-65 or BMI 16.0-30.0** — hardcoded engine constants.
  Since this project's real-data-grounded population frequently falls outside that (MIMIC mean age
  68.7), patients outside range are simulated via a capped-demographic proxy body — their real
  EF/BNP/severity still drive the simulation, only the simulated body's age/weight is a proxy.
- **A real bug found and fixed during this phase**: stacking the binary condition's fixed EF cut
  with a second EF-derived continuous multiplier pushed a test patient (EF=26.6) into genuine
  cardiovascular collapse (`"Can't transport with a negative volume"`, `IrreversibleState`) — the
  same failure signature later characterized in much more depth in §5 below. Caught correctly by
  the crash-detection code being built in this same phase. **Fixed** by having the continuous
  multiplier represent only the *additional acute* severity on top of the condition, not a second
  full cut.

### Phase 3 — ML scenario classifier (`src/scenario_classifier/`)

See §4 below for full model detail.

### Phase 4 — Batch Pulse simulation dataset (`src/pulse_runner/batch_runner.py`,
`src/analytics/simulation_features.py`)

Ran 150 synthetic patients (30 per scenario type, stratified from the existing synthetic
population) through Pulse in parallel — 117 succeeded, 33 failed, almost entirely high-severity
`cardiac_stress`/`acute_deterioration` runs (the two scenarios with an `Exercise` action)
destabilizing the engine. This dataset (`data/simulation_runs/features_dataset.csv`) is what
Phase 5's risk scorer and secondary model are built/validated on.

### Phase 5 — Risk scoring & clinical logic (`src/analytics/`, `src/ml_models/`)

See §4 below for the two risk-scoring models. Also built in this phase, all in `src/analytics/`:

- **`staging.py`** — rule-based NYHA classifier. AHA/ACC 2022 Stage B structural/biomarker
  criteria gate whether a patient has any structural HF basis; the simulated exertion response
  then places a structurally-at-risk patient in NYHA I-IV.
- **`deterioration_rate.py`** — per-vital slopes over the 21-day wearable window, normalized to
  population-SD-equivalents/day, converted to a risk-score-equivalent daily rate via one named,
  flagged `assumed_default` constant (no clinical literature exists for this specific conversion).
- **`projection.py`** — linearly extrapolates severity forward, then re-runs the *entire*
  pipeline (patient_builder → Pulse → feature extraction → risk score) at each projected severity
  for 7/14/30-day horizons. This means a projection isn't just "the current score times a slope" —
  it's a fresh, real Pulse simulation of the patient's projected future state.

### Phase 6 — FastAPI backend (`src/api/`)

5 SQLAlchemy tables (`patients`, `clinical_reports`, `wearable_readings`, `simulation_runs`,
`risk_assessments`). Key design choices:

- **Wearable data accumulates, doesn't immediately trigger.** `POST /wearable-sync` stores one
  day's reading; the assessment pipeline only fires once 21 readings have accumulated (matches the
  fixed-window design the ML model needs).
- **Everything Pulse-related lives in one background job.** `BackgroundTasks` runs the whole
  chain (Model 1 → Pulse → feature extraction → risk score → staging → deterioration rate →
  projection) once, off the request path — every `GET` endpoint is a fast DB read, never blocking
  on Pulse (which can take minutes).
- **Tier 1 fallback**: a clinical report with missing EF defaults to the healthy-population mean
  (62%); missing NT-proBNP defaults to 100 pg/mL. Both are recorded via `ef_is_fallback`/
  `bnp_is_fallback` flags on the stored report — this fallback mechanism is directly responsible
  for one of the real-world limitations in §5 below.
- **A real cross-version bug found and fixed**: the Pulse Docker container ships Python 3.9, but
  `models.py`/`schemas.py` were first written with PEP 604 union syntax (`str | None`), which
  SQLAlchemy/Pydantic's runtime `eval()` can't resolve on 3.9. Fixed by using `typing.Optional[X]`
  in those two files specifically.

### Phase 7 — Frontend dashboard (`frontend/`) + extension

A React (Vite) single-page dashboard built against a decoded design reference. Comparing the
design against the actual API surfaced several fields the pipeline computed but never returned
(`scenario_type`, `severity`, EF, BNP, per-vital trend slopes) — added as small, additive API
extensions rather than fabricated client-side. The Phase 7 extension wired up the sidebar's other
4 sections (Trends & History, Simulation Lab, Reports, Settings), which had been static labels
with no click handler, plus a working dark/light/system theme toggle. Full verification evidence
in `docs/frontend_extension_validation.md`.

### Phase 8 — Full-pipeline batch validation (`scripts/validate_phase8.py`)

Not a build phase — a validation pass that ran 25 synthetic patients through the **live API**
(not a direct function call) for the first time, catching the severity-regressor bug detailed in
§5 below.

### Phase 9 — Docker/CI infrastructure

`backend/Dockerfile` (FastAPI + Pulse engine, `linux/amd64` — the Pulse binary has no arm64
build), `frontend/Dockerfile` (Vite build → nginx), `docker-compose.yml` (Postgres + backend +
frontend, one command), `.github/workflows/ci.yml` (pytest + frontend build on every push).

### Real-world data validation (post-roadmap, iterated 3 times)

Not a numbered phase — a validation extension that replays a real, published, ethics-approved
dataset (PerHeart, 27 real HF patients) through the live pipeline in place of synthetic data. Full
detail in §5-§6 below and `docs/real_world_data_integration.md`.

---

## 4. What the models actually do and how they work

### Model 1a — Scenario Classifier

**Plain-language**: given a patient's clinical info and how their wearable readings have been
trending over 3 weeks, predict which of 5 physiological "stories" best matches what's happening to
them (e.g. "this looks like fluid building up" vs. "this looks like general deconditioning").

**Technical**: `RandomForestClassifier` (`n_estimators=300`, default depth), 5-class
(`stable`/`fluid_overload`/`cardiac_stress`/`deconditioning`/`acute_deterioration`). **Features**
(29 columns): clinical snapshot (age, sex, BMI, ejection fraction, NT-proBNP) + per-vital wearable
trend aggregates (first-7-day mean, last-7-day mean, delta, linear slope) for 6 vitals over the
21-day window. **Training data**: `data/synthetic/patients.csv` + `wearable_trends.csv`, n=2000,
patient-level stratified 70/15/15 split. **Performance (held-out test, n=300)**: 90.7% accuracy
(macro F1 0.91), one-vs-rest ROC macro-AUC 0.990 [bootstrap 95% CI reported in
`models/phase3_extended_eval_report.txt`]. File: `models/scenario_classifier.joblib`
(gitignored, regenerate with `python -m src.scenario_classifier.train`).

### Model 1b — Severity Regressor

**Plain-language**: alongside the scenario label, also predicts *how severe* the situation is, as
a continuous 0-1 number.

**Technical**: `RandomForestRegressor`, same features/training data/split as Model 1a (shares one
feature matrix). **Performance**: severity MAE 0.047 / RMSE 0.061 offline (bootstrap 95% CI
[0.043, 0.052]). **Live-pipeline performance** (the number that actually matters for deployment)
is covered in §5 — this model had a real, diagnosed bug affecting only its live behavior, since
fixed; current live MAE (n=27 revalidation, 2026-08-17) is **0.0247** [95% CI 0.0171, 0.0336],
scenario accuracy 1.0000 [1.0, 1.0].

### Model 2a — Primary Risk Scorer (`src/analytics/risk_score.py`)

**Plain-language**: takes the 5 hemodynamic changes measured during one Pulse simulation
(how much heart rate rose, blood pressure dropped, cardiac output declined, etc.) and combines
them into one 0-1 risk number with a clinical explanation — "the score is HIGH because MAP
dropped below the shock threshold" is a sentence a doctor can act on.

**Technical**: **not a trained model at all** — a hand-tuned, interpretable weighted linear
combination. Each of 5 inputs is normalized to 0-1 against a clinically-cited anchor and combined
with hand-set weights summing to 1:

| Component | Weight | Clinical anchor |
|---|---|---|
| `instability_flag` | 0.30 (highest) | MAP<65mmHg — Surviving Sepsis Campaign / Vincent & De Backer, NEJM 2013 |
| `map_drop` | 0.20 | same MAP<65 anchor, full scale from ~92.5mmHg healthy baseline |
| `co_drop_pct` | 0.20 | 30% CO decline = full scale — Nohria et al. JAMA 2002; SCAI 2019 |
| `hr_rise` | 0.15 | NEWS2 heart-rate scoring bands (RCP, 2017) |
| `compensation_flag` | 0.15 | Frank-Starling failure, textbook systolic-dysfunction hallmark |

This is the **locked primary model** — chosen over the trained alternative (Model 2b below)
because it needs no training data (so the small 117-row dataset can't hurt its reliability) and
every component of its output is directly explainable, unlike a black-box prediction
(`src/analytics/risk_score.py`'s module docstring, `docs/methodology.md` §6). A 6th input,
`map_start` (the patient's baseline blood pressure), was added later to fix a real blind spot —
see §5. **Performance**: within-scenario correlation with true severity — `acute_deterioration`
0.70/0.69 (offline/post-fix-reeval), `cardiac_stress` 0.30, `deconditioning` 0.21-0.35 — all
positive as expected; the pooled correlation across all scenario types is near-zero, which is a
Simpson's-paradox confound (different scenarios have different baseline risk), not evidence the
score is broken (`docs/methodology.md` §6.1).

### Model 2b — Secondary/Experimental Risk Scorer (`src/ml_models/train_risk_scorer.py`)

**Plain-language**: a trained ML alternative to the hand-tuned score, kept only as a comparison
point — explicitly **not** used to generate any risk number a patient or clinician would see.

**Technical**: `XGBRegressor` (`n_estimators=100`, `max_depth=3`), same 5 features as Model 2a.
**Training data**: the same 117-row Phase 4 dataset, 5-fold CV stratified by scenario (no
held-out split — 117 rows split three ways leaves too small a test set). **Performance**: MAE
0.089 ± 0.020, R² 0.828 ± 0.091 across folds. **Why it's secondary, not primary**: n=117 is too
small for a reliable black-box model (same reasoning behind keeping the hand-tuned score primary),
and the dataset has real, uncorrected class imbalance — `cardiac_stress` (15 rows) and
`acute_deterioration` (12 rows) are underrepresented specifically *because* those are the two
scenarios whose high-severity runs crash (§5) — meaning the model has seen the fewest examples of
exactly the cases where an inaccurate score would matter most. File:
`models/risk_scorer_xgb.joblib` (gitignored, regenerate with `python -m src.ml_models.train_risk_scorer`).

---

## 5. Bugs found and fixes made — full history

Chronological, oldest first.

### 1. Phase 2 — EF-severity double-stacking crash (found + fixed)

**What broke**: applying both the binary `ChronicVentricularSystolicDysfunction` condition's
fixed EF cut *and* a second, separate EF-derived continuous severity cut on top of it pushed a
test patient (EF=26.6) into a real crash — `"Can't transport with a negative volume"`,
`IrreversibleState` — the same failure signature investigated in much more depth in item 4 below.
**How found**: manual Phase 2 validation, caught by the crash-detection code (`run_pulse()`) being
built in the same phase. **Resolution**: **fixed** — the continuous multiplier was changed to
represent only the *additional acute* severity on top of what the condition already applies, not
a second full cut (`docs/methodology.md` §4).

### 2. Phase 8 — live severity-regressor bug (found + fixed)

**What broke**: a 25-patient batch run through the real, live API (not a direct function call)
measured severity MAE 0.271 — vs. 0.048 offline. Scenario classification was unaffected (100%
live agreement); only the continuous severity value degraded badly.
**How found**: only visible by running the full production code path end to end — offline
batch evaluation could never have surfaced it.
**Root cause**: `build_features()` (offline training) computed an `nyha_ordinal` feature from each
synthetic patient's real, varied NYHA class; `build_inference_features()` (the live path) had no
way to know a genuinely new patient's NYHA class yet (it's what the pipeline itself computes
*downstream*), so it silently defaulted every live patient to the most-benign class — a
train/inference feature-availability mismatch, not a coding bug in the classical sense.
**Resolution**: **fixed** — `nyha_ordinal` removed entirely from the feature set, both models
retrained (small offline cost: accuracy 92.3%→90.7%, MAE unchanged 0.048→0.047). Live severity
MAE re-measured at 0.008 on n=5, later 0.0275 on n=20, currently **0.0247 on n=27**
(`models/model_card.md`).

### 3. Phase 5 validation — `fluid_overload` risk-score blind spot (found + fixed)

**What broke**: all 30 `fluid_overload` patients in the 117-row batch scored `risk_score=0.000`
regardless of true severity (0.003 to 0.99).
**How found**: inspecting the raw per-scenario validation numbers in Phase 5.
**Root cause**: `fluid_overload`'s danger is a *chronically shifted baseline* (MAP already
congested at rest, ~77-79mmHg) rather than an *acute change during* the simulated encounter — but
the original 5-feature formula only measures change *during* one run, never an already-abnormal
starting state. Structurally blind to this presentation, not an implementation bug.
**Resolution**: **fixed** — `compute_risk_score()` gained a 6th input, `map_start`, and a new
`baseline_deficit_score` sub-score; final score is `max(acute_score, baseline_deficit_score)`,
leaving the original 5 weights untouched. Mean `fluid_overload` risk_score rose 0.000→0.501,
bucket shifted 30/30 `LOW`→29/30 `MODERATE` (`docs/methodology.md` §6.1).

### 4. 2026-08-17 — Exercise-action instability (characterized, still open — not fixed)

**What broke**: `cardiac_stress`/`acute_deterioration` runs above roughly severity 0.45 crash with
`PulseScenarioDriver exited 1`, a known pattern since Phase 4 but never previously root-caused.
**How found**: pulled the real Pulse `.log` files for 3 independent crashes and read the actual
engine trace, rather than treating "it crashes" as the finding.
**Mechanism found**: the disease-severity modifiers and the `Exercise` action fire in the *same
simulated instant* (zero time gap) → Fatigue → Hypoxia/Tachycardia/Tachypnea → Renal
Hypoperfusion → CardiovascularCollapse → a heart chamber's simulated blood volume goes thousands
of mL *negative* → `IrreversibleState`. All 3 crashes landed within a 154.1-154.32s window — a
deterministic failure, not random flakiness.
**What was tried**: 4 controlled interventions against a reproducible control case — a 60s and a
120s stabilization gap before `Exercise` (both **still crashed**, just delayed by ~exactly the gap
length); a gradual 4-step intensity ramp (**still crashed**, delayed further); `Exercise` alone
with no disease modifiers (**ran clean**); disease modifiers alone with no `Exercise`
(**ran clean**); halved `Exercise` intensity (**ran clean** for that patient). Testing the
intensity-reduction fix on a *second* patient found a **different, lower** safe threshold —
proving the safe boundary is patient/severity-dependent, not one fixed constant.
**Resolution**: **characterized as a limitation, not fixed.** No intensity cap or crash-avoidance
logic was added — the project's existing `MAX_EXERCISE_INTENSITY=0.5` sits above both tested
patients' crash points and isn't a validated safe threshold. A full boundary sweep (~300 Pulse
calls, 12-25 hours) is scoped as real future work, not attempted. Full writeup:
`docs/methodology.md`'s "Known Engine Constraints" (Exercise-action instability subsection).

### 5. 2026-08-17 — 180s Pulse timeout (characterized, still open)

**What broke/was suspected**: an earlier session observed per-patient wall-clock climbing to
700+s mid-run with rising failure rates, hypothesized as Docker Desktop/WSL2-level degradation
after hours of sustained load.
**How found**: re-attempted 2 previously-timed-out patients immediately after a clean Docker
Desktop restart (app fully quit, not just a container restart) on a fresh (~1h-old) session.
**What was found**: both re-attempts *completed*, but at 180.3-180.4s — within 3 seconds of their
original 183.2-183.9s *failures*. Not a meaningful recovery. Ruled out both prior hypotheses:
not session degradation (a fresh session showed the same timing), and not the known
high-severity-Exercise crash pattern (one re-attempt scenario has no `Exercise` action at all).
**Resolution**: **characterized, not fixed** — the actual finding is that some scenario/severity
combinations simply take close to 180s of real wall-clock time on this host's arm64→amd64
emulation, so the timeout has almost no margin; success/failure is sensitive to ordinary timing
jitter. Corroborated by 20+ further data points across later PerHeart/revalidation runs, all
landing in the same 170-200s band. The *original* WSL2-specific degradation hypothesis was neither
confirmed nor refuted (different host/platform, untestable here). Raising `timeout_sec` in
`src/api/services.py`'s `run_pulse()` call is a concrete next option, not attempted.

### 6. 2026-08-17 — `fluid_overload` fix doesn't transfer to unmeasured-EF patients (found + partially fixed)

**What broke**: re-running the PerHeart cohort against fix #3 above found **zero change** in the
one real `fluid_overload` patient's risk score (still 0.000/LOW).
**How found**: comparing that patient's pre-fix and post-fix live API output directly.
**Root cause**: `baseline_deficit_score` needs the Pulse-simulated body to reflect a real,
disease-appropriate EF. This patient's EF was never measured (PerHeart doesn't collect it) and
Tier-1-fallback-defaulted to the healthy-population mean (62%, confirmed by exact match) — telling
Pulse to simulate a structurally *normal* heart regardless of scenario/severity.
**Resolution**: **partially fixed — messaging only.** `risk_caveats` now names this exact
mechanism instead of the stale, generic pre-fix warning. Verifying this live caught and fixed a
real second bug: `ef_is_fallback` was being wrongly re-derived downstream from an already-resolved
value instead of reusing the value already stored at submission time. **The underlying limitation
remains open** — a real EF measurement or validated proxy is the actual fix, not attempted.
(`docs/real_world_data_integration.md` §8.5/§8.5.1, `docs/methodology.md`'s `fluid_overload`
Known Engine Constraints subsection.)

---

## 6. What's left to do

Pulled directly from `HANDOFF.md`'s current to-do list (2026-08-17).

### P1 — biggest blockers to a credible submission

- **Real clinical outcome validation** — *in progress / partially done*. A retrospective slice
  (MIMIC-IV, `baseline_deficit_score` mechanism only, n=17,129 admissions, AUC=0.596) is done and
  documented (`docs/methodology.md` §7.X). The full prospective validation — a real clinical
  partnership comparing this pipeline's output against actual clinician assessments and real
  deterioration events in the target outpatient population — is **not started**; blocked on
  identifying a cardiology department/HF clinic contact and institutional IRB requirements.
- **Diagnose the Pulse timeout behavior** — *done, 2026-08-17* (see §5 item 5 above) — though
  "done" here means characterized, not resolved; the practical mitigation (raise the timeout, or
  accept the failure rate) is still an open decision.
- **Re-run PerHeart against the `fluid_overload` fix** — *done, 2026-08-17* (§5 item 6 above).
- **Increase live-revalidation completion rate** — *attempted, landed at n=27/30 (90%), not the
  full target* — blocked on the same Exercise-instability limitation (§5 item 4); the 3 remaining
  failures are the known crash mechanism, not something a retry fixes.

### P2 — known, scoped gaps worth closing before submission

- **Quantify statistical power more explicitly** — *not started*. n=16 (PerHeart) and n=27 (live
  revalidation) are both still small; widening further (e.g. to n=50) is scoped but not attempted.
- **Benchmark against an established clinical risk score** — *done* (MAGGIC vs. `risk_score.py`,
  `docs/benchmark_comparison.md`).
- **Medication modeling feasibility** — *done* (`docs/medication_modeling_feasibility.md` —
  diuretic modeling is feasible via Pulse's existing substance library; beta-blocker/ACEI modeling
  is not, without Pulse engine-level work).

### P3 — strengthens the paper's positioning

- **Related-work/positioning section** — *first draft done* (`docs/related_work.md`), needs a
  read-through before treating as final — explicitly a non-exhaustive first pass.
- **Formal ethics & data-availability statement** — *first draft done*
  (`docs/ethics_statement.md`), flags open items (IRB determination, target-journal format) that
  need Kaveri's input, not guessable from the repo.

### P4 — standard journal scaffolding

- **Reproducibility package** — *done* (`docs/project-log/reproducibility_package.md`, the
  authoritative documentation index as of this session's reorg).
- **AI-tool-usage disclosure policy** — *not started, blocked* — depends on which journal is
  targeted; a decision only Kaveri can make, not derivable from anything in the repo.

### Not on the priority list, but worth surfacing

- The Exercise-action instability boundary sweep (§5 item 4's "future work" — ~300 Pulse calls,
  12-25 hours of real Docker time) is scoped but not scheduled.
- A real EF measurement/proxy for the unmeasured-EF `fluid_overload` limitation (§5 item 6) has no
  scoped plan yet.
