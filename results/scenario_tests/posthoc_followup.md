# Post-hoc follow-up: alert definition check, and alert-smoothing rules

**This document is entirely post-hoc.** `RESULTS.md` (the pre-registered analysis) is unchanged.
Everything here is read-only re-analysis of the already-saved, frozen-harness CSVs
(`results/scenario_tests/daily_results_*.csv`) -- no re-simulation, no change to the harness,
cohort, or schedules. Rule definitions (`results/scenario_tests/posthoc_plan.md`) were written and
committed before any rule below was computed.

## 1. Alert definition: analyze.py's definition vs. the real system's

**`analyze.py`'s `alert_flag`** (what `RESULTS.md` reports) is `current_alert.get("alert") ==
"alert"`, read directly from `src.api.routes._build_status()` -- the real production function,
not a reimplementation (`run_patient_seed.py` imports and calls it directly, line 211). That
function's `current_alert` comes from `src/analytics/score_reporting.py::alert_decision()`:
alerts when `severity > STABLE_SEVERITY_CAP` (0.15) and a confidence floor is met (or
unconditionally if Pulse landed in the crash zone -- the `unstable_completed`/`failed_fallback`
cases).

**The real dashboard uses a different function entirely.** A full-repo grep for every consumer of
`current_alert` / `alert_basis` / `alert_decision` / `build_score_report` outside `src/api/` and
`src/analytics/score_reporting.py` itself returns nothing -- and a grep of `frontend/src/` for
those same names returns nothing either. **No frontend component ever reads `current_alert` or
`alert_decision()`'s output.** Every component that shows risk/alert state --
`HeroStatusCard.jsx` (the main patient status card, including the "Significant deterioration
detected -- clinical follow-up recommended today" banner), `SimulationLabPage.jsx`,
`ReportsPage.jsx`, `DoctorReportCard.jsx`, `TrendsHistoryPage.jsx`, `Sidebar.jsx`, and
`ForwardProjectionPanel.jsx` -- reads `assessment.risk_bucket` instead, which comes from
`src/analytics/risk_score.py::compute_risk_score()`: `risk_bucket == "HIGH"` when `risk_score >=
0.65` (`MODERATE_HIGH_BOUNDARY`).

**These two things disagree substantially** (§2 below) and **the dashboard a clinician would
actually look at only ever shows the second one.** `alert_decision()` is real, reachable backend
code (returned by the `/status` API), but it is dead weight as far as the actual product
experience goes -- nothing displays it. The honest "does the system alert" question should be
answered with `risk_bucket == "HIGH"`, not the pre-registered CSV's `alert_flag` column.

**This is reported as a finding about the pre-registered analysis, not acted on by changing
`RESULTS.md`** (kept unchanged, per instruction) -- the corrected numbers are below and in a
separate file.

## 2. P01, P08, P09: day-by-day, all seeds, under the system's own definition

Full per-day CSVs already existed (`daily_results_{P01,P08,P09}_seed{42,43,44}.csv`); this is a
direct re-read, no new computation beyond `risk_bucket == "HIGH"`.

**P01 (all 3 seeds): `risk_score` never exceeds 0.01 on any of the 63 patient-days. Never reaches
even `MODERATE`, let alone `HIGH`.** The pre-registered `alert_flag` fires intermittently (True on
isolated days -- 7/9/10/14 in seed 42, for example) but `risk_score` stays essentially at zero the
entire time; those `alert_flag=True` days are the severity-threshold definition firing on its own
much lower bar (0.15), disconnected from what the dashboard would show. **Under the system's real
definition, P01 never alerts, in any seed. Correctly quiet.**

**P09 (all 3 seeds): same pattern as P01** -- `risk_score` stays under 0.014 for all 63
patient-days despite `alert_flag=True` on nearly every day. **Never alerts under the system's
definition, in any seed. Correctly quiet.**

**P08 (all 3 seeds): genuinely different.** `risk_score` climbs into `MODERATE` then `HIGH`
starting around day 9-12 (seed 42: day 12; seed 43: day 10; seed 44: day 9) and **stays `HIGH`
through day 21 in all three seeds** -- including days 20-21, where the pre-registered `alert_flag`
had already gone back to `False` (RESULTS.md §7 describes P08 as "recovering on its own" by day
20; **under the system's own definition it does not recover within the 21-day window at all** --
`risk_score` is still 0.92-0.98, still `HIGH`, on day 21 in every seed). `alert_source` is
`scorer` throughout the active period in every case (no `unstable_completed`/`failed_fallback`
days for this patient). **P08 genuinely false-alerts under the system's definition too, and for
longer than the pre-registered analysis suggested, not shorter.**

**Continuity**: P01/P09 are never "on" under the system definition, so there's nothing to
describe as continuous/on-off. P08 is a single continuous `HIGH` episode once it starts (not
flickering on/off day to day) in all three seeds.

## 3. Full headline results, both definitions

| metric | pre-registered (severity > 0.15, `alert_flag`) | **system definition (`risk_bucket == "HIGH"`)** |
|---|---|---|
| should_catch detected (of 5) | 5/5 | **3/5** -- misses P04, P05 |
| should_stay_quiet false-alerted (of 3) | 3/3 | **1/3** -- only P08 |
| false alerts / 100 patient-days (quiet group) | 58.73 | **17.99** |
| edge case P02 (alert in all 3 seeds?) | Yes | **No** -- only seed 44 (day 9) |
| edge case P03 (alert in all 3 seeds?) | No (2/3 seeds) | **No** (0/3 seeds -- never alerts under this definition) |
| weight-rule vs. pipeline agreement | agree only on P02, P04 (of the 2 weight-rule triggers) | **agree on neither** -- P02, P04 both trigger the trivial weight rule but neither reaches `risk_bucket=="HIGH"` in all seeds |
| feature importances (which model/signals) | unchanged -- these describe the *models*, not the alert gate; see RESULTS.md §6 | unchanged, same caveat |
| noise-robustness check (P01/P10, offline) | unchanged -- this check never ran Pulse, so it has no `risk_score` to re-score with; it necessarily used `severity_band()`, the pre-registered definition. **Caveat, not previously stated this plainly: it cannot be redone under the system definition at all**, since `risk_bucket` only exists downstream of a real Pulse run. | n/a |

**should_catch detail under the system definition**: P06 (lead 0, i.e. alerts right at story
onset), P07 (lead -8, alerting well before its own compressed-onset window, same background issue
as everything else), P10 (lead -2) are caught. **P04 (fluid overload) reaches `risk_bucket=="HIGH"`
in 2 of 3 seeds (days 8, 10) but never in seed 42 (`risk_score` peaks at 0.0078, essentially LOW
the whole run) -- a genuine seed-dependent miss, not a near-miss in every seed.** **P05
(deconditioning) never reaches `HIGH` in any seed** (`risk_score` peaks at 0.008-0.012 across all
three seeds) -- a consistent miss, not close in any seed.

**Net effect of using the right definition: the original "near-universal false alert" finding
overstates the problem for P01/P09 (both are actually fine) and understates a different, real
problem (P04 and P05, two should_catch patients, are under-detected by the system's own alert
gate).** P08 remains a genuine false alert either way.

## 4. Post-hoc rules (R1/R2/R3) -- plan in `posthoc_plan.md`, results below

All three operate on `risk_score >= 0.65` per day (the system definition from §1-3), per the
pre-registered plan. `results/scenario_tests/posthoc/posthoc_summary.json` has the exact numbers;
table:

| rule | should_catch detected | false alerts / 100 patient-days (quiet group) | mean lead time (days) |
|---|---|---|---|
| baseline (no smoothing, = §3's system definition) | 3/5 | 17.99 | -3.33 |
| R1 (2 consecutive days) | 3/5 | 15.87 | -2.33 |
| **R2 (3 consecutive days)** | **3/5** | **13.76** | -1.00 |
| R3 (3-day rolling mean) | 3/5 | 14.81 | -1.33 |

**All three rules satisfy criterion 1** (none trades away a should_catch detection -- all keep the
same 3/5 as the baseline; P04 and P05 were never caught by the baseline either, so there was
nothing for smoothing to lose there). **R2 wins criterion 2 outright** (13.76, the lowest false-alert
rate of the four) -- no tiebreak needed.

**Chosen rule: R2 (alert only after 3 consecutive days of `risk_score >= 0.65`).** It cuts the
quiet-group false-alert rate by about 24% relative to the unsmoothed system definition (17.99 ->
13.76 per 100 patient-days) without costing any of the 3 should_catch detections the baseline
already had. It does **not** fix P04/P05's under-detection (smoothing an already-low signal more
aggressively cannot manufacture a detection that was never there) and does **not** fully eliminate
P08's false alert (a sustained, multi-day `HIGH` episode easily survives a 3-day persistence
filter) -- it only trims the shorter, noise-driven spikes elsewhere in the should_stay_quiet group.

## 5. Proposed confirmation run (NOT started)

**Proposal**: run the frozen harness (`run_batch.py`, unmodified) on fresh seeds 45, 46, 47 for all
10 patients (30 jobs, N=6, same as the original batch), then re-apply R2 (and the system
definition from §1-3) to the new CSVs and report the same table as §4, to check R2's false-alert
reduction and the should_catch/should_stay_quiet pattern hold on seeds it wasn't selected on.

**Time estimate**: the original batch (30 jobs, N=6, 21 monitored days/job) took ~2h35m wall clock
end-to-end (6 launch waves x ~31 min/wave under N=6 contention, ~86-90s/day per job; one job needed
3 extra days of lag-recovery time). A confirmation run of the same shape (30 jobs, N=6, 21 days) on
new seeds should take **approximately the same, ~2.5-3 hours**, assuming similar contention and no
unusual Pulse failure streak.

**Not started.** Waiting for a go-ahead before launching.
