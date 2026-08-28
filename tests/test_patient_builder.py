"""Unit tests for src/patient_builder/ -- pure Python, no Docker/Pulse required.

Run from repo root: pytest tests/test_patient_builder.py -v
"""
import pytest

from src.data_synthesis.generate_patients import generate_patients
from src.patient_builder.patient_file import (
    HFREF_EF_THRESHOLD_PCT,
    PULSE_MAX_AGE_YR,
    PULSE_MAX_BMI,
    build_patient_file,
    ef_to_cardiovascular_modifiers,
    needs_pulse_capping,
    pulse_eligible_age,
    pulse_eligible_weight_kg,
)
from src.patient_builder.scenario_file import build_scenario_file

SCENARIO_TYPES = ["stable", "fluid_overload", "cardiac_stress", "deconditioning", "acute_deterioration"]


class TestBuildPatientFile:
    def test_required_keys_present(self):
        patient = {"patient_id": "P0001", "sex": "Female", "age": 61.5, "height_cm": 162.0, "weight_kg": 70.0}
        pf = build_patient_file(patient)
        assert pf["Sex"] == "Female"
        assert pf["Age"]["ScalarTime"]["Value"] == 61.5
        assert pf["Age"]["ScalarTime"]["Unit"] == "yr"
        assert pf["Height"]["ScalarLength"]["Value"] == 162.0
        assert pf["Weight"]["ScalarMass"]["Value"] == 70.0

    def test_no_baseline_hr_or_bp_set(self):
        # Pulse auto-computes these from demographics -- we must not override them
        patient = {"patient_id": "P0002", "sex": "Male", "age": 50, "height_cm": 175, "weight_kg": 80}
        pf = build_patient_file(patient)
        assert "HeartRateBaseline" not in pf
        assert "SystolicArterialPressureBaseline" not in pf
        assert "DiastolicArterialPressureBaseline" not in pf

    def test_elderly_patient_age_capped_for_pulse(self):
        # real HF patients are frequently >65 (MIMIC mean 68.7) -- Pulse hard-rejects that, so the
        # patient FILE must be capped even though patients.csv keeps the true age
        patient = {"patient_id": "P0003", "sex": "Female", "age": 91.8, "height_cm": 160, "weight_kg": 65}
        pf = build_patient_file(patient)
        assert pf["Age"]["ScalarTime"]["Value"] == PULSE_MAX_AGE_YR

    def test_high_bmi_patient_weight_capped_for_pulse(self):
        # height 155.3cm + weight 98.2kg = BMI 40.7, well above Pulse's 30.0 ceiling
        patient = {"patient_id": "P0004", "sex": "Female", "age": 40, "height_cm": 155.3, "weight_kg": 98.2}
        pf = build_patient_file(patient)
        capped_weight = pf["Weight"]["ScalarMass"]["Value"]
        capped_bmi = capped_weight / (155.3 / 100) ** 2
        assert capped_bmi <= PULSE_MAX_BMI + 0.01
        assert capped_weight < 98.2


class TestPulseEligibilityCapping:
    def test_age_within_range_unchanged(self):
        assert pulse_eligible_age(45.0) == 45.0

    def test_age_above_max_capped(self):
        assert pulse_eligible_age(91.8) == PULSE_MAX_AGE_YR

    def test_age_below_min_capped(self):
        assert pulse_eligible_age(10.0) == 18.0

    def test_weight_within_bmi_limit_unchanged(self):
        # 70kg at 175cm -> BMI 22.9, well under the cap
        assert pulse_eligible_weight_kg(175.0, 70.0) == 70.0

    def test_weight_above_bmi_limit_capped(self):
        capped = pulse_eligible_weight_kg(155.3, 98.2)
        assert capped < 98.2
        assert capped / (1.553**2) <= PULSE_MAX_BMI + 0.01

    def test_weight_below_bmi_floor_capped(self):
        # 178cm + 40kg -> BMI ~12.6, below Pulse's hard 16.0 floor
        capped = pulse_eligible_weight_kg(178.0, 40.0)
        assert capped > 40.0
        assert capped / (1.78**2) >= 16.0

    def test_needs_pulse_capping_flags_elderly_or_obese(self):
        assert needs_pulse_capping(age_yr=70, height_cm=170, weight_kg=70) is True
        assert needs_pulse_capping(age_yr=40, height_cm=155.3, weight_kg=98.2) is True
        assert needs_pulse_capping(age_yr=40, height_cm=175, weight_kg=75) is False


class TestEfToCardiovascularModifiers:
    def test_condition_boundary_at_ef_40(self):
        assert ef_to_cardiovascular_modifiers(40.0, 0.0)["apply_systolic_dysfunction_condition"] is True
        assert ef_to_cardiovascular_modifiers(40.1, 0.0)["apply_systolic_dysfunction_condition"] is False

    def test_lower_ef_gives_lower_stroke_volume_multiplier_within_preserved_ef_regime(self):
        # comparison must stay within the EF>40 (no-condition) regime -- crossing the boundary
        # isn't comparable since the Condition itself (not the multiplier) carries the EF signal
        # once EF<=40 (see test_condition_severity_zero_has_no_extra_multiplier_cut below)
        mild = ef_to_cardiovascular_modifiers(65.0, 0.0)
        moderate = ef_to_cardiovascular_modifiers(45.0, 0.0)
        assert moderate["stroke_volume_multiplier"] < mild["stroke_volume_multiplier"]

    def test_condition_severity_zero_has_no_extra_multiplier_cut(self):
        # once ChronicVentricularSystolicDysfunction is applied (EF<=40), a zero-severity patient
        # should get NO additional continuous-multiplier cut -- the condition's own fixed 0.27x
        # elastance cut already represents their chronic state. Double-counting this caused a real
        # simulated patient to collapse during Phase 2 validation (see module docstring).
        result = ef_to_cardiovascular_modifiers(25.0, 0.0)
        assert result["apply_systolic_dysfunction_condition"] is True
        assert result["stroke_volume_multiplier"] == 1.0

    def test_higher_severity_gives_lower_stroke_volume_multiplier(self):
        mild = ef_to_cardiovascular_modifiers(55.0, 0.1)
        severe = ef_to_cardiovascular_modifiers(55.0, 0.9)
        assert severe["stroke_volume_multiplier"] < mild["stroke_volume_multiplier"]

    def test_multipliers_never_below_floor(self):
        worst = ef_to_cardiovascular_modifiers(15.0, 1.0)
        assert worst["stroke_volume_multiplier"] >= 0.5
        assert worst["systemic_resistance_multiplier"] >= 0.6

    def test_severity_out_of_range_is_clamped(self):
        # severity isn't clamped inside this function itself (scenario_file.py clamps before
        # calling it) -- but the multiplier floor must still hold even if a caller passes >1
        result = ef_to_cardiovascular_modifiers(55.0, 5.0)
        assert result["stroke_volume_multiplier"] >= 0.5


class TestBuildScenarioFile:
    @pytest.mark.parametrize("scenario_type", SCENARIO_TYPES)
    def test_produces_valid_structure_for_every_scenario(self, scenario_type):
        scenario = build_scenario_file(
            patient_json_path="/workspace/scenarios/patient_test.json",
            scenario_type=scenario_type,
            severity=0.5,
            ejection_fraction_pct=45.0,
        )
        assert scenario["PatientConfiguration"]["PatientFile"] == "/workspace/scenarios/patient_test.json"
        assert "DataRequestManager" in scenario
        assert len(scenario["DataRequestManager"]["DataRequest"]) == 11
        actions = scenario["AnyAction"]
        assert "AdvanceTime" in actions[0]
        assert "AdvanceTime" in actions[-1]

    def test_stable_has_no_extra_actions(self):
        scenario = build_scenario_file("p.json", "stable", 0.1, ejection_fraction_pct=60.0)
        # only the two AdvanceTime bookends, nothing in between
        assert len(scenario["AnyAction"]) == 2

    def test_hfref_ef_adds_condition(self):
        scenario = build_scenario_file("p.json", "fluid_overload", 0.5, ejection_fraction_pct=30.0)
        assert scenario["PatientConfiguration"]["Conditions"] == {
            "AnyCondition": [{"PatientCondition": {"ChronicVentricularSystolicDysfunction": {}}}]
        }

    def test_preserved_ef_has_no_condition(self):
        scenario = build_scenario_file("p.json", "fluid_overload", 0.5, ejection_fraction_pct=60.0)
        assert "Conditions" not in scenario["PatientConfiguration"]

    def test_exercise_intensity_never_exceeds_stability_cap(self):
        scenario = build_scenario_file("p.json", "cardiac_stress", severity=1.0, ejection_fraction_pct=55.0)
        exercise_actions = [
            a["PatientAction"]["Exercise"]["Intensity"]["Scalar0To1"]["Value"]
            for a in scenario["AnyAction"]
            if "PatientAction" in a and "Exercise" in a["PatientAction"]
        ]
        assert exercise_actions  # sanity: make sure we actually found the Exercise action
        assert all(v <= 0.5 for v in exercise_actions)

    def test_actions_are_wrapped_in_patient_action(self):
        # every non-AdvanceTime action must be wrapped in "PatientAction" at the AnyAction
        # list-item level, or Pulse's protobuf JSON parser rejects it outright
        scenario = build_scenario_file("p.json", "acute_deterioration", severity=0.7, ejection_fraction_pct=30.0)
        for action in scenario["AnyAction"]:
            assert "AdvanceTime" in action or "PatientAction" in action

    def test_invalid_scenario_type_raises(self):
        with pytest.raises(ValueError):
            build_scenario_file("p.json", "not_a_real_scenario", 0.5, ejection_fraction_pct=55.0)


def test_builders_work_against_real_generated_patients():
    """End-to-end sanity check using actual Phase 1 synthetic patients, not just hand-built dicts."""
    patients = generate_patients(n=10, seed=1)
    for _, patient in patients.iterrows():
        pf = build_patient_file(patient)
        assert pf["Sex"] in ("Male", "Female")
        scenario = build_scenario_file(
            patient_json_path="patient.json",
            scenario_type=patient["scenario_type"],
            severity=patient["severity"],
            ejection_fraction_pct=patient["ejection_fraction_pct"],
        )
        assert "PatientConfiguration" in scenario
