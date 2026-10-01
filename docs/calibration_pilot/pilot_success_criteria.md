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
