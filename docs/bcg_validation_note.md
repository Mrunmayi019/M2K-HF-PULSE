# Real-patient BCG validation note — subjects 14 and 102

**Purpose:** validate the HeartGuard AI / Pulse pipeline against real heart-failure patients from
the Zhan et al. (2025) "A Multi-Pathology Ballistocardiogram Dataset for Cardiac Function
Monitoring and Arrhythmia Assessment" (*Scientific Data*; figshare
10.6084/m9.figshare.28416896) instead of synthetic/MIMIC data only. This is a **two-patient
pipeline-mechanics check, not a cohort validation** — see Limitations below for exactly what is
and isn't supported by these runs. Written to be self-contained: a reader with no access to the
session that produced it should be able to follow what was done and why from this file alone.

## Dataset and subject selection

The dataset's HF subgroup has 7 subjects (EF 34-47%); only 3 have the XJ (left-ventricle) M-mode
view this validation needs: **14, 43, 102**. All three were screened before picking:

- **Subject 43** (age 91, AF+HF) was set aside first, before any BCG extraction: Pulse hard-rejects
  patients outside age 18-65 (would need the project's existing age-clamping proxy, an added
  caveat), and its AF (atrial fibrillation) diagnosis means an irregular baseline rhythm that would
  complicate a clean R-J interval in a way neither of the other two candidates has. Never run.
- **Subject 102** (age 45, HF, no arrhythmia tag) was tried next and *was* fully extracted (see its
  own section below) — but its XJ-clip R-R-derived HR (52.8 bpm) showed an unexplained **2.15x**
  discrepancy against its own clinical-sheet HR (115 bpm). This was confirmed to be a real
  discrepancy in the recording, not an artifact of our own extraction: the dataset's own
  auto-generated `signal.pdf` plot for this subject independently shows the same ~53 bpm rhythm
  over its stated 0-20s time axis, and three other subjects' (14, 43, 100) own R-R-derived HR all
  landed within ±20% of their sheet HR, ruling out a systematic sample-rate bug. The source paper
  offers no explanation (no breath-hold/sedation/rest-vs-acquisition protocol note). This
  discrepancy does **not** block subject 102's own BCG-feature extraction or Pulse run (both
  proceeded successfully, see below) — it only means subject 102's session HR could not be trusted
  as ground truth for its own HR comparison, so `Subject_Info.xlsx`'s HR (115) is used instead
  (see its results section).
- **Subject 14** (age 53, PVCS+HF) was picked as the primary/first-run subject specifically because
  its own cross-check was clean (77 xlsx vs. 81.0 bpm R-R-derived, 1.05x) with no equivalent
  age-clamping or rhythm-irregularity caveat.

Both 14 and 102 were ultimately run end-to-end (see their own sections below); 43 was screened out
before extraction and never run.

## BCG feature extraction method (both subjects)

Each subject's XJ folder has `signal.csv` (100Hz raw BCG / ECG / denoised BCG, no explicit time
column) plus two small annotation files, `*_BCG.csv` and `*_ECG.csv` (point index + time per
detected peak). Confirmed empirically, not assumed:
- The dataset's own paper states `_BCG.csv` gives "J-peak positions in the BCG signal."
- `_ECG.csv` points were checked against the raw `ecg` column and are genuine local maxima
  (checked indices 126/243/354 for subject 102 — each sits exactly at its window's max),
  consistent with R-wave peaks.
- I and K are **not** annotated by the dataset at all. I is located as the minimum in the 200ms
  window preceding each J (per Ashouri, Orlandic & Inan, 2016, *Sensors* 16(6):787); K is the first
  local minimum after J (per Feng et al., 2023, *Frontiers in Physiology* 14:1201722), both found
  on the denoised BCG channel.
- **R-J pairing:** each R-peak is matched to the nearest BCG-J-peak time falling in a 50-300ms
  window after it (a plausibility window, not a fixed offset) — beats with no J-peak in that window
  are excluded, not force-matched to a distant one.
- **Beat exclusion, per subject:**
  - *Subject 14:* 0 of 20 beats excluded. Checked for PVCs (short-coupling-interval +
    compensatory-pause R-R pattern) — none found; corroborated independently by the dataset's own
    file-tagging convention, where subject 14's ALL-sheet `Data_file` field is
    `EJ(PVCs)、XJ、ZJ(PVCs)` — only its EJ/ZJ views carry the PVC tag, not XJ.
  - *Subject 102:* 3 of 17 R-peaks excluded (no BCG J-peak fell in their 50-300ms window) and 4 of
    18 nominal BCG peaks were left unpaired (1 pre-recording edge artifact, 3 spurious detections).
    The underlying ECG R-R series is itself clean and regular (no arrhythmia), so this is treated
    as a BCG-side peak-detection quality issue specific to this recording, not a rhythm problem —
    14 clean R-J-paired beats were used for both R-J interval and I/J/K amplitude.

- **Subject 14 BCG features** (20 clean sinus beats): R-J interval mean 233.0ms (SD 22.6), IJ
  amplitude mean 1.172, JK amplitude mean 1.496 (dataset's own relative signal units, no published
  calibration factor — see Limitations).
- **Subject 102 BCG features** (14 clean R-J-paired beats): R-J interval mean 175.0ms, IJ amplitude
  mean 1.061, JK amplitude mean 1.162.

## Subject 14 — primary run

- **Patient file:** `build_patient_file()` unchanged, no new code needed — Sex/Age/Height/Weight
  mapped directly, no Pulse-range clamping required (age 53, BMI 27.3 both native).
- **Scenario:** EF=34.7% run through the existing `ef_to_cardiovascular_modifiers()` unchanged.
  BCG features run through a new `bcg_to_cardiovascular_modifiers()` (same file/pattern), producing
  `VenousComplianceMultiplier=0.901` (from R-J interval, via Bicen et al. 2017) and
  `SystemicComplianceMultiplier=1.0` (from IJ/JK amplitude, via Feng et al. 2023) — see that
  function's docstring for the full citation/derivation. `scenario_file.py` gained a minimal
  `extra_modifiers` parameter so a real per-patient measurement can override a scenario's own
  generic severity-based value for the same field, rather than the two stacking.
- **Scenario type/severity: manually assigned** (`acute_deterioration`, severity 0.35) from the
  real EF/diagnosis, per methodology.md's own EF-profile taxonomy (HFrEF/low-EF profile). **ML
  Model 1 (the scenario classifier) could not run and its validation is explicitly out of scope
  here** — it needs a 21-day wearable-trend window that does not exist for a single-session
  dataset patient.
- **Crash-boundary check, done before running:** Exercise intensity = severity × 0.6 = 0.21,
  comfortably under both the general 0.45 caution line and `acute_deterioration`'s own observed
  crash range (0.6-0.85, Phase 4). Confirmed correct — the run completed cleanly.

## Run result

`PulseScenarioDriver` inside `kitware/pulse:4.3.1`: **SUCCESS**, final simulated time 660/660s,
zero fatal/irreversible markers. Two non-fatal warnings, both anthropometric (not BCG-related):

```
Patient height of 160 cm is outside of typical ranges - below 3rd percentile (190 cm). No guarantees of model validity.
Patient BMI of 27.3437 kg/m^2 is overweight. No guarantees of model validity.
```

## Subject 14 default-configuration numbers

(This is subject 14's half of the full default-vs-HR-baseline comparison — see the consolidated
**Results** section below, after both subjects are introduced, for the side-by-side table across
both patients and both configurations.) Simulated resting HR (72.27 bpm) happens to land close to
the real value (77 bpm, 0.94x) — but this is not evidence of personalization accuracy: Pulse's
patient file deliberately never set a HR baseline in this default configuration
(`build_patient_file()`'s original design, "leaves everything else... for the engine to
auto-compute"), so the simulated value is Pulse's generic population default converged from
Age/Height/Weight/EF-condition alone, not a fit to this patient's real HR. Confirmed as
coincidental, not signal, by subject 102's own default-configuration result (0.63x, far worse —
see below) using the identical non-personalized design.

**SV/CO gap, traced stage by stage.** (Two corrections folded in here from an initial pass: the
t=0 value was first mischaracterized as "the simulated SV" without noting it's the *pre-modifier*
value, and the `StrokeVolumeMultiplier`'s own effect was initially assumed to show up as a simple
~9% cut before checking the actual trajectory. Both are corrected below, not just asserted.) Not
just "the engine doesn't take SV as input" — that explains why a gap *can* exist, not why it's this
large. The t=0 value above is *before* the scenario's
`CardiovascularMechanicsModification` action ever fires (that happens at t=60s) — so the
`StrokeVolumeMultiplier=0.912` (a ~9% cut) plays no part in the 65.72mL vs. 113.87mL comparison at
all. The full chain, confirmed from the engine log and a clean counterfactual run:

| Stage | SV (mL) | vs. real (113.87mL) |
|---|---|---|
| 1. Anthropometric-only baseline (Age/Height/Weight/Sex, pre-EF-condition) — engine log's "Successfully tuned circuit with tissue resistances," CO=5727.57 mL/min ÷ HR=72 | 79.55 | 0.699x (30.1% short) |
| 2. Post-`ChronicVentricularSystolicDysfunction` condition, pre-scenario-action (CSV t=0) | 65.72 | 0.577x (42.3% short) |

Decomposing the 42.3%-of-real shortfall (48.15mL) at stage 2: **71.3% (34.32mL) comes from the
anthropometric baseline alone**, before any EF or BCG input touches it; **28.7% (13.83mL) comes
from the EF condition's fixed 0.27x elastance cut**; the continuous multiplier contributes **0%**
to this figure, since it isn't active yet.

**Height-build counterfactual, to test whether the baseline shortfall is specifically a
height/build penalty (it isn't).** Ran two clean, EF-condition-free, modifier-free
"stable/severity=0" patients differing only in height: (A) 160cm/70kg (subject 14's real values —
triggers both Pulse warnings above) vs. (B) 175cm/70kg (same weight, triggers neither warning).
Result: **SV was identical, 79.46mL vs. 79.46mL.** Pulse's baseline SV does not scale with height
in this comparison — the anthropometric-range warnings and the SV shortfall are decoupled. The
~79.5mL baseline looks like a largely generic value for this patient class rather than a
height-penalized one: a structural mismatch between Pulse's generic body-scaling defaults and this
individual's real measured SV, not evidence that this patient's specific build is disadvantaged by
the engine.

**The `StrokeVolumeMultiplier`'s own isolated effect could not be observed in this run.** It fires
at the same instant (t=60s) as the `Exercise` action, and Exercise's inotropic/venous-return
response dominates it: SV *rises* immediately after t=60s (66.3→70.9→81.0→86.0→88.1mL from
t=60-70s) rather than dropping ~9%, before later collapsing to 50.8mL by t=120s as HR climbs into
extreme tachycardia and diastolic filling time collapses. **Open option, not run here:** isolating
the multiplier's own contribution would need a separate run with `CardiovascularMechanicsModification`
applied but `Exercise` suppressed or time-delayed — flagged for later if this specific number
becomes load-bearing for a claim.

At end-of-scenario (t=660s, severity 0.35 `acute_deterioration`): HR saturates at the computed
maximum (170.9 bpm), MAP drops to 54.7 mmHg (crosses this project's own 65mmHg instability
threshold), SV falls further to 51.2mL, CO rises to 8757 mL/min on the back of the HR spike alone
— the classic "HR up, SV can't augment" HFrEF pattern this project's own Phase 2 validation
already documented for `acute_deterioration`. This is a consequence of the manually-chosen
severity/scenario, not something being validated against a real acute event — no real acute-event
data exists for this single-session patient to compare it to.

## Subject 102 — second patient, subject-14-anchored reference

Same pipeline, second real patient: Male, age 45, height 182cm, weight 94kg, EF 35.1%
(`Subject_Info.xlsx`), same manual `acute_deterioration`/severity=0.35 assignment (same EF-profile
reasoning, no wearable-trend data for either patient). BCG features: R-J interval 175.0ms (n=14
clean-paired beats), IJ amplitude 1.061, JK amplitude 1.162.

**Reference-point role-swap.** `bcg_to_cardiovascular_modifiers()` gained two optional parameters
(`rj_reference_ms`, `amplitude_reference`, defaulting to subject 102's own values so subject 14's
already-completed run is unaffected) so this run could use **subject 14's** measured values as its
reference point instead — otherwise subject 102 would trivially score deficit=0 on both terms
against its own numbers. Result is a clean mirror image of subject 14's own run: subject 102's R-J
(175.0ms) is *shorter* than the subject-14 reference (233.0ms) → `VenousComplianceMultiplier`
clamps to **1.0** (inert — looks "better" than reference); its amplitude (composite 1.1115) is
*lower* than the reference (1.334) → `SystemicComplianceMultiplier` = **0.95** (active). Subject
14's run had the opposite pattern (venous active, systemic inert) — the same n=2 structural point
as before, now demonstrated from both directions rather than asserted once.

**Crash-boundary check:** identical to subject 14 (severity 0.35, Exercise intensity 0.21) —
confirmed safe before running.

**Run result:** SUCCESS, final simulated time 660/660s, one non-fatal warning this time (BMI 28.38
overweight only — 182cm doesn't trigger the height warning subject 14's 160cm did).

**Ground-truth choice, explicit per instruction:** subject 102's own XJ-session R-R-derived HR
(52.8 bpm) is the unreliable value flagged earlier (2.15x mismatch against its own sheet, never
explained) — so **`Subject_Info.xlsx`'s HR=115 is used as ground truth here, not the session
value**, unlike every other "real" figure in this note which comes from the same session as the
BCG features. This is a genuine asymmetry between the two subjects' validations worth keeping
visible, not smoothing over.

Subject 102's own default-configuration numbers (t=0, post-EF-condition, pre-scenario-action):
simulated HR 72.13 bpm, SV 68.20mL, CO 4919.6 mL/min — against real HR 115 (xlsx, see ground-truth
note above), SV 78.21mL (EDV 221.92 − ESV 143.71), CO ~8994 (SV×HR). Ratios: **HR 0.63x, SV 0.87x,
CO 0.55x**. See the consolidated **Results** section below for both subjects' full default-vs-
HR-baseline-experiment comparison, side by side.

Two things invert relative to subject 14: HR is now the *worse*-matching ratio (0.63x, vs. subject
14's coincidentally-close 0.94x) precisely because the real value being compared against (115) is
now the reliable xlsx figure rather than a session-derived number Pulse's default might happen to
land near — this is the same "HR baseline is never personalized by design" limitation as subject
14, just visible more starkly here because the correct ground truth was used. SV, by contrast, is
notably closer than subject 14's (0.87x vs. 0.58x) — subject 102's real/simulated build differs
from subject 14's in both weight (94kg vs 70kg) and age (45 vs 53), and the step-1 height
counterfactual already ruled out height as the driver of Pulse's baseline-SV shortfall; whether
weight specifically narrows the gap here was not tested with a matched counterfactual for this
patient and shouldn't be assumed from this single comparison.

At end-of-scenario (t=660s): HR reaches 124.7 bpm (below subject 14's saturated 170.9 — the two
patients' `HeartRateMultiplier` is identical at 1.14, so this reflects a different computed
maximum-HR ceiling for this patient's anthropometrics, not a different severity), MAP drops to
57.6 mmHg (crosses the 65mmHg instability threshold, same as subject 14), SV rises slightly to
63.4mL, CO rises to 7910.6 mL/min.

## Results — default configuration (primary) vs. HR-baseline experiment (follow-up)

Both run sets below are final and both are reported — the HR-baseline experiment is a follow-up
test of one specific fix hypothesis, not a replacement for the default-configuration numbers,
which remain the primary reported result reflecting this pipeline's actual current behavior.

### Default configuration (no HR baseline) — primary reported result

This reflects current production behavior: `build_patient_file()` is called with no
`hr_baseline_bpm` argument (its default), exactly as every existing synthetic-patient call site in
this codebase already does — confirmed by grepping every call site (`src/pulse_runner/batch_runner.py`,
`src/analytics/projection.py`, `src/api/services.py`, `src/api/continuous_state_pipeline.py`,
`scripts/validate_phase2.py`, all 5 `tests/test_patient_builder.py` call sites): none pass
`hr_baseline_bpm`. This is the number set this validation should be cited as, unless the
HR-baseline experiment below is specifically what's being discussed.

| Subject | HR sim / real | HR ratio | SV sim / real | SV ratio | CO sim / real | CO ratio |
|---|---|---|---|---|---|---|
| 14 | 72.27 / 77 | 0.94 | 65.72 / 113.87 | **0.58** | 4749.9 / ~8768 | **0.54** |
| 102 | 72.13 / 115 | **0.63** | 68.20 / 78.21 | 0.87 | 4919.6 / ~8994 | **0.55** |

(Subject 102's real HR here is `Subject_Info.xlsx`'s 115, not its own unreliable session-derived
52.8 — see the ground-truth note above.) Both patients land in the same ~45-55% CO shortfall band
despite very different HR ratios (0.94 vs. 0.63) — subject 14's HR closeness is coincidental (see
above), not evidence the default configuration personalizes well when it happens to look good.

### HR-baseline experiment — follow-up test, not the default

`build_patient_file()` gained an optional `hr_baseline_bpm` parameter (default `None`, fully
backward-compatible — the existing `test_no_baseline_hr_or_bp_set` test still passes unchanged,
and no production/default call site passes it, confirmed above) to test whether setting Pulse's
`HeartRateBaseline` directly from each patient's real xlsx HR improves the SV/CO match. Pulse's
documented valid range for this field is 50-110 bpm; subject 102's real 115 falls above it and was
clamped to 110 (same "clamp only at the Pulse-input boundary" policy as age/BMI) — flagged
explicitly since it means subject 102's row below isn't testing its true value.

**Result: HR itself matches almost perfectly, as designed — but SV got measurably *worse* in both
patients, and CO barely moved.** Not the clean improvement the hypothesis suggested — a real,
valuable negative result, reported as found:

| Subject | Configuration | HR ratio | SV ratio | CO ratio |
|---|---|---|---|---|
| 14 | Default (no baseline) | 0.939 | 0.577 | 0.542 |
| 14 | HR baseline=77 (experiment) | **1.003** | **0.547** ↓ | 0.549 (flat) |
| 102 | Default (no baseline) | 0.627 | **0.872** | 0.547 |
| 102 | HR baseline=110, clamped from 115 (experiment) | **0.958** | **0.641** ↓ | 0.615 |

For both patients, forcing a higher starting HR triggered Pulse's own stabilization/tuning to
converge on a *lower* stroke volume than its generic-default tuning did — a real physiological
tradeoff the engine is reproducing (less diastolic filling time at a higher resting HR), not a
bug. Subject 102 shows this starkly: SV ratio dropped from 0.872 (its best absolute-accuracy
number anywhere in this validation) to 0.641 once HR was forced up from Pulse's default 72 to 110.
CO improved somewhat for subject 102 (0.547→0.615, HR's gain outweighing SV's loss) but was
essentially flat for subject 14 (0.542→0.549).

**Conclusion: personalizing only the HR baseline is not sufficient to close the SV/CO gap, and
trades one mismatch for another.** Consistent with the earlier stage-by-stage finding that Pulse's
anthropometric/circuit-level tuning — not the HR starting point — is the dominant driver of the SV
shortfall (see the SV/CO decomposition above). Full run artifacts:
`data/bcg_validation/subject14_hr_baseline/`, `data/bcg_validation/subject102_hr_baseline/`.

**Current operating decision:** `hr_baseline_bpm` remains unset (its default) in every default/
production pipeline path until a joint HR-plus-circuit-parameter calibration exists (see the
`docs/methodology.md` §9 "Self-calibrating baseline" cross-reference in Limitations below) — this
experiment is the evidence for *why* a joint approach is necessary, not an HR-only one. The
parameter itself stays available, opt-in, for exactly this kind of deliberate experiment.

## Absolute vs. relative (trend) accuracy — two different claims, only one of which this dataset can test

Every comparison in this note so far is an **absolute-value** comparison: does the simulator's number match the patient's real number at one point in time? The answer, established above, is "not well" (~45-55% CO gap, now traced to its anthropometric-baseline source, not meaningfully improved by HR-baseline personalization either).

**That is not the metric this system's clinical purpose actually depends on.** The digital twin's stated job (`docs/methodology.md` §1) is to answer "given this patient's trajectory so far, what is their body likely to do next" — a **relative/trend** question: does simulated CO/SV/HR move in the right *direction*, and by roughly the right *magnitude*, when the patient's real condition changes? A system whose absolute values are offset by a consistent ~45-55% could still be clinically useful if it reliably tracks *change* — the same way a scale that reads 5% high everywhere is still useful for tracking weight loss, but a scale that only sometimes reads high is not.

**This dataset cannot measure that, and no trend-accuracy number is fabricated here to fill the gap.** Both subject 14 and subject 102 are **single-session snapshots** — one clinical sheet, one ~15-20s BCG/echo recording, no second time-point. Measuring whether simulated CO *change* tracks real CO *change* needs at least two real time-points per patient (e.g. two clinic visits with echo/BCG months apart, ideally spanning a real clinical change — improving, stable, or worsening) to compute a real delta-accuracy metric (e.g. correlation or MAE between simulated Δ and real Δ across a small cohort). Neither subject in this dataset has that.

**Recommended next validation step, not attempted here:** identify a dataset (this one or another) with ≥2 real time-points per patient, run each patient's pipeline at both time-points using their respective real inputs, and compare the *simulated* CO/SV/HR delta between the two runs against the *real* delta. That is the metric that would actually speak to this system's stated clinical purpose — the absolute-accuracy numbers in this note are a necessary prerequisite finding (they explain *why* the simulator's numbers look the way they do), not a substitute for it.

## Limitations

- **Single-session, not longitudinal.** No wearable-trend window exists for this dataset, so ML
  Model 1 (scenario classifier) could not run; `scenario_type`/`severity` were assigned manually
  from the real EF/diagnosis. Classifier validation is explicitly out of scope for this check.
- **BCG substituted for PPG.** This project's Tier 2 design (methodology.md §3) scoped an
  echo/PPG-derived vascular-compliance term; no PPG dataset was ever available. BCG is a different
  modality measuring a different mechanical signal (whole-body recoil vs. peripheral blood-volume
  pulse) — used here because it's what this dataset provides, not because it's an equivalent
  substitute.
- **n=2 BCG reference points, not a cohort norm.** `bcg_to_cardiovascular_modifiers()`'s reference
  values are subject 102's own measurements — the only other BCG recording available to this
  project — not a population mean. For subject 14 specifically, `SystemicComplianceMultiplier`
  came back exactly `1.0` (no effect) because subject 14's own IJ/JK amplitude happened to be
  *higher* than the n=2 reference, i.e. it looked "better" on that specific axis. This is a
  structural consequence of having only two reference points, not a finding that BCG amplitude is
  clinically uninformative — with a larger reference sample this term would very likely be active.
  Only the venous-compliance term (from R-J interval) was functionally active in this run.
- **BCG amplitude units are relative, not absolute.** The dataset publishes no sensor calibration
  factor; IJ/JK amplitude values are only meaningful *within this dataset's own recordings*, never
  against another BCG sensor/study's absolute g-force values.
- **The R-J-to-compliance and amplitude-to-compliance mappings are single-study literature
  citations** (Bicen et al. 2017 IEEE Sensors J.; Feng et al. 2023 Frontiers in Physiology),
  **not independently validated against outcomes** by this project. Bicen et al. validate R-J as a
  PEP correlate; this project's own further step — PEP prolongation implies reduced venous
  compliance specifically — is this project's extrapolation, not a claim either cited paper makes.
- **M-mode EF vs. Simpson's-biplane EF.** The dataset's EF values come from M-mode echocardiography
  (a single ultrasound line), not the Simpson's-biplane method more commonly used for EF in
  clinical practice and in this project's other (synthetic/MIMIC) EF sources. The two methods are
  not numerically interchangeable in general; this project's existing EF-driven modifiers
  (`ef_to_cardiovascular_modifiers`) treat the input as a plain EF percentage regardless of
  measurement method, so this is a methodological inconsistency across data sources, not something
  this run corrects for.
- **Real BCG-derived venous compliance came out milder than the synthetic taxonomy's generic
  value for the same EF/scenario pairing** — 0.901 (real, from this patient's R-J interval) vs.
  0.825 (`acute_deterioration`'s own generic `max(0.4, 1.0 - 0.5*severity)` formula at
  severity=0.35). Noted here as a concrete real-vs-synthetic personalization delta this pipeline
  can now produce — not a discrepancy to resolve; the two numbers come from different, independent
  sources (a real per-patient waveform measurement vs. a hand-tuned population heuristic) and
  disagreeing is exactly the kind of signal real personalization data is supposed to surface.
- **Pulse's generic anthropometric SV baseline sits well below both patients' real measured SV,
  independent of whether Pulse's own out-of-typical-range warnings fire.** The step-1 height
  counterfactual (see subject 14's SV/CO breakdown above) showed this directly: a "typical"
  175cm/70kg body produced the *same* ~79.5mL baseline SV as the real, warning-triggering
  160cm/70kg body. So subject 14's warnings (height, BMI) are a decoupled signal, not the cause of
  its SV shortfall — and subject 102 (182cm, no height warning, only a mild BMI-overweight
  warning) shows a real SV/CO gap too (0.87x/0.55x), just smaller. The underlying limitation is
  that Pulse's population-generic cardiovascular tuning, not this project's EF/BCG modifiers, is
  the dominant driver of both patients' SV/CO shortfalls — with warning status an unreliable guide
  to how large that shortfall will be.
- **HR baseline personalization was tested and does not close the SV/CO gap** — see the dedicated
  section above. `build_patient_file()` originally omitted a patient-specific HR baseline by
  design (same "modify inputs, let the engine compute outputs" philosophy documented for BP);
  setting it directly from real data (now supported, optional) makes HR match almost exactly but
  makes SV match *worse* in both patients tested, with CO roughly flat-to-modestly-better. The
  original runs' HR closeness (subject 14: 0.94x) was coincidental, not personalization accuracy —
  confirmed by subject 102's much worse original ratio (0.63x) using the same non-personalized
  design.
- **Design constraint for `docs/methodology.md` §9's "Self-calibrating baseline" backlog item,
  discovered by this validation, not hypothetical.** That item currently reads as "compare the
  twin's predicted vitals against a patient's actual incoming wearable readings and iteratively
  correct the baseline" without specifying which parameter(s) to correct. This validation shows
  **naive HR-only self-calibration would likely reduce SV/CO accuracy, not improve it** — demonstrated
  in both subjects tested here: forcing HR baseline toward each patient's real value produced *less*
  diastolic filling time in Pulse's own stabilization, which converged on a *lower* stroke volume
  than the generic-default tuning did (subject 14: SV ratio 0.577→0.547; subject 102: 0.872→0.641,
  its best absolute-accuracy number anywhere in this validation, made worse by the correction).
  **Any future self-calibration implementation must jointly adjust `HeartRateBaseline` together
  with the circuit-level compliance/resistance parameters** (the same anthropometric/circuit tuning
  identified as the dominant SV/CO driver in the stage-by-stage decomposition above) **— correcting
  HR alone is now a known-bad approach for that backlog item, not an untested option.**
- **Absolute-accuracy vs. relative/trend-accuracy is an open, untested distinction** — see the
  dedicated section above. Everything numeric in this note is an absolute-value comparison at one
  time-point; the system's actual clinical purpose depends on relative/trend accuracy (does
  simulated change track real change), which neither subject's single-session data can test. Not
  measured here, not fabricated — flagged as the concrete next validation step.
- **n=7 HF subgroup in the source dataset is illustrative, not a cohort claim** — this validation
  uses two of those seven subjects; no aggregate statistic across the subgroup is computed or
  implied here.
- **Subject 102's ground truth is asymmetric with subject 14's.** Subject 14's real-value
  comparisons all come from the same clinical sheet/session. Subject 102's real HR comparison uses
  `Subject_Info.xlsx`'s HR (115), not its own XJ-session R-R-derived HR (52.8, the value flagged
  earlier as an unexplained 2.15x mismatch never resolved by the source paper) — a deliberate
  substitution of the more trustworthy of two disagreeing real numbers, not an oversight, but a
  genuine asymmetry in how "real" was defined per patient that a reader comparing the two subjects'
  ratios side by side should know about.

## Files

- `scripts/bcg_extract_subject14_features.py` / `bcg_extract_subject102_features.py` — the actual
  R-J/I-J-K extraction code (peak pairing, PVC check, I/K localization) described above. Pure
  pandas/numpy, no Docker required; needs the raw dataset on disk (path set at the top of each
  script). Writes `rj_ijk_features.csv` into each subject's `data/bcg_validation/` folder below.
- `data/bcg_validation/subject14/patient.json`, `scenario.json`, `scenarioResults.csv`,
  `scenario.log`, `full_results.csv`, `rj_ijk_features.csv` — build/run/extraction artifacts for
  subject 14.
- `data/bcg_validation/subject102/patient.json`, `scenario.json`, `scenarioResults.csv`,
  `scenario.log`, `full_results.csv`, `rj_ijk_features.csv` — build/run/extraction artifacts for
  subject 102.
- `scripts/bcg_subject102_validation.py` / `scripts/bcg_subject102_run.py` — subject 102's
  build/crash-check and run scripts, mirroring the subject-14 pair below.
- `scripts/bcg_real_patient_validation.py` — builds patient/scenario files, prints the
  crash-boundary check.
- `scripts/bcg_real_patient_run.py` — runs the built scenario through `run_pulse()`, prints the
  full engine log and first/last result rows (must run inside `kitware/pulse:4.3.1`).
- `data/bcg_validation/step1_diagnostic/{A_160cm,B_175cm}/` — the height-isolation counterfactual
  run's artifacts (patient.json, scenario.json, scenario.log).
- `scripts/bcg_step1_diagnostic.py` — builds/runs the two EF-condition-free, modifier-free height
  counterfactuals used in the SV/CO decomposition above.
- `scripts/bcg_hr_baseline_experiment.py` / `scripts/bcg_hr_baseline_run.py` — build and run
  scripts for the HR-baseline personalization experiment above.
- `data/bcg_validation/subject14_hr_baseline/`, `subject102_hr_baseline/` — patient.json,
  scenario.json, scenario.log, full_results.csv for that experiment (kept separate from the
  original runs' artifacts so both states remain on disk for comparison).
- `src/patient_builder/patient_file.py` — `bcg_to_cardiovascular_modifiers()` and the optional
  `hr_baseline_bpm` parameter on `build_patient_file()` (both new).
- `src/patient_builder/scenario_file.py` — `extra_modifiers` parameter (new, additive, `None` by
  default for every existing synthetic-patient call site).
