# Medication-Effect Modeling — Feasibility Check

**Status: research only, no implementation.** Per `HANDOFF.md` P2's own framing ("do a quick
feasibility check ... before committing engineering time — this might be out of reach without
engine-level work"), this is a scoped answer to "can Pulse do this at all, and how far," not a
build. `docs/methodology.md` §8/§9 already flags the absence of medication modeling as a real
gap for real-world applicability (nearly all HF patients are on a diuretic, beta-blocker, and/or
ACE inhibitor/ARB) — this doc is the first actual investigation into it.

## What was checked

Pulse's public documentation (`pulse.kitware.com`): the drugs/pharmacology methodology page and
the `SubstanceBolusData`/action reference, plus this project's own `src/patient_builder/
scenario_file.py` (how existing actions — `Exercise`, `CardiovascularMechanicsModification` — are
constructed and wrapped for a Pulse scenario JSON) to ground the effort estimate in this
codebase's actual patterns, not a generic guess.

## Finding 1 — Pulse has a real drug engine, and it already models a diuretic

Pulse's actions include `SubstanceBolus` and `SubstanceInfusion`, backed by a genuine
physiologically-based pharmacokinetic (PBPK) + pharmacodynamic (PD) model — substance mass enters
the vena cava compartment, is transported through the bloodstream, and cleared renally/hepatically/
systemically. This is not a stub.

**Furosemide (a loop diuretic) is already in Pulse's modeled substance library**, with a
documented mechanism: blocks the tubular Na-K-Cl cotransporter, increases urine production and ion
excretion, and **decreases blood volume by 500-1000 mL**. This maps directly onto this project's
`fluid_overload` scenario — the exact presentation whose risk-score blind spot was fixed this
project via the `baseline_deficit_score` term (`src/analytics/risk_score.py`, `docs/methodology.md`
§6.1). A diuretic bolus/infusion action is therefore both mechanistically real in Pulse and
clinically on-target for a scenario this project already models.

## Finding 2 — Beta-blockers and ACE inhibitors/ARBs are not in Pulse's substance library

The documented substance list covers diuretics (furosemide), sympathomimetic pressors
(epinephrine, norepinephrine, phenylephrine), anesthetics/sedatives (propofol, etomidate,
midazolam, lorazepam, ketamine), analgesics (fentanyl, morphine), neuromuscular blockers, a
bronchodilator (albuterol), and a few reversal/miscellaneous agents (naloxone, pralidoxime,
prednisone). **No beta-blocker, ACE inhibitor, or ARB substance is documented.** These would need
new `Substance` definitions authored inside Pulse itself (PK/PD parameters — clearance,
volume of distribution, the actual heart-rate/contractility/afterload dose-response curves) — not
something this project's patient_builder/scenario layer can add by itself, since it only
constructs scenario JSON that references Pulse's own substance definitions by name.

## Effort estimate

- **Diuretic (furosemide) modeling — feasible now, moderate effort.** Would follow the same
  pattern as the existing `Exercise` action in `scenario_file.py`'s `_exercise_action()`/
  `_scenario_actions()`: a new `_substance_bolus_action()` (or infusion) helper wrapped in
  `PatientAction`, added conditionally for `fluid_overload` scenarios (and any others where a
  diuretic response is clinically expected). Needs: confirming the exact `SubstanceBolus` JSON
  schema (dose units, `Concentration`/`Rate` fields) against a real Pulse scenario file, then the
  same empirical validation loop already used for every other action in this project (run inside
  the Pulse container, check for the timing/stabilization gotchas `scenario_file.py`'s comments
  already document — e.g. the `Incremental: true` requirement found for
  `CardiovascularMechanicsModification`). Rough estimate: **1-3 days**, most of it validation, not
  code.
- **Beta-blocker / ACE inhibitor / ARB modeling — not feasible without Pulse engine-level work.**
  Would require authoring new `Substance` PK/PD definitions inside Pulse's own codebase (not this
  project's), then validating them against real dose-response data before trusting any output —
  exactly the kind of "unfounded precision" this project's own locked Tier-3 decision
  (`docs/methodology.md` §9) already commits to avoiding for anything not empirically validated in
  this project. **Recommend not pursuing this** within the current project scope.

## Recommendation

If medication modeling is pursued at all, scope it to **furosemide/diuretic-only**, applied to
`fluid_overload` (and possibly `acute_deterioration`) scenarios — this covers a real, common HF
treatment and reuses Pulse's own validated PK/PD model rather than inventing one. Explicitly do
**not** attempt beta-blocker/ACEI/ARB modeling without first confirming Pulse (or a specific fork/
version of it) has since added those substances — re-check `pulse.kitware.com`'s documentation
before committing to this, since it may have been extended since this check
(2026-08-17).
