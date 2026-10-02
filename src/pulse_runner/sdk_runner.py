"""Continuous-state-sync feature (feature/continuous-state-sync branch, 2026-08-30): Pulse
SDK-based save/resume.

**SUPERSEDED (2026-09-01) -- DO NOT USE. Kept only as the documented evidence trail for a real,
100%-reproducible native bug.** `PulseEngine.initialize_engine()` (called from this module's
`run_initial()`) segfaults every time, confirmed via gdb, natively inside Pulse's own engine code:

    SESubstanceManager::AddActiveSubstance()
      <- SubstanceManager::InitializeSubstances()
      <- Controller::Initialize()
      <- Controller::InitializeEngine()

with ZERO scikit-learn/joblib involvement -- reproduced calling nothing but `PulseEngine()` +
`initialize_engine()` in an otherwise-empty fresh process, 3/3 runs. This DISPROVES this module's
own earlier "reissue on resume, verified bit-for-bit" conclusion as evidence that the SDK path
itself is safe: those earlier tests just didn't hit this crash by luck of thread scheduling, the
same class of false-negative already flagged (see docs/continuous_state_sync_status.md's Step 4
isolation-test log, tests #10-13) for a different, now-superseded theory (a joblib fork colliding
with Pulse's native threads). `PulseScenarioDriver` (the CLI/scenario-JSON path) runs the identical
patient/scenario computation cleanly every time -- see `src/pulse_runner/cli_state_scenario.py`
and `src/pulse_runner/cli_state_runner.py`, which reimplement this module's save/resume/reissue
logic on that path instead, and are what `src/api/continuous_state_pipeline.py` actually uses now.

The CardiovascularMechanicsModification-reissue-on-resume finding below (module docstring
"CRITICAL, empirically-verified finding") is NOT invalidated by the above -- that's a property of
how Pulse's serialized engine state itself behaves on resume, independent of SDK vs. CLI, and was
re-verified at the CLI layer (see docs/continuous_state_sync_status.md).

Everything below this point describes the abandoned SDK approach, left unmodified as-is.

---

This is a deliberately separate module from `src/pulse_runner/runner.py` -- that module backs the
current, working, from-scratch-every-time pipeline (`src/api/services.py`) and must not change
until this feature is reviewed and approved. Nothing in `services.py` imports from here yet.

Why the SDK instead of `PulseScenarioDriver` (see docs/pulse_state_serialization_investigation.md):
the CLI driver's own internal consistency check compares final sim time only against the
scenario's own AdvanceTime sum, not a resumed state's already-elapsed clock, so it exits 1 with a
false-positive "Simulation time does not equal expected end time" error on every resumed run --
which would look like a crash to runner.py's existing FATAL_LOG_MARKERS/exit-code detection. The
SDK has no such check.

CRITICAL, empirically-verified finding this module's resume logic depends on
(docs/pulse_state_serialization_investigation.md's root-cause investigation): serialized engine
state does NOT keep a `CardiovascularMechanicsModification` action "in force" across a resume --
the instantaneous circuit values at save time are captured exactly, but without re-issuing the
action fresh immediately after loading (before advancing time), the resumed trajectory drifts
away from what an uninterrupted continuous run would produce (~3-7% over 90s in testing).
Re-issuing it fresh, using the current ejection_fraction_pct/severity, produced a bit-for-bit exact
match against a continuous run. Every resume in this module MUST reissue before advancing.
"""
from __future__ import annotations

import pathlib
import tempfile

from pulse.engine.PulseEngine import PulseEngine, eModelType
from pulse.cdm.patient import SEPatientConfiguration
from pulse.cdm.engine import SEDataRequestManager, SEDataRequest
from pulse.cdm.patient_actions import SECardiovascularMechanicsModification, SEExercise
from pulse.cdm.scalars import FrequencyUnit, PressureUnit, VolumePerTimeUnit

from src.patient_builder.patient_file import ef_to_cardiovascular_modifiers
from src.patient_builder.scenario_file import MAX_EXERCISE_INTENSITY

PULSE_DATA_ROOT = "/pulse/bin/"


class PulseSdkError(Exception):
    pass


def default_data_request_mgr() -> SEDataRequestManager:
    """The 4 physiology properties src/analytics/simulation_features.py's analyze_simulation()
    and src/analytics/risk_score.py actually consume (HeartRate, MeanArterialPressure,
    CardiacOutput, HeartStrokeVolume) -- kept minimal and consistent with those modules so a
    future integration doesn't need a second request-manager definition."""
    drm = SEDataRequestManager()
    drm.set_data_requests([
        SEDataRequest.create_physiology_request("HeartRate", unit=FrequencyUnit.Per_min),
        SEDataRequest.create_physiology_request("MeanArterialPressure", unit=PressureUnit.mmHg),
        SEDataRequest.create_physiology_request("CardiacOutput", unit=VolumePerTimeUnit.L_Per_min),
        SEDataRequest.create_physiology_request("HeartStrokeVolume"),
    ])
    return drm


def build_cardiovascular_modification_action(
    ejection_fraction_pct: float, severity: float
) -> SECardiovascularMechanicsModification:
    """Mirrors src/patient_builder/scenario_file.py's _cardiovascular_modification_action() core
    fields (the 3 shared by every scenario type) via the real SDK action class, using the same
    unmodified ef_to_cardiovascular_modifiers() the rest of the pipeline already relies on.

    Does not include scenario-specific "extra" modifiers (VenousComplianceMultiplier,
    HeartRateMultiplier, Exercise) that src/patient_builder/scenario_file.py layers on for
    fluid_overload/cardiac_stress/acute_deterioration -- those represent an acute scenario
    encounter, not the chronic/continuous state this module tracks. Scoped deliberately narrow
    for this feature's first implementation; not a decision about whether to extend it later.
    """
    modifiers = ef_to_cardiovascular_modifiers(ejection_fraction_pct, severity)
    action = SECardiovascularMechanicsModification()
    action.set_incremental(True)  # required -- see scenario_file.py's own comment on why
    mods = action.get_modifiers()
    mods.get_stroke_volume_multiplier().set_value(modifiers["stroke_volume_multiplier"])
    mods.get_systemic_resistance_multiplier().set_value(modifiers["systemic_resistance_multiplier"])
    mods.get_systemic_compliance_multiplier().set_value(modifiers["systemic_compliance_multiplier"])
    return action


# Scenario types whose src/patient_builder/scenario_file.py._scenario_actions() layers an
# Exercise action on top of the core CardiovascularMechanicsModification -- representing an acute
# exertion event for that day's encounter, distinct from the chronic/continuous multiplier.
# fluid_overload/deconditioning/stable have no such extra action (see that module's docstrings for
# why -- e.g. deconditioning deliberately omits Exercise to represent chronic reduced reserve, not
# an acute event).
EXERCISE_SCENARIO_INTENSITY_FACTOR = {
    "cardiac_stress": 1.0,
    "acute_deterioration": 0.6,
}


def build_exercise_action(scenario_type: str, severity: float) -> SEExercise | None:
    """Today's fresh, scenario-specific acute action -- mirrors
    src/patient_builder/scenario_file.py's _exercise_action()/_scenario_actions() exactly (same
    MAX_EXERCISE_INTENSITY clamp and the same 0.6x factor for acute_deterioration), via the SDK.
    Returns None for scenario types that don't get an Exercise action (stable/fluid_overload/
    deconditioning) -- caller should skip applying it in that case.
    """
    factor = EXERCISE_SCENARIO_INTENSITY_FACTOR.get(scenario_type)
    if factor is None:
        return None
    intensity = max(0.1, min(severity * factor, MAX_EXERCISE_INTENSITY))
    action = SEExercise()
    action.get_intensity().set_value(round(intensity, 3))
    return action


def snapshot(engine: PulseEngine) -> dict:
    """Simulation time is always index 0 (see PulseEngine.py); the rest follow
    default_data_request_mgr()'s order."""
    d = engine.pull_data()
    return {"simulation_time_s": d[0], "heart_rate": d[1], "map": d[2], "cardiac_output": d[3],
            "stroke_volume": d[4]}


def run_initial(
    patient_json_path: str,
    ejection_fraction_pct: float,
    severity: float,
    stabilization_s: float,
    duration_s: float,
) -> tuple[str, dict]:
    """First-ever run for a patient: fresh engine, stabilize, apply the initial
    CardiovascularMechanicsModification, advance, serialize. Returns (state_json_str, snapshot).
    """
    engine = PulseEngine(eModelType.HumanAdultWholeBody, PULSE_DATA_ROOT)
    pc = SEPatientConfiguration()
    pc.set_patient_file(patient_json_path)
    if not engine.initialize_engine(pc, default_data_request_mgr()):
        raise PulseSdkError(f"initialize_engine failed for {patient_json_path}")

    engine.advance_time_s(stabilization_s)
    engine.process_action(
        build_cardiovascular_modification_action(ejection_fraction_pct, severity)
    )
    engine.advance_time_s(duration_s)

    state_json = _serialize_to_string(engine)
    return state_json, snapshot(engine)


def resume_and_advance(
    state_json: str,
    ejection_fraction_pct: float,
    severity: float,
    duration_s: float,
    scenario_type: str | None = None,
) -> tuple[str, dict]:
    """Loads a previously-saved state, IMMEDIATELY reissues CardiovascularMechanicsModification
    with the given (possibly updated) ejection_fraction_pct/severity -- required, see module
    docstring, verified bit-for-bit exact -- then applies today's fresh scenario-specific action
    (Exercise, if `scenario_type` calls for one; see build_exercise_action()) representing the new
    wearable data's classified encounter, then advances. Returns (new_state_json_str, snapshot).

    Order (reissue CardiovascularMechanicsModification, then Exercise, then advance) is a
    deliberate choice -- restore the structural/chronic baseline before applying an acute
    stressor on top of it -- not empirically re-verified against reversing the order; both actions
    are applied before any time advances either way.
    """
    engine = PulseEngine(eModelType.HumanAdultWholeBody, PULSE_DATA_ROOT)
    if not _deserialize_from_string(engine, state_json):
        raise PulseSdkError("serialize_from_file failed loading saved state")

    engine.process_action(
        build_cardiovascular_modification_action(ejection_fraction_pct, severity)
    )
    if scenario_type is not None:
        exercise_action = build_exercise_action(scenario_type, severity)
        if exercise_action is not None:
            engine.process_action(exercise_action)
    engine.advance_time_s(duration_s)

    new_state_json = _serialize_to_string(engine)
    return new_state_json, snapshot(engine)


def _serialize_to_string(engine: PulseEngine) -> str:
    """Round-trips through a temp file rather than PulseEngine.serialize_to_string() --
    that convenience wrapper has a real bug (found during this feature's investigation): it
    forwards its `format` argument to the low-level binding without converting
    pulse.cdm.engine.eSerializationFormat to PyPulse.serialization_format the way
    serialize_from_string() does, so it always raises TypeError. serialize_to_file()/
    serialize_from_file() (file-based) don't have this bug and are what every verification in
    docs/pulse_state_serialization_investigation.md actually used."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = f.name
    try:
        if not engine.serialize_to_file(tmp_path):
            raise PulseSdkError("serialize_to_file returned False")
        return pathlib.Path(tmp_path).read_text()
    finally:
        pathlib.Path(tmp_path).unlink(missing_ok=True)


def _deserialize_from_string(engine: PulseEngine, state_json: str) -> bool:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        f.write(state_json)
        tmp_path = f.name
    try:
        return engine.serialize_from_file(tmp_path, default_data_request_mgr())
    finally:
        pathlib.Path(tmp_path).unlink(missing_ok=True)
