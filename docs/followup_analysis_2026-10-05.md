# Follow-up analysis, 2026-10-05 (items 1-5)

Read-only, from the already-saved scenario-test CSVs (feature/scenario-testing) and the real
`decide_alert()`/`compute_baseline_high_streak()`/`compute_risk_score()` -- no new Pulse runs, no
code changes. Scripts: `src/evaluation/scenario_tests/followup_analysis.py`. Full data:
`results/scenario_tests/posthoc/followup_item1_{dev,heldout}.json`, `followup_item3.json`.

## 1. Evaluation table (perturbation-aware)

**Perturbation start day per patient** (first day with a scheduled `event` in `cohort.yaml`; P01
has none at all):

| P01 | P02 | P03 | P04 | P05 | P06 | P07 | P08 | P09 | P10 |
|---|---|---|---|---|---|---|---|---|---|
| none | 5 | 4 | 4 | 4 | 4 | 10 | 5 | 4 | 4 |

**Rule applied**: a day counts toward *detection* only if `day >= perturbation_start` AND the
patient is `should_catch`/`edge_case`. Every `should_stay_quiet` day, and every pre-perturbation
day for any patient, counts as *false* if it's ALERT or WATCH.

### Per-patient, per-seed (days ALERT / days WATCH / first ALERT day / first WATCH day)

**DEV (42-44)**

| patient | seed | days ALERT | days WATCH | first ALERT | first WATCH | false ALERT days | false WATCH days |
|---|---|---|---|---|---|---|---|
| P01 (quiet) | 42/43/44 | 0/0/0 | 0/0/0 | -/-/- | -/-/- | none | none |
| P04 (catch) | 42/43/44 | 0/14/12 | 0/2/1 | -/8/10 | -/6/9 | none | none |
| P05 (catch) | 42/43/44 | 0/0/0 | 0/0/0 | -/-/- | -/-/- | none | none |
| P06 (catch) | 42/43/44 | 3/3/5 | 15/15/14 | 5/5/4 | 4/4/3 | none | none / none / [3] |
| P07 (catch) | 42/43/44 | 20/17/18 | 0/0/2 | 2/5/3 | -/-/2 | [2-9]/[5-9]/[3,5-9] | none/none/[2,4] |
| P08 (quiet) | 42/43/44 | 3/3/5 | 8/10/12 | 12/10/9 | 11/9/5 | **all of them** (quiet) | **all of them** (quiet) |
| P09 (quiet) | 42/43/44 | 0/0/0 | 0/0/0 | -/-/- | -/-/- | none | none |
| P10 (catch) | 42/43/44 | 17/3/20 | 1/16/0 | 5/4/2 | 4/3/- | none/none/[2,3] | none/[3]/none |

**HELD-OUT (45-47)**

| patient | seed | days ALERT | days WATCH | first ALERT | first WATCH | false ALERT days | false WATCH days |
|---|---|---|---|---|---|---|---|
| P01 (quiet) | 45/46/47 | 0/0/12 | 4/0/5 | -/-/10 | 18/-/5 | [10-21] (seed47) | [18-21](45), [5-9](47) |
| P04 (catch) | 45/46/47 | 0/0/0 | 0/0/20 | -/-/- | -/-/2 | none | none/none/[2,3] |
| P05 (catch) | 45/46/47 | 3/0/0 | 14/0/0 | 6/-/- | 5/-/- | none | none |
| P06 (catch) | 45/46/47 | 5/17/5 | 14/2/14 | 4/5/4 | 3/3/3 | none | [3]/[3]/[3] |
| P07 (catch) | 45/46/47 | 18/18/19 | 0/0/0 | 4/4/3 | -/-/- | [4-9] all three | none |
| P08 (quiet) | 45/46/47 | 3/3/3 | 10/14/14 | 10/6/6 | 9/5/5 | **all of them** (quiet) | **all of them** (quiet) |
| P09 (quiet) | 45/46/47 | 0/0/1 | 0/0/0 | -/-/21 | -/-/- | [21] (seed47) | none |
| P10 (catch) | 45/46/47 | 3/18/17 | 17/1/2 | 5/4/5 | 2/3/3 | none | [2,3]/[3]/[3] |

(P02/P03, edge cases, excluded from this table for brevity -- both never ALERT or WATCH at all in
either seed set, except P02 dev seed 44, which reaches ALERT day 9/WATCH day 5, both on or after
its own perturbation start day 5.)

### Group totals

| | DEV | HELD-OUT |
|---|---|---|
| should_catch reaching ALERT on/after perturbation, all 3 seeds | **3/5** | **3/5** |
| should_catch reaching at least WATCH on/after perturbation, all 3 seeds | **3/5** | **3/5** |
| should_stay_quiet, any ALERT (any day, any seed) | P08 only | **P01 and P08** |
| should_stay_quiet, any WATCH (any day, any seed) | P08 only | **P01, P08, and P09** |

should_catch is unchanged from the risk-scorer-alert finding (P06/P07/P10 caught; P04/P05
structurally missed -- WATCH doesn't add a catch here since the "all 3 seeds" rule still fails
for P04/P05 in both sets, per `docs/unified_alert_evaluation.md`). **The should_stay_quiet
picture is worse on held-out than previously reported**: P01 now shows a real false ALERT (seed
47) and a real false WATCH (seed 45); P09 shows one false ALERT day (seed 47, day 21) and no
WATCH days. P08 remains the one confirmed false alarm in both sets, every day of it, since it has
no real perturbation to detect at all.

## 2. P01 held-out seed 47 -- corrected: a false ALERT, not corroboration

Full day-by-day:

| day | predicted_scenario | predicted_severity | Exercise fired | map_start | map_end | instability_flag | risk_score | risk_bucket |
|---|---|---|---|---|---|---|---|---|
| 1 | deconditioning | 0.067 | No | 95.18 | 95.05 | 0 | 0.0009 | LOW |
| 2 | deconditioning | 0.108 | No | 95.05 | 95.09 | 0 | 0.0000 | LOW |
| 3 | deconditioning | 0.116 | No | 95.09 | 95.14 | 0 | 0.0058 | LOW |
| 4 | deconditioning | 0.070 | No | 95.14 | 96.03 | 0 | 0.0000 | LOW |
| 5 | **cardiac_stress** | 0.097 | **Yes** | 96.03 | 75.31 | 0 | 0.4506 | MODERATE |
| 6 | deconditioning | 0.123 | No | 75.31 | 77.39 | 0 | 0.6249 | MODERATE |
| 7 | deconditioning | 0.237 | No | 77.39 | 78.35 | 0 | 0.5494 | MODERATE |
| 8 | deconditioning | 0.241 | No | 78.35 | 77.03 | 0 | 0.5146 | MODERATE |
| 9 | deconditioning | 0.138 | No | 77.03 | 74.03 | 0 | 0.5625 | MODERATE |
| 10 | deconditioning | 0.127 | No | 74.03 | **46.35** | **1** | 0.8500 | **HIGH** |
| 11-21 | deconditioning (every day) | 0.08-0.29 | No | ~59-60 (settled) | ~59-60 | 1 | 1.0 (day 11+) | HIGH |

This is reported as what it is: **P01 is the should_stay_quiet control; this entire trajectory
(days 5-21) is a false ALERT**, driven by Pulse's own cascade, not by anything the patient's
"stable, ordinary life" story called for. Retracting the earlier framing ("genuine
corroboration") -- that language wrongly implied the sustained instability made this a
legitimate signal. It doesn't: `instability_flag` being 1 is why C3 doesn't *downgrade* it (C3 is
only designed to catch one specific false-alarm shape, not to judge whether an alert is
clinically warranted), not evidence that the alert itself is warranted. It is correctly described
as a false ALERT in §1's table above.

## 3. Finding (a): confirmed, with one correction

**Confirmed, exhaustively, with zero exceptions**: across all 10 patients x all 6 seeds (60
series), **every single `HIGH` day is preceded by (or occurs on) a day where the classifier
predicted `cardiac_stress` or `acute_deterioration`** (`EXERCISE_SCENARIO_INTENSITY_FACTOR`'s only
two keys) **somewhere earlier in that same patient-seed's run.** Checked programmatically, not
sampled: 0 violations.

**Correction to "and never recovers afterwards"**: more precisely, **`map_start` never recovers
*back to its healthy baseline* once an Exercise-firing day has occurred** -- but it is NOT simply
frozen after that first trigger. P01 seed 47 (§2 above) shows `map_start` continuing to move
substantially on *non*-Exercise days afterward: a mild drift (75.3 -> 78.3 -> 74.0, days 6-9) then
a sharp, unprompted crash (74.0 -> 46.4) on day 10, five days after the only `cardiac_stress` day
and while every intervening day was classified `deconditioning`. This is Pulse's own continuous
cardiovascular dynamics evolving under the daily-reissued `CardiovascularMechanicsModification`
(severity/EF-driven, reissued every day regardless of Exercise -- `continuous_state_pipeline.py`'s
own module docstring), not a second Exercise trigger. The accurate statement: **an Exercise-firing
day is necessary to ever leave the healthy baseline in the first place (0 counterexamples); it is
not the only day `map_start` can move, and the post-trigger trajectory can include further,
unprompted large moves, not just a flat carry-forward.**

### P01, P04, P05, P08 -- scenario-label counts, first Exercise day, first MODERATE/HIGH day, all 6 seeds

| patient | seed | scenario counts | first Exercise day | first MODERATE | first HIGH |
|---|---|---|---|---|---|
| P01 | 42 | deconditioning:21 | never | never | never |
| P01 | 43 | deconditioning:21 | never | never | never |
| P01 | 44 | deconditioning:21 | never | never | never |
| P01 | 45 | deconditioning:18, cardiac_stress:3 | 18 | 18 | never |
| P01 | 46 | deconditioning:21 | never | never | never |
| P01 | 47 | deconditioning:20, cardiac_stress:1 | 5 | 5 | 10 |
| P04 | 42 | deconditioning:19, fluid_overload:2 | never | never | never |
| P04 | 43 | deconditioning:16, cardiac_stress:5 | 6 | 6 | 8 |
| P04 | 44 | deconditioning:19, cardiac_stress:1, fluid_overload:1 | 9 | 9 | 10 |
| P04 | 45 | deconditioning:21 | never | never | never |
| P04 | 46 | deconditioning:21 | never | never | never |
| P04 | 47 | cardiac_stress:4, deconditioning:17 | 1 | 2 | never |
| P05 | 42 | stable:1, deconditioning:20 | never | never | never |
| P05 | 43 | stable:4, deconditioning:17 | never | never | never |
| P05 | 44 | stable:6, deconditioning:15 | never | never | never |
| P05 | 45 | stable:3, deconditioning:17, cardiac_stress:1 | 5 | 5 | 6 |
| P05 | 46 | deconditioning:19, stable:2 | never | never | never |
| P05 | 47 | stable:4, deconditioning:17 | never | never | never |
| P08 | 42 | stable:7, deconditioning:5, cardiac_stress:9 | 11 | 11 | 12 |
| P08 | 43 | stable:6, deconditioning:3, cardiac_stress:12 | 9 | 9 | 10 |
| P08 | 44 | stable:7, cardiac_stress:11, deconditioning:3 | 5 | 5 | 9 |
| P08 | 45 | deconditioning:7, stable:6, cardiac_stress:8 | 9 | 9 | 10 |
| P08 | 46 | stable:5, cardiac_stress:13, deconditioning:3 | 5 | 5 | 6 |
| P08 | 47 | stable:6, cardiac_stress:13, deconditioning:2 | 5 | 5 | 6 |

**Note added 2026-10-09:** "first Exercise day" here is the first day with an Exercise-triggering **label**. Monitored day 1 goes through `run_initial()`, which never applies Exercise, so P04 seed 47's "1" means labelled on day 1 and Exercise first applied on day 2 (day-1 HR 72.0 → 73.9, MAP flat, LOW). See `docs/research_flags_evaluation.md` §7.1. The "0 violations" check above still holds with applied Exercise.

(`acute_deterioration` never appears for any of these four patients in any seed -- only
`cardiac_stress` actually fires Exercise for this group; both are counted in the global check.)

## 4. Why 29/30 fluid_overload validation cases reach MODERATE, and P04 mostly doesn't

**Exact mechanism, confirmed in `src/patient_builder/patient_file.py::ef_to_cardiovascular_
modifiers(ejection_fraction_pct, severity)`**:

```python
HFREF_EF_THRESHOLD_PCT = 40.0
apply_condition = ejection_fraction_pct <= HFREF_EF_THRESHOLD_PCT
if apply_condition:
    combined = severity * 0.5
else:
    ef_deficit = max(0.0, min((70.0 - ejection_fraction_pct) / 55.0, 1.0))
    combined = max(ef_deficit, severity * 0.8)
```

When `EF <= 40`, Pulse's `ChronicVentricularSystolicDysfunction` condition is applied -- a large,
fixed structural hit, independent of severity. This is what builds a congested *resting* MAP
baseline from construction, not an acute response to anything during the encounter.

**The 30-case validation set**: EF range 15.0-43.5%. **29 of 30 have EF <= 40** (condition
applied); their `map_start` sits at ~78-79mmHg regardless of severity (checked across 5 sampled
rows spanning severity 0.3-0.964, `map_start` is 78 or 79 in every one -- EF-driven, not
severity-driven). **The one case with EF > 40 (43.5%) has `map_start = 94.0mmHg`** -- healthy,
matching the 1/30 that stays `LOW` exactly.

**P04's cohort EF is 51.0%** (`cohort.yaml`'s neutral band, Amendment A) -- above the 40%
threshold. `ef_to_cardiovascular_modifiers` therefore never applies the condition for P04; its
`map_start` begins at the healthy ~95mmHg baseline (confirmed, §3's table and `scorer_diagnosis.
md`), exactly like the validation set's one EF>40 outlier. **Yes -- the neutral EF band from
amendment A is the reason P04's physiology barely changes.** It was deliberately chosen to sit
above `HFREF_EF_THRESHOLD_PCT` for every patient in the cohort (removing the EF-matches-severity
confound amendment A was built to fix), but that same choice removes the one mechanism
(`ChronicVentricularSystolicDysfunction`, construction-time, EF-driven) that reliably produces a
congested baseline independent of what happens during any single day's encounter. P04 is left
with only the indirect route (an Exercise-triggered acute event that happens to cascade and
carry forward, §3) -- noise-dependent, not a deterministic property of being a "fluid_overload
patient" the way EF<=40 was for the original validation set.

**Scope note**: the scenario-test cohort's EF range is narrow by construction -- Amendment A
assigned EF 48-57% to all 10 patients (`cohort.yaml`: P01=48 ... P10=57, one percentage point
apart, by patient-ID order), entirely above the 40% threshold. Nothing in this cohort tests a
patient with EF<=40 at all, so this comparison establishes the mechanism (confirmed exactly
against the 30-case validation set, which does span EF 15-43.5%) but does not itself probe how
this scorer behaves for an HFrEF-range scenario-test patient -- there isn't one in this cohort.

## 5. decide_alert() implementation checks

**Does the offline evaluation call the real `decide_alert()`, or a copy?** The real one.
`src/evaluation/scenario_tests/followup_analysis.py` (and `unified_alert_eval.py` before it):
`from src.analytics.score_reporting import AlertAssessmentView, compute_baseline_high_streak,
decide_alert` -- the exact same module the live API imports from
(`src/api/models.py`/`routes.py`/`services.py`/`continuous_state_pipeline.py` all import from
this same file). No reimplementation anywhere.

**C3's "no instability_flag ever seen" -- what window?** **The current streak only**, not the
patient's whole history. `compute_baseline_high_streak()`'s own logic: `instability_seen` resets
to `False` every time the streak itself resets (day isn't `HIGH`+`baseline`-dominant), and is
only carried forward while the streak is continuously active. An instability day from a *previous,
already-broken* streak is forgotten; only instability within the *currently active* streak blocks
the C3 downgrade.

**What happens across a failed day?** `mark_simulation_run_failed()` returns before the
`RiskAssessment`-insert block in both `services.py` and `continuous_state_pipeline.py` -- **no
`RiskAssessment` row, and therefore no streak update, is ever written for a failed day.** The
next successful day's `previous_assessment` query (`order_by(id.desc()).first()`) finds the last
*successful* row, skipping the gap entirely. **A failed day is invisible to the streak -- it
neither resets it nor advances it; the streak resumes exactly where it was before the failure, as
if the failed day had not been attempted.** This mirrors the pipeline's own "resume from last
good state, one encounter behind" design elsewhere, but is stated explicitly here since
`compute_baseline_high_streak()`'s own docstring doesn't call this out.

**Persisting streak state -- new DB column? How do existing databases get it?** Yes, two new
nullable columns on `RiskAssessment` (`baseline_high_streak_days`, `instability_seen_in_streak`,
`src/api/models.py`). **This project uses no migration framework -- `Base.metadata.create_all()`
only, which creates missing *tables*, not missing *columns* on an existing table.** Any SQLite
file that already has a `risk_assessments` table from before this change would **not**
automatically gain these two columns; the next `INSERT` naming them would raise
`sqlite3.OperationalError: table risk_assessments has no column named baseline_high_streak_days`.
Checked: there is no persisted/deployed `.db` file anywhere in this repo and no Alembic directory
(confirmed by `find`), so this is not an active bug against anything existing today -- but it is a
real gap for any future real deployment with a pre-existing database file, which would need a
manual `ALTER TABLE` (or a fresh DB) before this code could run against it. Not fixed here, since
no code change was authorized for this message; flagged for a decision.
