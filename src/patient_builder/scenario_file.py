"""Builds a Pulse scenario JSON for one of the 5 locked scenario types + a severity level.

Unlike the prototype's src/generator.py (which maps ad hoc condition names to Hemorrhage/Exercise
actions), this targets the locked taxonomy from CLAUDE.md (stable, fluid_overload, cardiac_stress,
deconditioning, acute_deterioration) and drives severity primarily through the
CardiovascularMechanicsModification action (see patient_file.ef_to_cardiovascular_modifiers for
why -- Pulse has no direct EF/contractility input).
"""
from __future__ import annotations

from src.patient_builder.patient_file import ef_to_cardiovascular_modifiers

DATA_REQUESTS = [
    {"Category": "Physiology", "PropertyName": "HeartRate"},
    {"Category": "Physiology", "PropertyName": "MeanArterialPressure"},
    {"Category": "Physiology", "PropertyName": "SystolicArterialPressure"},
    {"Category": "Physiology", "PropertyName": "DiastolicArterialPressure"},
    # OxygenSaturation is a Scalar0To1 (~0.95-0.99) -- without an explicit DecimalFormat, Pulse's
    # default output formatting ("SystemFormatting" = system's own choice, usually 0 decimal
    # places) truncates it to always 0. Confirmed empirically (log showed the engine internally
    # targeting ~0.976-0.983 during stabilization while the CSV column read a flat 0.0). Setting
    # "Precision" alone did NOT fix it -- Precision is only honored when "Type" is explicitly set
    # to something other than the default SystemFormatting (confirmed via DecimalFormatData's
    # proto comment: "SystemFormatting = Not provided, let the system do what it wants").
    {
        "Category": "Physiology",
        "PropertyName": "OxygenSaturation",
        "DecimalFormat": {"Type": "FixedMantissa", "Precision": 3},
    },
    {"Category": "Physiology", "PropertyName": "CardiacOutput"},
    {"Category": "Physiology", "PropertyName": "HeartStrokeVolume"},
    {"Category": "Physiology", "PropertyName": "RespirationRate"},
]

STABILIZATION_S = 60
# Exercise intensity above ~0.5 destabilizes the engine at these patient baselines -- same
# constraint the prototype's src/generator.py already found necessary (its `exercise_severity`
# cap). Kept as a named constant here rather than a repeated magic number.
MAX_EXERCISE_INTENSITY = 0.5


def _scalar_unsigned(value: float) -> dict:
    return {"ScalarUnsigned": {"Value": value}}


def _cardiovascular_modification_action(modifiers: dict, extra: dict) -> dict:
    fields = {
        "StrokeVolumeMultiplier": _scalar_unsigned(modifiers["stroke_volume_multiplier"]),
        "SystemicResistanceMultiplier": _scalar_unsigned(modifiers["systemic_resistance_multiplier"]),
        "SystemicComplianceMultiplier": _scalar_unsigned(modifiers["systemic_compliance_multiplier"]),
    }
    fields.update({k: _scalar_unsigned(v) for k, v in extra.items()})
    # Every patient action must be wrapped in "PatientAction" at the AnyAction list-item level --
    # confirmed against the prototype's working src/generator.py and by hitting the actual
    # protobuf JSON parse error ("no such field: 'CardiovascularMechanicsModification'") when this
    # wrapper was missing.
    #
    # "Incremental": true is required, not optional, here: with it left at the (default) false,
    # Pulse silently triggers an internal restabilization after applying the modifiers, which
    # consumes real simulated time beyond what our AnyAction/AdvanceTime durations account for.
    # Pulse then hard-fails its OWN internal check ("Simulation time does not equal expected end
    # time") and exits 1 -- confirmed empirically: a "deconditioning" run requested 660s total but
    # actually ran to 1260s before erroring out. Incremental=true skips that implicit restabilize.
    return {
        "PatientAction": {
            "CardiovascularMechanicsModification": {"Modifiers": fields, "Incremental": True}
        }
    }


def _exercise_action(intensity: float) -> dict:
    intensity = max(0.1, min(intensity, MAX_EXERCISE_INTENSITY))
    return {"PatientAction": {"Exercise": {"Intensity": {"Scalar0To1": {"Value": round(intensity, 3)}}}}}


def _scenario_actions(scenario_type: str, severity: float, modifiers: dict) -> list[dict]:
    """Returns the list of (non-AdvanceTime) actions for a scenario type, plus any extra
    CardiovascularMechanicsModification multipliers layered on top of the EF-driven base."""
    if scenario_type == "stable":
        return []

    if scenario_type == "fluid_overload":
        # Congestive picture: venous compliance drops (less able to buffer volume), on top of
        # the EF-driven stroke volume / systemic resistance changes.
        extra = {"VenousComplianceMultiplier": max(0.5, 1.0 - 0.4 * severity)}
        return [_cardiovascular_modification_action(modifiers, extra)]

    if scenario_type == "cardiac_stress":
        extra = {"HeartRateMultiplier": 1.0 + 0.3 * severity}
        return [
            _cardiovascular_modification_action(modifiers, extra),
            _exercise_action(severity),
        ]

    if scenario_type == "deconditioning":
        # Deliberately NO Exercise action here: deconditioning represents a *chronic* reduced
        # exercise reserve/baseline fitness state, not an acute exertion event -- adding Exercise
        # made this scenario physiologically indistinguishable from cardiac_stress in validation
        # (both drove HR to 150-164 and MAP down ~30 points). Reserve capacity reduction is
        # represented via the mild resistance/compliance modifiers alone, dialed further down
        # from the EF-driven base since deconditioning is meant to be the mildest scenario.
        extra = {
            "SystemicResistanceMultiplier": max(0.85, 1.0 - 0.1 * severity),
            "SystemicComplianceMultiplier": max(0.85, 1.0 - 0.1 * severity),
        }
        return [_cardiovascular_modification_action(modifiers, extra)]

    if scenario_type == "acute_deterioration":
        # Combines fluid_overload's venous congestion with cardiac_stress's tachycardia, at
        # higher magnitude -- the most aggressive of the 5 scenarios by design.
        extra = {
            "VenousComplianceMultiplier": max(0.4, 1.0 - 0.5 * severity),
            "HeartRateMultiplier": 1.0 + 0.4 * severity,
        }
        return [
            _cardiovascular_modification_action(modifiers, extra),
            _exercise_action(severity * 0.6),
        ]

    raise ValueError(f"unknown scenario_type: {scenario_type}")


def build_scenario_file(
    patient_json_path: str,
    scenario_type: str,
    severity: float,
    ejection_fraction_pct: float,
    duration_min: float = 10.0,
) -> dict:
    severity = max(0.0, min(severity, 1.0))
    modifiers = ef_to_cardiovascular_modifiers(ejection_fraction_pct, severity)

    # "Conditions" (ConditionListData) is a message with one repeated field, "AnyCondition" --
    # protobuf JSON still needs the object wrapper naming that field, a bare array isn't valid
    # (confirmed empirically: "unexpected character: '['; expected '{'"). Each entry is then
    # wrapped in "PatientCondition" (AnyConditionData's oneof, per Engine.proto), same
    # oneof-wrapping pattern as actions.
    conditions = []
    if modifiers["apply_systolic_dysfunction_condition"]:
        conditions.append({"PatientCondition": {"ChronicVentricularSystolicDysfunction": {}}})

    patient_configuration = {"PatientFile": patient_json_path}
    if conditions:
        patient_configuration["Conditions"] = {"AnyCondition": conditions}

    actions = _scenario_actions(scenario_type, severity, modifiers)

    return {
        "PatientConfiguration": patient_configuration,
        "DataRequestManager": {"DataRequest": DATA_REQUESTS},
        "AnyAction": [
            {"AdvanceTime": {"Time": {"ScalarTime": {"Value": STABILIZATION_S, "Unit": "s"}}}},
            *actions,
            {"AdvanceTime": {"Time": {"ScalarTime": {"Value": duration_min, "Unit": "min"}}}},
        ],
    }
