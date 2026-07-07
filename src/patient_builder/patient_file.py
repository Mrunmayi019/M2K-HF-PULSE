"""Builds a Pulse-compatible patient JSON file from one of our synthetic patients.

Only sets what Pulse's own patient methodology says is safe to set directly (Sex/Age/Height/
Weight) and leaves everything else -- including HeartRateBaseline and blood pressure baselines --
for the engine to auto-compute during stabilization. This matches the project's own planning doc
guidance ("don't hardcode outputs like BP, modify inputs and let the engine compute outputs") and
was confirmed against Patient.proto + the shipped StandardMale.json: there is no direct ejection
fraction / contractility input on the patient file at all.

Structural heart function is instead driven per-scenario via
src/patient_builder/scenario_file.py's use of ef_to_cardiovascular_modifiers() below, applied as a
CardiovascularMechanicsModification action (not a patient-file baseline).
"""
from __future__ import annotations

# Pulse's ChronicVentricularSystolicDysfunction condition is binary (confirmed via
# CardiovascularModel::ChronicHeartFailure() in the engine source: it always applies a fixed
# m_LeftHeartElastanceModifier *= 0.27, with no severity parameter). We apply it only for
# clinically-reduced EF, using the same EF<=40 HFrEF cutoff already used in data_provenance.md.
HFREF_EF_THRESHOLD_PCT = 40.0

# StrokeVolumeMultiplier floor -- Pulse becomes unstable/irreversible at extreme multiplier values
# (same "keep it stable" concern the prototype's generator.py already handles for Hemorrhage
# severity). Bounds are a starting point, to be tuned during Phase 2 validation.
MIN_STROKE_VOLUME_MULTIPLIER = 0.5
MIN_RESISTANCE_COMPLIANCE_MULTIPLIER = 0.6

# Pulse's engine hard-codes these bounds (confirmed in the compiled 4.3.1 image's source,
# engine/human_adult/whole_body/controller/SetupPatient.cpp: `ageMax_yr = 65.0`,
# `BMIObese_kg_per_m2 = 30.0`, `BMISeverelyUnderweight_kg_per_m2 = 16.0`) -- also confirmed
# empirically: Pulse's own shipped Overweight.json patient sits at exactly BMI 30.0, and there is
# no "Obesity"/"Underweight" condition in PatientConditions.proto to work around either bound.
# Real HF patients are frequently older/heavier than the max (our own mimic_bigquery_extract age
# mean is 68.7 -- see data_provenance.md), and our own NHANES-derived weight distribution has a
# wide enough SD to occasionally fall under the low-BMI floor too. The engine will not initialize
# outside [16.0, 30.0] BMI or [18, 65] age at all ("Unable to initialize engine").
#
# Project decision: clamp only at this Pulse-input boundary, not in the underlying synthetic
# population. data/synthetic/patients.csv keeps its full realistic distribution (used by ML Model
# 1, analytics, etc.); only the body actually handed to Pulse is capped into its validated range.
# The patient's true EF/BNP/severity still drive everything else in the pipeline (see
# ef_to_cardiovascular_modifiers below) -- only the simulated body's age/weight are a proxy for
# patients outside Pulse's supported range. See docs/methodology.md limitations section.
PULSE_MIN_AGE_YR = 18.0
PULSE_MAX_AGE_YR = 65.0
PULSE_MIN_BMI = 16.5  # a hair above Pulse's hard 16.0 floor
PULSE_MAX_BMI = 29.5  # a hair under Pulse's hard 30.0 ceiling -- both margins avoid float-rounding rejects


def pulse_eligible_age(age_yr: float) -> float:
    return max(PULSE_MIN_AGE_YR, min(age_yr, PULSE_MAX_AGE_YR))


def pulse_eligible_weight_kg(height_cm: float, weight_kg: float) -> float:
    """Clamps weight so BMI stays within what Pulse will accept, holding height fixed."""
    height_m = height_cm / 100.0
    min_weight_kg = PULSE_MIN_BMI * height_m**2
    max_weight_kg = PULSE_MAX_BMI * height_m**2
    return max(min_weight_kg, min(weight_kg, max_weight_kg))


def needs_pulse_capping(age_yr: float, height_cm: float, weight_kg: float) -> bool:
    """True if this patient's true values fall outside what Pulse can simulate directly --
    useful for validation/reporting on how often the proxy-capping above actually kicks in."""
    bmi = weight_kg / (height_cm / 100.0) ** 2
    age_out_of_range = not (PULSE_MIN_AGE_YR <= age_yr <= PULSE_MAX_AGE_YR)
    bmi_out_of_range = not (PULSE_MIN_BMI <= bmi <= PULSE_MAX_BMI)
    return age_out_of_range or bmi_out_of_range


def build_patient_file(patient: dict) -> dict:
    """Minimal Pulse patient file: Sex/Age/Height/Weight only.

    `patient` is one row (dict-like) from data/synthetic/patients.csv -- needs `sex`, `age`,
    `height_cm`, `weight_kg`. Age and weight are capped into Pulse's supported range (see
    pulse_eligible_age/pulse_eligible_weight_kg above) -- the patient's real values elsewhere in
    the pipeline (patients.csv, severity/EF-driven modifiers) are unaffected.
    """
    height_cm = float(patient["height_cm"])
    return {
        "Name": f"Synthetic_{patient.get('patient_id', 'patient')}",
        "Sex": "Male" if patient["sex"] == "Male" else "Female",
        "Age": {"ScalarTime": {"Value": pulse_eligible_age(float(patient["age"])), "Unit": "yr"}},
        "Height": {"ScalarLength": {"Value": height_cm, "Unit": "cm"}},
        "Weight": {
            "ScalarMass": {
                "Value": pulse_eligible_weight_kg(height_cm, float(patient["weight_kg"])),
                "Unit": "kg",
            }
        },
    }


def ef_to_cardiovascular_modifiers(ejection_fraction_pct: float, severity: float) -> dict:
    """Maps ejection fraction + scenario severity to Pulse CardiovascularMechanicsModifiers.

    Returns a dict with:
      - "apply_systolic_dysfunction_condition": bool -- whether to add
        ChronicVentricularSystolicDysfunction to the patient's Conditions (EF <= 40%)
      - "stroke_volume_multiplier": float -- scales heart driver amplitude down as EF drops and
        as severity rises (the continuous lever, since the Condition above is fixed-severity)
      - "systemic_resistance_multiplier", "systemic_compliance_multiplier": float -- mild
        vascular stiffening with severity, contributing to the same congestive picture

    Severity and EF both push the same direction (worse EF + worse severity -> lower multiplier)
    but are independent inputs: EF sets the chronic/structural floor, severity modulates the
    acute/current degree on top of it.

    IMPORTANT -- do not stack this with the Condition's own effect: when EF <= 40,
    ChronicVentricularSystolicDysfunction already applies a large fixed contractility cut (0.27x
    elastance, see module docstring). Re-deriving a second large multiplier from the same EF value
    on top of that double-counts the reduced-EF signal -- confirmed empirically during Phase 2
    validation, where doing so pushed an EF=26.6 patient into cardiovascular collapse ("Can't
    transport with a negative volume", IrreversibleState). So when the condition applies, the
    continuous multiplier represents *only* the additional acute severity on top of the chronic
    baseline the condition already established, not the EF deficit again.
    """
    severity = max(0.0, min(severity, 1.0))
    apply_condition = ejection_fraction_pct <= HFREF_EF_THRESHOLD_PCT

    if apply_condition:
        combined = severity * 0.5
    else:
        ef_deficit = max(0.0, min((70.0 - ejection_fraction_pct) / 55.0, 1.0))  # 0 (healthy) - 1 (EF~15)
        combined = max(ef_deficit, severity * 0.8)  # severity alone can't fully replicate a chronic EF hit

    stroke_volume_multiplier = max(
        MIN_STROKE_VOLUME_MULTIPLIER, 1.0 - 0.5 * combined
    )
    resistance_compliance_multiplier = max(
        MIN_RESISTANCE_COMPLIANCE_MULTIPLIER, 1.0 - 0.3 * combined
    )

    return {
        "apply_systolic_dysfunction_condition": apply_condition,
        "stroke_volume_multiplier": round(stroke_volume_multiplier, 3),
        "systemic_resistance_multiplier": round(resistance_compliance_multiplier, 3),
        "systemic_compliance_multiplier": round(resistance_compliance_multiplier, 3),
    }
