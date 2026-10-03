"""Continuous-state-sync feature (feature/continuous-state-sync branch): scenario-JSON builders
for the CLI/PulseScenarioDriver-based save/resume mechanism.

Supersedes src/pulse_runner/sdk_runner.py's SDK-based approach -- see that module's docstring for
why: `PulseEngine.initialize_engine()` was found to segfault 100% reproducibly (gdb-confirmed,
native crash inside Pulse's own SESubstanceManager::AddActiveSubstance, with ZERO scikit-learn/
joblib involvement), while PulseScenarioDriver (the CLI/scenario-JSON path this module drives)
runs the identical patient/scenario computation cleanly every time. The earlier "joblib fork vs.
Pulse threads" diagnosis was incomplete -- the real problem was specific to the SDK's engine-init
path, not a process-sharing collision.

Uses `SerializeStateData` (the "SerializeState" action) to save engine state to a file, and
`ScenarioData.StartType`'s `EngineStateFile` field to resume a new driver process directly from a
saved state file -- both confirmed against the real protobuf schema and verified end-to-end in
docs/pulse_state_serialization_investigation.md.

Deliberately reuses src/patient_builder/scenario_file.py's private helpers
(_cardiovascular_modification_action, _exercise_action, DATA_REQUESTS, MAX_EXERCISE_INTENSITY)
rather than re-deriving the same JSON shapes -- this is the single source of truth for what a
Pulse action/data-request looks like as JSON, and must not itself be modified (it backs the
existing, working, from-scratch pipeline in src/api/services.py).
"""
from __future__ import annotations

from src.patient_builder import scenario_file
from src.patient_builder.patient_file import ef_to_cardiovascular_modifiers

# Mirrors sdk_runner.py's EXERCISE_SCENARIO_INTENSITY_FACTOR -- scenario types whose
# src/patient_builder/scenario_file.py._scenario_actions() layers an Exercise action on top of the
# core CardiovascularMechanicsModification, applied here on every resume as "today's fresh
# scenario-specific action" (see src/api/continuous_state_pipeline.py's module docstring).
EXERCISE_SCENARIO_INTENSITY_FACTOR = {
    "cardiac_stress": 1.0,
    "acute_deterioration": 0.6,
}


def _serialize_state_action(filename: str) -> dict:
    """SerializeStateData -- an action, sibling to AdvanceTime, NOT wrapped in "PatientAction".
    Field name confirmed directly against this image's own schema
    (/source/src/schema/pulse/cdm/bind/Actions.proto's `message SerializeStateData { ActionData
    Action = 1; eMode Mode = 2; string Filename = 3; }`) after the field name documented in
    docs/pulse_state_serialization_investigation.md ("Type") turned out to be wrong for 4.3.1 --
    confirmed via the driver's own parse error ("no such field: 'Type'") -- the real field is
    "Mode" (values "Save"/"Load", per eMode)."""
    return {"SerializeState": {"Mode": "Save", "Filename": filename}}


def _core_cardiovascular_modification_action(ejection_fraction_pct: float, severity: float) -> dict:
    """The chronic/continuous multiplier only (no scenario-specific extras) -- mirrors
    sdk_runner.py's build_cardiovascular_modification_action() exactly, via the real JSON-building
    helper scenario_file.py already uses for the working from-scratch pipeline."""
    modifiers = ef_to_cardiovascular_modifiers(ejection_fraction_pct, severity)
    return scenario_file._cardiovascular_modification_action(modifiers, extra={})


def build_exercise_action(scenario_type: str, severity: float) -> dict | None:
    """Returns None for scenario types with no Exercise action (stable/fluid_overload/
    deconditioning) -- caller should skip applying it in that case. Mirrors
    sdk_runner.py's build_exercise_action()."""
    factor = EXERCISE_SCENARIO_INTENSITY_FACTOR.get(scenario_type)
    if factor is None:
        return None
    return scenario_file._exercise_action(severity * factor)


def build_initial_scenario(
    patient_json_path: str,
    ejection_fraction_pct: float,
    severity: float,
    stabilization_s: float,
    duration_s: float,
    state_out_path: str,
) -> dict:
    """First-ever encounter for a patient: fresh PatientConfiguration, stabilize, apply the
    initial CardiovascularMechanicsModification, advance, then SerializeState/Save. No Exercise
    action -- matches sdk_runner.run_initial()'s existing convention (Exercise is only ever applied
    on a resume, driven by that day's freshly-classified scenario_type).
    """
    modifiers = ef_to_cardiovascular_modifiers(ejection_fraction_pct, severity)

    # Same Conditions logic as scenario_file.build_scenario_file() -- ChronicVentricularSystolic-
    # Dysfunction can only be set at initial PatientConfiguration time, never on a resumed run
    # (EngineStateFile has no Conditions field), so it must be decided correctly here, once.
    conditions = []
    if modifiers["apply_systolic_dysfunction_condition"]:
        conditions.append({"PatientCondition": {"ChronicVentricularSystolicDysfunction": {}}})

    patient_configuration = {"PatientFile": patient_json_path}
    if conditions:
        patient_configuration["Conditions"] = {"AnyCondition": conditions}

    return {
        "Scenario": {
            "PatientConfiguration": patient_configuration,
            "DataRequestManager": {"DataRequest": scenario_file.DATA_REQUESTS},
            "AnyAction": [
                {"AdvanceTime": {"Time": {"ScalarTime": {"Value": stabilization_s, "Unit": "s"}}}},
                scenario_file._cardiovascular_modification_action(modifiers, extra={}),
                {"AdvanceTime": {"Time": {"ScalarTime": {"Value": duration_s, "Unit": "s"}}}},
                _serialize_state_action(state_out_path),
            ],
        }
    }


def build_resume_scenario(
    state_in_path: str,
    ejection_fraction_pct: float,
    severity: float,
    duration_s: float,
    scenario_type: str | None,
    state_out_path: str,
) -> dict:
    """Resumes from state_in_path, IMMEDIATELY reissues CardiovascularMechanicsModification with
    the given (possibly updated) ejection_fraction_pct/severity -- required, see
    src/pulse_runner/sdk_runner.py's module docstring for the empirically-verified reissue finding
    (which is a property of the Pulse engine's own state-resume behavior, not the SDK -- re-verified
    at this CLI layer in docs/continuous_state_sync_status.md) -- then applies today's fresh
    scenario-specific action (Exercise, if scenario_type calls for one), then advances, then
    SerializeState/Save. Returns the built scenario dict.
    """
    actions = [_core_cardiovascular_modification_action(ejection_fraction_pct, severity)]
    if scenario_type is not None:
        exercise_action = build_exercise_action(scenario_type, severity)
        if exercise_action is not None:
            actions.append(exercise_action)
    actions.append({"AdvanceTime": {"Time": {"ScalarTime": {"Value": duration_s, "Unit": "s"}}}})
    actions.append(_serialize_state_action(state_out_path))

    return {
        "Scenario": {
            "EngineStateFile": state_in_path,
            "DataRequestManager": {"DataRequest": scenario_file.DATA_REQUESTS},
            "AnyAction": actions,
        }
    }
