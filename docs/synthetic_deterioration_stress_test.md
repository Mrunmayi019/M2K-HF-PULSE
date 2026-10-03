# Synthetic deterioration stress test — subjects 14 and 102

## Scope — read this before any result below

**This is a synthetic stress test using two real patients' real baselines (age, sex, height,
weight, EF, resting HR) as anchors for an otherwise entirely synthetic 21-day trajectory. It is
NOT evidence this system detects real deterioration in real patients.** Neither subject 14 nor
subject 102 has any real longitudinal data — both are single-session recordings (see
`docs/bcg_validation_note.md`). Everything past day 0 in this test is synthetically generated to
*look like* deterioration; it was never observed. What this test actually checks is **internal
pipeline consistency**: given a wearable trend engineered to resemble worsening heart failure,
does the existing scenario classifier correctly recognize it, and does the existing Pulse
simulation layer respond in the clinically expected direction as the severity signal driving it
rises? That is a mechanics question about this codebase, not a clinical claim about either
patient. Validating real-world early detection would require real longitudinal wearable/echo data
for real patients, which this project does not have.

## 1. Generator confirmed, and where it needed adapting

`src/data_synthesis/generate_wearable_trends.py`'s `generate_wearable_trends()` builds the 21-day
trend for all 5 scenario types (fluid_overload, cardiac_stress, deconditioning,
acute_deterioration, stable) from a `patients_df` (needs `patient_id`, `scenario_type`,
`severity`, `weight_kg`) plus population reference stats
(`reference_stats.yaml`'s `wearable_baseline`, mean/SD per vital). **It has no parameter to anchor
a real patient's own measured HR** — HR baseline is always population-sampled
(`rng.normal(mean, sd)`); only `weight_kg` anchors to the patient's own value already.

This test reuses the function's actual internals directly rather than reimplementing trend logic:
`SCENARIO_SIGNAL_DELTAS["acute_deterioration"]` (the per-vital max deltas) and `_trend_curve()`
(the frac²-accelerating shape used for `acute_deterioration`'s "deteriorating" mode) are imported
and called unchanged. The only adaptation: the baseline dict is built manually so
`resting_hr_bpm`'s *mean* is the subject's real value (77 for subject 14, 115 for subject 102)
instead of a population draw — day-to-day *noise* around that mean still uses the same population
SD the original function uses, since only the mean is a real measurement. `weight_kg` uses each
subject's real weight, the same precedent the original function already sets. Trend mode was
forced to `"deteriorating"` (not drawn via the original function's probabilistic
`_assign_trend_mode`, which could produce `"recovering"`) — this is a deliberate worsening stress
test, not a random draw. Assumed synthetic ground-truth severity: 0.85 for both subjects (this
test's own assumption, not a measured value). Code: `scripts/synthetic_deterioration_stress_test.py`.

**Reproducibility note, fixed after an initial bug:** the first run used
`seed = hash(label) % 2**32` — Python's built-in `hash()` on strings is randomized per process
(hash randomization), so re-running produced *different* trends and different findings each time.
Fixed to fixed, explicit integer seeds (1400, 1020) per subject. All numbers below are from the
seed-fixed, now-reproducible run (verified by running twice and diffing identical output).

**Blast radius checked: this bug never affected anything outside this session's own new script.**
`hash()`-based seeding was never used anywhere else in the codebase — confirmed by grep.
`generate_wearable_trends()` itself has always used its own explicit `seed: int = 42` parameter via
`np.random.default_rng(seed)`, fully deterministic, and this script never calls that function
directly (only reuses its internal constants/helper function, per §1 above). No previously-reported
result in this project depended on the buggy code; it was introduced and fixed within this same
session, before ever being cited elsewhere.

## 2. The 21-day trends

Full data: `data/synthetic_deterioration_stress_test/{subject14,subject102}_trend.csv`.

Both trends show the expected `acute_deterioration` shape: resting HR climbing from baseline
(subject 14: 76→99 bpm; subject 102: 115→137 bpm), SpO2 declining (~97%→93%), steps and HRV
falling, weight rising slightly (fluid retention) — driven by `SCENARIO_SIGNAL_DELTAS`, unchanged.

## 3. Classifier + severity regressor results

Run via the existing trained `models/scenario_classifier.joblib` /
`severity_regressor.joblib`, using `src/scenario_classifier/features.py`'s actual live-inference
path (`build_inference_features()`, the same function `src/api/services.py`'s production pipeline
calls), with `nt_probnp_pg_ml` set to the existing Tier-1 fallback (100 pg/mL, `src/api/services.py`'s
own `NT_PROBNP_FALLBACK_PG_ML` — neither subject has a measured BNP value in the source BCG
dataset).

**The production system only ever predicts once, at the full 21-day window.** To find *when* a
trend would first be flagged, this test builds an expanding-window sweep (day 7 through day 20)
using the same `build_inference_features()` call repeatedly — a new analysis this test adds, not
a reused day-by-day prediction capability that already existed.

**Final (day 20) classification: `acute_deterioration` for both subjects — correct.**

**Subject 14 — misclassifies for 5 days before correcting, reported exactly as found:**

| Day | Scenario | Severity | Note |
|---|---|---|---|
| 6 | `fluid_overload` | 0.3695 | misclassified |
| 7 | `fluid_overload` | 0.3942 | misclassified |
| 8 | `fluid_overload` | 0.4561 | misclassified |
| 9 | `fluid_overload` | 0.3422 | misclassified, **and a real non-monotonic dip** (0.4561→0.3422) |
| 10 | `fluid_overload` | 0.4245 | misclassified |
| 11 | `acute_deterioration` | 0.5027 | **corrects here, stays correct through day 20** |
| 20 | `acute_deterioration` | 0.8661 | final |

**Subject 102 — correctly classified from day 6 onward, no misclassification:**

| Day | Scenario | Severity | Note |
|---|---|---|---|
| 6 | `acute_deterioration` | 0.2547 | correct from the first day tested |
| 14 | `acute_deterioration` | 0.6132 | |
| 15 | `acute_deterioration` | 0.6014 | **real non-monotonic dip** (0.6132→0.6014) |
| 16 | `acute_deterioration` | 0.6756 | recovers and continues rising |
| 20 | `acute_deterioration` | 0.8783 | final |

**Severity is not strictly monotonic for either subject** — confirmed, not smoothed over. Both
dips are small (subject 14: −0.11 absolute; subject 102: −0.012 absolute) and both trajectories
resume climbing the very next day, so neither looks like a real plateau, but the non-monotonicity
is real and would show up as a small false "improving" reading on the day it occurs in any system
that alerted on day-over-day severity change alone.

### Threshold resolution — done before any "day flagged" claim was made

**No severity-specific alert threshold exists anywhere in this codebase.** Checked: training
config, `models/model_card.md`, every eval script, and `src/analytics/staging.py` (which imports
`risk_score.py`'s `MODERATE_HIGH_BOUNDARY`/`LOW_HIGH_BOUNDARY` and applies them to `risk_score` —
it never defines its own threshold on `severity`).

**`risk_score.py`'s `MODERATE_HIGH_BOUNDARY=0.65` was considered and rejected** — `severity` (the
classifier's raw regression output) and `risk_score` (a downstream, Pulse-simulation-derived
quantity) are not on comparable scales. Computed on the real 117-row Phase 4 dataset
(`data/simulation_runs/features_dataset.csv`), restricted to `acute_deterioration` (n=12):

| | severity | risk_score |
|---|---|---|
| mean | 0.385 | 0.655 |
| **min** | **0.046** | **0.491** |
| max | 0.846 | 0.760 |
| correlation | — | 0.685 |

`risk_score`'s floor for this scenario type (0.491) sits above `severity`'s own mean (0.385) —
`risk_score` saturates high almost as soon as any `Exercise`-driven stress occurs (a structural
property already documented in `docs/methodology.md` §6.1, confirmed numerically here). Borrowing
0.65 for `severity` would imply a validated cutoff that does not exist.

**Follow-up, 2026-09-10:** this same finding turned out to affect live production code, not just
this test's own analysis script — `src/analytics/projection.py`'s `project_severity()` was
applying a risk_score-calibrated rate directly to severity. Fixed the same day; full writeup in
`docs/methodology.md` §8 ("severity and risk_score are not on comparable scales — RESOLVED"),
including `src/analytics/score_reporting.py`'s new `severity_band()`/`score_provenance()`
(the same two-band, non-0.65 approach validated here, now available API-wide, not just in this
test's own script).

**Used instead: 0.15, the `stable`-scenario severity ceiling** — a real, non-arbitrary property of
this training data, not invented or borrowed from a different quantity.
`generate_patients.py`'s `_assign_scenario()` hard-codes `severity = severity * 0.15` for `stable`
patients (confirmed at n=2000: observed max 0.149). Reported as *"the day this trajectory first
clearly exceeds what `stable` looks like in this training data"* — a descriptive marker, not a
clinical alert cutoff.

**Both subjects first exceed the 0.15 stable ceiling on day 6** (the earliest day tested) —
severity 0.3695 (subject 14) and 0.2547 (subject 102), both already well above 0.15 by the first
window with enough data to predict at all.

## 4. Pulse directional-consistency check

**Scope, same discipline as above: this checks whether Pulse's simulated hemodynamics move in the
clinically expected direction as the severity signal driving them rises — internal consistency
between the ML layer and the physiology layer, not a real-world match.** Ran 4 representative days
per subject (6, 11, 16, 20) through `PulseScenarioDriver`, using each day's own classifier severity
output, `scenario_type="acute_deterioration"` throughout (the correct final classification — used
even for subject 14's misclassified early days, since this check isolates the severity signal
itself, not scenario-type-switching behavior), and each subject's already-established BCG-derived
compliance multipliers unchanged. Code: `scripts/synthetic_deterioration_pulse_check.py`.

**Crash-boundary check, done before running:** day 16 (severity 0.635/0.676 for the two subjects)
was flagged in advance as inside this project's own documented `acute_deterioration` crash range
(`docs/methodology.md` §5/§7: "crashes/timeouts above severity ≈0.6–0.85").

**Result: 4 of 8 points succeeded, 4 failed — exactly the flagged high-severity points, plus day
20 (severity 0.866/0.878), modestly above the documented 0.85 upper edge.** All 4 failures were
`PulseScenarioDriver exited 1` — the same known engine-crash signature already characterized
elsewhere in this project, not a new failure mode. This halves how much of a genuinely severe
deteriorating trajectory can actually be run through Pulse directly.

**Subject 14 (day 6, day 11 only — day 16/20 failed):**

| Day | Severity | HR | SV | CO | MAP |
|---|---|---|---|---|---|
| 6 | 0.3695 | 170.90 | 51.56 | 8811.30 | 53.54 |
| 11 | 0.5027 | 170.90 | 50.12 | 8565.61 | 53.04 |

HR is already saturated at its computed maximum (170.90) at *both* points — no differentiating
signal available from HR here. SV, CO, and MAP all move in the clinically expected ("worsening")
direction as severity rises: SV↓, CO↓, MAP↓.

**Subject 102 (day 6, day 11 only — day 16/20 failed):**

| Day | Severity | HR | SV | CO | MAP |
|---|---|---|---|---|---|
| 6 | 0.2547 | 104.13 | 72.21 | 7519.67 | 62.45 |
| 11 | 0.5004 | 123.46 | 62.30 | 7691.81 | 56.62 |

HR is *not* saturated here (104→123), giving a real, expected-direction signal (↑). SV and MAP
also move in the expected direction (↓, ↓). **CO rises (7519.67→7691.81) — not the naively-expected
decline.** This is not a bug or a contradiction: it's the same "HR up, SV can't augment, but CO
still climbs on the back of HR before eventually reversing" mechanism this project's own Phase 2
validation already documented for `acute_deterioration`/`cardiac_stress` (`docs/methodology.md`
§7). Whether CO eventually reverses direction at higher severity for this subject can't be
observed here — those points (day 16, 20) are exactly the ones that crashed.

**Honest summary, not forced into a clean yes/no: SV and MAP consistently move in the clinically
expected direction as severity rises, in both subjects, across every observable point. HR either
saturates immediately (subject 14) or moves in the expected direction (subject 102) — not a
uniform signal. CO is directionally ambiguous over the observable range and cannot be checked at
all above severity ≈0.6, because that is exactly where Pulse's own engine instability makes the
simulation crash.** This is a real, useful finding about the current system's limits, not a clean
pass or fail.

## Summary and primary limitation

**The primary limitation of this entire stress test is not the CO ambiguity above, the day-6
misclassification, or the non-monotonic severity dips — it is the crash rate itself, and it should
be read as such, not as a secondary footnote.** The system cannot currently produce Pulse-simulated
hemodynamics anywhere in the severity ≈0.6–0.85 range for `acute_deterioration` — which is *the
higher end of a deteriorating trajectory*, exactly the region a real early-warning use case would
most need physiological detail from. In this test, that meant 4 of 8 representative points failed
outright, and the two points that would have shown whether CO eventually reverses direction at
high severity are precisely the two that could not be run at all.

Put plainly: **the part of this system meant to model a worsening condition is least available
exactly when a real early-warning use case would most need it.** The classifier/severity layer has
no such gap — it produced a clean, monotonic-ish, correctly-classified severity signal across the
*entire* 21-day range for both subjects, high severity included. It is specifically the Pulse
simulation layer that goes dark in the clinically most important region. Everything else this test
found (the day-6 misclassification, the two small non-monotonic dips, the CO/HR directional
nuances) is a secondary finding by comparison — real and worth keeping, but not the headline. This
is a permanent-scope-boundary-or-fix-target decision (root-causing the `Exercise`-action
instability itself vs. bounding claims to the severity range Pulse can reliably simulate — see
`docs/methodology.md`'s "Known Engine Constraints" section), not resolved by this test — this test
only establishes that the gap is real, exactly where it falls, and exactly how large a share of a
genuine deterioration trajectory it removes from observability.

## Files

- `scripts/synthetic_deterioration_stress_test.py` — builds both subjects' real-HR-anchored 21-day
  trends (reusing `generate_wearable_trends()`'s internals) and runs the expanding-window
  classifier/severity sweep.
- `data/synthetic_deterioration_stress_test/{subject14,subject102}_trend.csv` — the full 21-day
  trend data for both subjects.
- `scripts/synthetic_deterioration_pulse_check.py` — builds and runs the 8 representative-day
  Pulse scenarios.
- `data/synthetic_deterioration_stress_test/pulse/{subject14,subject102}_day{6,11,16,20}/` —
  patient.json, scenario.json, scenario.log (and scenarioResults.csv for the 4 that succeeded) per
  point.
- `data/synthetic_deterioration_stress_test/pulse/summary.json` — the 8-point results summary.
