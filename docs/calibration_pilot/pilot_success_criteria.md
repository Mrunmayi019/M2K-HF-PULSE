# Calibration pilot — success criteria

Written 2026-10-02, before any pilot simulation was run.

## Arms

- **Arm A-prod (primary baseline):** the patient built by the existing `build_patient_file()` and
  `build_scenario_file()` exactly as production builds it, with `scenario_type="stable"`,
  `severity=0`, and each patient's real EF, sex, height and weight (age assumed 60). Under
  `stable` the scenario has no actions, so of `ef_to_cardiovascular_modifiers()`'s output only the
  `ChronicVentricularSystolicDysfunction` condition (EF ≤ 40) reaches Pulse; its multipliers do not.
- **Arm A-formula (secondary baseline):** the same scenario, plus a
  `CardiovascularMechanicsModification` action carrying `ef_to_cardiovascular_modifiers()`'s
  multipliers, built in a new pilot script only (production code unchanged).
- **Arm B (calibrated):** Pulse knobs calibrated per patient following Gu et al., npj Digital
  Medicine 2025. Not yet built.

## Success rule

Arm B (calibrated) is promising if, in at least 2 of 3 patients, its simulated cardiac output is
closer to the real CO_td than Arm A's, with no additional crashes. Calibration will use EF, MAP
and HR only; CO is held out and used only for evaluation.

"Arm A" in this rule means **Arm A-prod**. Arm A-formula is reported alongside it for context but
is not part of the success rule.

---

## Amendment 1 — 2026-10-02

Written **after** the Arm A results for patients 295/136/120 were seen (commit `8cab8b2`) and
**before** any Arm B run and before the selection script below was run. Why: the real measurements
in the Gu file disagree with each other for those 3 patients (thermodilution vs Fick cardiac
output, echo vs MRI ejection fraction), so a second, independently chosen set of patients with
internally consistent measurements is added. The original text above is unchanged.

a) **Primary rule unchanged.** The success rule above (against CO_td, patients 295/136/120, Arm B
   vs Arm A-prod) remains the primary rule.

b) **Extra reporting.** Every result table also reports error against CO_fick, and reports stroke
   volume error and HR error separately. Real SV = CO / HR_vitals (once with CO_td, once with
   CO_fick); twin SV = twin CO / twin HR.

c) **Second set, "measurement-consistent".** Chosen from real measurements only, first snapshot
   per patient, by applying these filters in this order:
   1. All present (a finite number; > 0 for physical measurements; Sex in {1, 2}): LVEF_tte,
      CO_td, CO_fick, HR_vitals, NIBPs_vitals, NIBPd_vitals, MRI_LVEDV, MRI_LVESV, Height,
      Weight, Sex.
   2. |CO_td − CO_fick| / mean(CO_td, CO_fick) ≤ 0.10.
   3. |LVEF_tte − MRI EF| ≤ 7 percentage points, with MRI EF = (MRI_LVEDV − MRI_LVESV) / MRI_LVEDV × 100.
   4. 16.5 ≤ BMI ≤ 29.5 (no weight clamp needed).
   5. 50 ≤ HR_vitals ≤ 110 bpm. This is the HeartRateBaseline range Pulse 4.3.1 accepts
      (`SetupPatient.cpp`: values outside it are an initialization error).
   6. No valve regurgitation worse than mild, on all four valves (AVr, MVr, TVr, PVr). Grade
      coding, worked out by comparing the numbers with their `_str` text across the whole
      dataset: 1.0 none, 1.5 minimal/trace, 2.0 mild, 2.5 mild-to-moderate, 3.0 moderate,
      3.5 moderate-to-severe, 4.0 severe. Code 1.0 is also used for "Doppler not available"
      and "not optimally visualized"; 0 and −1 are unparsed or missing text. **A valve passes
      only if its grade is known to be ≤ mild**: numeric 1.5 or 2.0, or numeric 1.0 with a
      "No evidence" text. Not-assessed or unknown valves fail. The selection log also reports
      the count under the looser reading (numeric ≤ 2.0 regardless of text), for information
      only.
   7. Not one of patients 295, 136 or 120.

   From the patients that pass, 3 are picked in this order: echo EF closest to 25, then closest
   to 40, then closest to 58. Ties go to the smaller CO_td/CO_fick gap. A patient already picked
   is not eligible for a later target. If fewer than 3 patients pass, nothing is picked and the
   rule is not loosened.

   The same 2-of-3 success rule (Arm B vs Arm A-prod, CO_td) is applied to this set and reported
   separately. Age is still unreadable from the file, so the fixed 60-year assumption carries over.

d) **Arm B design.** In Arm B, HR is set directly from HR_vitals (via `hr_baseline_bpm`), and
   calibration searches for EF and MAP only. CO stays held out.

---

## Closing note — 2026-10-02

**The pilot is closed. Arm B was not built or run, so the success rule above (and its Amendment 1
extension) was never evaluated.** There is no Arm B result, positive or negative.

Reason: before the blood-pressure lever check was run, a feasibility bar was set in planning
discussion: Arm B is only worth building if each patient's real EF, HR and MAP are within what
the twin can reach for at least 4 of the 6 pilot patients. The check found 1 of 6 (patient 136).
See `data/calibration_pilot/bp_check_report.md`, answer 4. Most misses are MAP. With the
weak-heart condition on, the highest MAP the twin reached was 78.5 mmHg by the (2·DBP + SBP)/3
formula, and the blood-pressure baseline is the only lever that moves MAP.

**This feasibility bar was agreed in discussion before the check ran, but it was not committed to
this repository beforehand.** Unlike the success rule and Amendment 1, it therefore has no
commit-history proof that it predates the result. It is recorded here only after the fact.

Summary of the whole pilot: `docs/calibration_pilot/pilot_summary.md`.
