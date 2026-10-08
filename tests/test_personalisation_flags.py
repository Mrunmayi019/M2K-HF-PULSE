"""ENABLE_BCG_MODIFIERS / ENABLE_HR_BASELINE (feature/wire-research-features, section B): on, off,
out of range, in both pipeline modes. Pulse and the models are mocked; what is checked is what
would have been handed to Pulse (the patient file and the scenario actions), what is stored, and
the caveat."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from conftest import FakeContinuousPulse, classifier, create_patient, fake_pulse_df, fill_window, sync
from src.patient_builder import personalisation, scenario_file
from src.patient_builder import patient_file as pf
from src.patient_builder.personalisation import (
    HR_BASELINE_BPM_RANGE, IJ_AMPLITUDE_RANGE, JK_AMPLITUDE_RANGE, RJ_INTERVAL_MS_RANGE,
)

# Subject 14's own values: inside every range, and they produce non-trivial modifiers against the
# default (subject 102) reference.
BCG = {"rj_interval_ms": 233.0, "ij_amplitude": 1.172, "jk_amplitude": 1.496}
SUBJECT14_MODIFIERS = pf.bcg_to_cardiovascular_modifiers(233.0, 1.172, 1.496)
REPORT = {"ejection_fraction_pct": 35, "nt_probnp_pg_ml": 1500, **BCG, "hr_baseline_bpm": 77}


def _fresh_run(client, pid, scenario="fluid_overload", severity=0.3):
    real_patient, real_scenario = pf.build_patient_file, scenario_file.build_scenario_file
    with patch("src.api.services._load_scenario_classifier_models", return_value=classifier(scenario, severity)), \
         patch("src.pulse_runner.runner.run_pulse", return_value=fake_pulse_df()), \
         patch("src.api.services.build_patient_file", wraps=real_patient) as bpf, \
         patch("src.api.services.build_scenario_file", wraps=real_scenario) as bsf:
        fill_window(client, pid)
    return bpf.call_args, bsf.call_args


# ---- input validation (both flags' fields, independent of whether the flags are on) ----

class TestValidation:
    @pytest.mark.parametrize("field,rng", [
        ("rj_interval_ms", RJ_INTERVAL_MS_RANGE),
        ("ij_amplitude", IJ_AMPLITUDE_RANGE),
        ("jk_amplitude", JK_AMPLITUDE_RANGE),
    ])
    def test_bcg_out_of_range_rejected(self, research_api, field, rng):
        client, _ = research_api
        pid = create_patient(client)
        for bad in (rng[0] - 0.001, rng[1] + 0.001):
            r = client.post(f"/patients/{pid}/clinical-report", json={**BCG, field: bad})
            assert r.status_code == 422, (field, bad)
        for ok in rng:
            assert client.post(f"/patients/{pid}/clinical-report", json={**BCG, field: ok}).status_code == 201

    def test_hr_baseline_out_of_range_rejected(self, research_api):
        client, _ = research_api
        pid = create_patient(client)
        lo, hi = HR_BASELINE_BPM_RANGE
        assert (lo, hi) == (77.0, 115.0)  # subject 14's and subject 102's clinical-sheet HR
        for bad in (lo - 1, hi + 1, 50, 140):
            assert client.post(f"/patients/{pid}/clinical-report", json={"hr_baseline_bpm": bad}).status_code == 422
        for ok in (lo, 90, hi):
            assert client.post(f"/patients/{pid}/clinical-report", json={"hr_baseline_bpm": ok}).status_code == 201

    def test_partial_bcg_rejected(self, research_api):
        client, _ = research_api
        pid = create_patient(client)
        r = client.post(f"/patients/{pid}/clinical-report", json={"rj_interval_ms": 200.0})
        assert r.status_code == 422
        assert "must be given together" in r.text

    def test_ranges_are_the_two_subjects_values(self):
        # subject 14 (233.0, 1.172, 1.496) and subject 102 (175.0, 1.061, 1.162), per
        # scripts/bcg_hr_baseline_experiment.py -- not widened, not rounded.
        assert RJ_INTERVAL_MS_RANGE == (175.0, 233.0)
        assert IJ_AMPLITUDE_RANGE == (1.061, 1.172)
        assert JK_AMPLITUDE_RANGE == (1.162, 1.496)

    def test_new_fields_round_trip_and_are_absent_when_not_given(self, research_api):
        client, _ = research_api
        pid = create_patient(client)
        with_fields = client.post(f"/patients/{pid}/clinical-report", json=REPORT).json()
        assert {k: with_fields[k] for k in (*BCG, "hr_baseline_bpm")} == {**BCG, "hr_baseline_bpm": 77}
        without = client.post(f"/patients/{pid}/clinical-report", json={"ejection_fraction_pct": 50}).json()
        assert not set(BCG) & set(without) and "hr_baseline_bpm" not in without


# ---- flags off: stored, never used ----

class TestFlagsOff:
    def test_fields_stored_but_nothing_reaches_pulse(self, research_api):
        client, _ = research_api
        pid = create_patient(client)
        client.post(f"/patients/{pid}/clinical-report", json=REPORT)
        patient_call, scenario_call = _fresh_run(client, pid)
        assert patient_call.kwargs.get("hr_baseline_bpm") is None
        assert scenario_call.kwargs.get("extra_modifiers") is None
        a = client.get(f"/patients/{pid}/status").json()["latest_assessment"]
        assert "personalisation" not in a
        assert "Experimental personalisation" not in a["risk_caveats"]

    def test_continuous_flags_off_passes_no_extra_modifiers(self, research_api, flags_off):
        flags_off.setenv("PIPELINE_MODE", "continuous")
        client, _ = research_api
        pid = create_patient(client)
        client.post(f"/patients/{pid}/clinical-report", json=REPORT)
        pulse = FakeContinuousPulse()
        with patch("src.api.continuous_state_pipeline._load_scenario_classifier_models", return_value=classifier()), \
             patch("src.pulse_runner.runner.run_pulse", return_value=fake_pulse_df()), \
             patch("src.api.continuous_state_pipeline.build_patient_file", wraps=pf.build_patient_file) as bpf:
            for p in pulse.patches():
                p.start()
            try:
                fill_window(client, pid)
                sync(client, pid, 21)
            finally:
                patch.stopall()
        assert all("extra_modifiers" not in kw for _, kw in pulse.calls)
        assert bpf.call_args.kwargs.get("hr_baseline_bpm") is None


# ---- flags on ----

class TestFreshModeOn:
    def test_bcg_and_hr_reach_pulse_and_are_recorded_with_caveat(self, research_api, flags_off):
        flags_off.setenv("ENABLE_BCG_MODIFIERS", "1")
        flags_off.setenv("ENABLE_HR_BASELINE", "1")
        client, _ = research_api
        pid = create_patient(client)
        client.post(f"/patients/{pid}/clinical-report", json=REPORT)
        patient_call, scenario_call = _fresh_run(client, pid, "fluid_overload", 0.3)

        assert patient_call.kwargs["hr_baseline_bpm"] == 77
        assert scenario_call.kwargs["extra_modifiers"] == SUBJECT14_MODIFIERS
        # the BCG values override fluid_overload's own VenousComplianceMultiplier in the action
        built = scenario_file.build_scenario_file(**scenario_call.kwargs)
        mods = built["AnyAction"][1]["PatientAction"]["CardiovascularMechanicsModification"]["Modifiers"]
        assert mods["VenousComplianceMultiplier"]["ScalarUnsigned"]["Value"] == SUBJECT14_MODIFIERS["VenousComplianceMultiplier"]

        a = client.get(f"/patients/{pid}/status").json()["latest_assessment"]
        rec = a["personalisation"]
        assert rec["bcg"]["applied"] is True and rec["bcg"]["modifiers"] == SUBJECT14_MODIFIERS
        assert rec["hr_baseline"] == {"requested_bpm": 77, "simulated_bpm": 77, "applied": True}
        assert rec["projection_personalised"] is False
        assert "Experimental personalisation applied (BCG compliance modifiers and resting heart-rate baseline)" in a["risk_caveats"]
        assert "2 subjects from one dataset" in a["risk_caveats"]
        assert "specific to that dataset" in a["risk_caveats"]

    def test_hr_above_pulse_max_is_simulated_at_110_and_recorded(self, research_api, flags_off):
        flags_off.setenv("ENABLE_HR_BASELINE", "1")
        client, _ = research_api
        pid = create_patient(client)
        client.post(f"/patients/{pid}/clinical-report", json={"hr_baseline_bpm": 115})
        patient_call, _ = _fresh_run(client, pid)
        assert pf.build_patient_file(*patient_call.args, **patient_call.kwargs)["HeartRateBaseline"]["ScalarFrequency"]["Value"] == 110
        rec = client.get(f"/patients/{pid}/status").json()["latest_assessment"]["personalisation"]
        assert rec["hr_baseline"]["requested_bpm"] == 115 and rec["hr_baseline"]["simulated_bpm"] == 110

    def test_bcg_on_a_stable_day_is_recorded_as_not_applied_and_has_no_caveat(self, research_api, flags_off):
        flags_off.setenv("ENABLE_BCG_MODIFIERS", "1")
        client, _ = research_api
        pid = create_patient(client)
        client.post(f"/patients/{pid}/clinical-report", json=BCG)
        _fresh_run(client, pid, "stable", 0.05)
        a = client.get(f"/patients/{pid}/status").json()["latest_assessment"]
        assert a["personalisation"]["bcg"]["applied"] is False
        assert "stable scenario" in a["personalisation"]["bcg"]["note"]
        assert "Experimental personalisation" not in a["risk_caveats"]

    def test_flag_on_without_inputs_changes_nothing(self, research_api, flags_off):
        flags_off.setenv("ENABLE_BCG_MODIFIERS", "1")
        flags_off.setenv("ENABLE_HR_BASELINE", "1")
        client, _ = research_api
        pid = create_patient(client)
        client.post(f"/patients/{pid}/clinical-report", json={"ejection_fraction_pct": 35})
        patient_call, scenario_call = _fresh_run(client, pid)
        assert patient_call.kwargs.get("hr_baseline_bpm") is None
        assert scenario_call.kwargs.get("extra_modifiers") is None
        assert "personalisation" not in client.get(f"/patients/{pid}/status").json()["latest_assessment"]


class TestContinuousModeOn:
    def test_bcg_reissued_every_day_hr_only_on_initial_run(self, research_api, flags_off):
        flags_off.setenv("PIPELINE_MODE", "continuous")
        flags_off.setenv("ENABLE_BCG_MODIFIERS", "1")
        flags_off.setenv("ENABLE_HR_BASELINE", "1")
        client, _ = research_api
        pid = create_patient(client)
        client.post(f"/patients/{pid}/clinical-report", json=REPORT)
        pulse = FakeContinuousPulse()
        with patch("src.api.continuous_state_pipeline._load_scenario_classifier_models", return_value=classifier("stable", 0.1)), \
             patch("src.pulse_runner.runner.run_pulse", return_value=fake_pulse_df()), \
             patch("src.api.continuous_state_pipeline.build_patient_file", wraps=pf.build_patient_file) as bpf:
            for p in pulse.patches():
                p.start()
            try:
                fill_window(client, pid)
                sync(client, pid, 21)
                # a later report with a different HR can't reach the running state
                client.post(f"/patients/{pid}/clinical-report", json={**REPORT, "hr_baseline_bpm": 90})
                sync(client, pid, 22)
            finally:
                patch.stopall()

        assert bpf.call_count == 1 and bpf.call_args.kwargs["hr_baseline_bpm"] == 77
        assert [kw["extra_modifiers"] for _, kw in pulse.calls] == [SUBJECT14_MODIFIERS] * 3
        hist = client.get(f"/patients/{pid}/history").json()["assessments"]
        assert all(a["personalisation"]["bcg"]["applied"] for a in hist)  # incl. stable days
        assert hist[-1]["personalisation"]["hr_baseline"]["requested_bpm"] == 77
        assert "needs a twin reset" in hist[-1]["personalisation"]["hr_baseline"]["note"]
        assert all("Experimental personalisation" in a["risk_caveats"] for a in hist)

    def test_build_scenario_with_extra_modifiers_none_is_unchanged(self):
        from src.pulse_runner.cli_state_scenario import build_initial_scenario, build_resume_scenario

        a = build_initial_scenario("p.json", 45, 0.3, 60, 600, "out.json")
        b = build_initial_scenario("p.json", 45, 0.3, 60, 600, "out.json", extra_modifiers=None)
        assert a == b
        c = build_resume_scenario("in.json", 45, 0.3, 600, "cardiac_stress", "out.json")
        d = build_resume_scenario("in.json", 45, 0.3, 600, "cardiac_stress", "out.json", extra_modifiers=None)
        assert c == d
        e = build_resume_scenario("in.json", 45, 0.3, 600, "stable", "out.json", extra_modifiers=SUBJECT14_MODIFIERS)
        mods = e["Scenario"]["AnyAction"][0]["PatientAction"]["CardiovascularMechanicsModification"]["Modifiers"]
        assert mods["VenousComplianceMultiplier"]["ScalarUnsigned"]["Value"] == SUBJECT14_MODIFIERS["VenousComplianceMultiplier"]


def test_caveat_helper_only_fires_when_something_was_applied():
    assert personalisation.personalisation_caveat(None) is None
    assert personalisation.personalisation_caveat({"bcg": {"applied": False}}) is None
    assert "resting heart-rate baseline" in personalisation.personalisation_caveat({"hr_baseline": {"applied": True}})
