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

# Pulse's documented valid range for a directly-set HeartRateBaseline is 50-110 bpm. Real HF
# patients are frequently outside it in either direction (compensatory tachycardia above 110 is
# common, e.g. subject 102's real 115 bpm below) -- same "clamp only at the Pulse-input boundary"
# policy as age/BMI above: the clamped value is what Pulse actually simulates from, the patient's
# true HR elsewhere in the pipeline (reporting, comparison) is unaffected.
PULSE_MIN_HR_BASELINE_BPM = 50.0
PULSE_MAX_HR_BASELINE_BPM = 110.0


def pulse_eligible_age(age_yr: float) -> float:
    return max(PULSE_MIN_AGE_YR, min(age_yr, PULSE_MAX_AGE_YR))


def pulse_eligible_hr_baseline(hr_bpm: float) -> float:
    return max(PULSE_MIN_HR_BASELINE_BPM, min(hr_bpm, PULSE_MAX_HR_BASELINE_BPM))


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


def build_patient_file(patient: dict, hr_baseline_bpm: float | None = None) -> dict:
    """Minimal Pulse patient file: Sex/Age/Height/Weight, plus an optional HeartRateBaseline.

    `patient` is one row (dict-like) from data/synthetic/patients.csv -- needs `sex`, `age`,
    `height_cm`, `weight_kg`. Age and weight are capped into Pulse's supported range (see
    pulse_eligible_age/pulse_eligible_weight_kg above) -- the patient's real values elsewhere in
    the pipeline (patients.csv, severity/EF-driven modifiers) are unaffected.

    `hr_baseline_bpm`: optional, default None -- same optional/backward-compatible pattern as
    scenario_file.build_scenario_file's `extra_modifiers`. None (the default) preserves the
    original behavior for every existing synthetic-patient call site: no HeartRateBaseline key at
    all, Pulse auto-computes it during stabilization (this module's own docstring rationale). Pass
    a real measured resting HR to have Pulse start from that value instead of its generic default
    -- clamped into Pulse's documented 50-110 bpm valid range via pulse_eligible_hr_baseline above
    if outside it (see that constant's own comment for why real patients often are).
    """
    height_cm = float(patient["height_cm"])
    pf = {
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
    if hr_baseline_bpm is not None:
        pf["HeartRateBaseline"] = {
            "ScalarFrequency": {
                "Value": pulse_eligible_hr_baseline(float(hr_baseline_bpm)),
                "Unit": "1/min",
            }
        }
    return pf


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


# ---------------------------------------------------------------------------------------------
# BCG (ballistocardiogram)-derived modifiers -- added for the single-real-patient validation
# extension (Zhan et al. 2025 Multi-Pathology BCG Dataset, figshare 10.6084/m9.figshare.28416896;
# published as Scientific Data, DOI underlying that figshare record). Two features extracted from
# one subject's XJ-view signal.csv + peak annotations (src/... extraction scripts, not committed
# here -- see the validation note for the extraction method):
#   - R-J interval: ECG R-peak to BCG J-peak timing, in ms.
#   - IJ/JK amplitude: BCG I->J and J->K deflection sizes, in this dataset's own signal units.
#
# Reference points below (RJ_INTERVAL_REFERENCE_MS, BCG_AMPLITUDE_REFERENCE) are subject 102's
# measured values from this same dataset -- NOT a population mean, NOT a healthy-baseline norm.
# We have exactly two subjects' worth of real BCG data in this project (subject 14, used as the
# active patient here, and subject 102, set aside as the patient input over an unresolved 2.15x
# HR discrepancy against its own clinical sheet -- see validation note). Subject 102's numbers are
# reused here only as the single available reference point to express subject 14's values as a
# fractional deviation from *something measured*, rather than an invented constant. This is a
# two-point directional observation, not a fitted relationship: with only two subjects, one of
# them necessarily anchors deficit=0 by construction, and nothing here has been checked against a
# third subject, let alone an outcome. If more BCG subjects are added later, replace these two
# constants with a real population mean/SD and refit -- do not extend this scale's absolute
# position to new patients as if it were validated.
RJ_INTERVAL_REFERENCE_MS = 175.0  # subject 102, XJ clip, 14 clean-paired beats, this dataset only
BCG_AMPLITUDE_REFERENCE = 1.1115  # subject 102, mean of (IJ=1.061, JK=1.162), same clip

# Same 0.3 sensitivity coefficient used in ef_to_cardiovascular_modifiers' compliance term, reused
# here rather than inventing a second arbitrary constant -- keeps the two modifier sources
# comparable in scale rather than one dwarfing the other by an unexamined coefficient choice.
BCG_MODIFIER_SENSITIVITY = 0.3


def bcg_to_cardiovascular_modifiers(
    rj_interval_ms: float,
    ij_amplitude: float,
    jk_amplitude: float,
    rj_reference_ms: float = RJ_INTERVAL_REFERENCE_MS,
    amplitude_reference: float = BCG_AMPLITUDE_REFERENCE,
) -> dict:
    """Maps ballistocardiogram (BCG)-derived timing/amplitude features to Pulse
    CardiovascularMechanicsModification "extra" multipliers (VenousComplianceMultiplier,
    SystemicComplianceMultiplier) -- meant to be merged into a scenario's `extra` dict alongside
    ef_to_cardiovascular_modifiers()'s base multipliers, the same way scenario_file.py's
    fluid_overload/acute_deterioration branches layer their own VenousComplianceMultiplier on top
    (see _scenario_actions), not as a replacement for the EF-driven base.

    Inputs, both measured from one subject's XJ-view recording (see module comment above for the
    reference-point provenance):
      - rj_interval_ms: mean ECG-R-peak-to-BCG-J-peak interval, milliseconds.
      - ij_amplitude, jk_amplitude: mean BCG I->J and J->K deflection amplitudes, in this
        dataset's own raw/denoised signal units -- NOT calibrated g-force or any absolute
        mechanical unit. The source dataset does not publish a sensor calibration factor, so these
        numbers are only meaningfully comparable *within this dataset's own recordings* (e.g.
        subject 14 vs subject 102), never against a different BCG sensor/study's amplitude values.
        Any scaling constant derived from them (BCG_AMPLITUDE_REFERENCE above included) is
        dataset-specific for the same reason, not a universal physiological constant.
      - rj_reference_ms, amplitude_reference: the "other" subject's own measured values, used as
        this call's single reference point (deficit=0 anchor). Default to subject 102's values
        (this module's own constants) for the subject-14 run; pass subject 14's own values
        explicitly when running subject 102, so whichever subject is NOT the active patient
        anchors the scale -- same n=2 framing either way, just with the two subjects' roles
        swapped depending on which one is being run. Never both default to the same subject's own
        measurements, which would trivially force deficit=0.

    Mapping and citations -- each maps ONE feature to ONE multiplier, deliberately not fused,
    since the two source citations validate two different, independent physiological claims:
      - R-J interval -> VenousComplianceMultiplier. Bicen, Gurel, Dorier & Inan (2017), "Improved
        Pre-Ejection Period Estimation From Ballistocardiogram and Electrocardiogram Signals by
        Fusing Multiple Timing Interval Features," IEEE Sensors Journal 17(13):4172-4180. That
        paper validates R-J interval as a correlate of pre-ejection period (PEP); a prolonged PEP
        is a recognized marker of reduced ventricular contractility. This project extrapolates
        that further to venous compliance specifically (a compensatory venoconstriction response
        to declining forward function) -- that second link is this project's own inference, not a
        claim Bicen et al. themselves make. Longer R-J -> assumed lower venous compliance.
      - IJ/JK amplitude -> SystemicComplianceMultiplier. Feng et al. (2023), "Non-invasive
        monitoring of cardiac function through Ballistocardiogram: an algorithm integrating
        short-time Fourier transform and ensemble empirical mode decomposition," Frontiers in
        Physiology 14:1201722, reports positive correlations between I-J amplitude and both
        cardiac output and stroke volume (J-K is included here as a same-complex secondary
        feature, averaged with I-J, but the cited correlation is specifically for I-J -- not
        independently confirmed here for J-K). Lower amplitude -> assumed lower systemic
        compliance/reduced forward output.

    IMPORTANT, same discipline as ef_to_cardiovascular_modifiers' own warning: this is a single
    real patient's data run through two single-study literature mappings, not something
    independently validated against clinical outcomes, echo ground truth, or a larger BCG cohort.
    Treat the returned multipliers as illustrative of the *pipeline mechanics* (can real BCG
    features flow into a Pulse modifier and stay inside safe bounds), not as a clinically-vetted
    personalization signal. Floors reuse ef_to_cardiovascular_modifiers' own
    MIN_RESISTANCE_COMPLIANCE_MULTIPLIER (0.6) -- the stroke-volume-specific 0.5 floor doesn't
    apply here since neither output is a stroke-volume term -- specifically so this can't combine
    with the EF-driven base to push a CardiovascularMechanicsModification past the ~0.45-severity
    Exercise-action crash boundary documented in docs/methodology.md §4/§5.
    """
    rj_deficit = max(0.0, min((rj_interval_ms - rj_reference_ms) / rj_reference_ms, 1.0))

    amplitude = (ij_amplitude + jk_amplitude) / 2.0
    amplitude_deficit = max(0.0, min((amplitude_reference - amplitude) / amplitude_reference, 1.0))

    venous_compliance_multiplier = max(
        MIN_RESISTANCE_COMPLIANCE_MULTIPLIER, 1.0 - BCG_MODIFIER_SENSITIVITY * rj_deficit
    )
    systemic_compliance_multiplier = max(
        MIN_RESISTANCE_COMPLIANCE_MULTIPLIER, 1.0 - BCG_MODIFIER_SENSITIVITY * amplitude_deficit
    )

    return {
        "VenousComplianceMultiplier": round(venous_compliance_multiplier, 3),
        "SystemicComplianceMultiplier": round(systemic_compliance_multiplier, 3),
    }
