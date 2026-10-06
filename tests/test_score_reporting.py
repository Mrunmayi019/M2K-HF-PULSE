"""Tests for src/analytics/score_reporting.py -- pure Python, no Docker/DB required.

Run from repo root: pytest tests/test_score_reporting.py -v
"""
import pytest

from src.analytics.score_reporting import (
    CONFIDENCE_BY_STATUS,
    C3_STREAK_THRESHOLD_DAYS,
    ENTER_N,
    ENTER_THRESHOLD,
    EXIT_N,
    EXIT_THRESHOLD,
    MIN_CONFIDENCE_FOR_ALERT,
    SCENARIO_TYPE_PERSISTENCE_N,
    THRESHOLD_CLINICALLY_VALIDATED,
    AlertAssessmentView,
    alert_decision,
    build_score_report,
    compute_baseline_high_streak,
    confidence_score,
    decide_alert,
    determine_simulation_status,
    hysteresis_alert_states,
    scenario_type_persistence,
    score_provenance,
    severity_band,
)
from src.data_synthesis.generate_patients import STABLE_SEVERITY_CAP


class TestScoreProvenance:
    def test_both_present_is_not_fused(self):
        result = score_provenance(classifier_severity=0.72, pulse_risk_score=0.55)
        assert result == {
            "classifier_severity": 0.72,
            "pulse_risk_score": 0.55,
            "source": "not_fused",
        }

    def test_classifier_only(self):
        result = score_provenance(classifier_severity=0.72, pulse_risk_score=None)
        assert result["source"] == "classifier_only"
        assert result["classifier_severity"] == 0.72
        assert result["pulse_risk_score"] is None

    def test_pulse_only(self):
        result = score_provenance(classifier_severity=None, pulse_risk_score=0.55)
        assert result["source"] == "pulse_only"
        assert result["pulse_risk_score"] == 0.55
        assert result["classifier_severity"] is None

    def test_both_none_raises(self):
        with pytest.raises(ValueError):
            score_provenance(classifier_severity=None, pulse_risk_score=None)

    def test_never_returns_a_combined_or_averaged_value(self):
        # The whole point: no key in the result is a fusion of the two inputs.
        result = score_provenance(classifier_severity=0.72, pulse_risk_score=0.28)
        allowed_keys = {"classifier_severity", "pulse_risk_score", "source"}
        assert set(result.keys()) == allowed_keys
        assert result["classifier_severity"] == 0.72  # untouched, not averaged with 0.28
        assert result["pulse_risk_score"] == 0.28  # untouched, not averaged with 0.72


class TestSeverityBand:
    def test_within_stable_range_at_zero(self):
        assert severity_band(0.0) == "within_stable_range"

    def test_within_stable_range_at_the_cap_itself(self):
        assert severity_band(STABLE_SEVERITY_CAP) == "within_stable_range"

    def test_exceeds_stable_range_just_above_the_cap(self):
        assert severity_band(STABLE_SEVERITY_CAP + 0.001) == "exceeds_stable_range"

    def test_exceeds_stable_range_at_high_severity(self):
        assert severity_band(0.9) == "exceeds_stable_range"

    def test_none_in_none_out(self):
        assert severity_band(None) is None

    def test_never_uses_the_borrowed_065_threshold(self):
        # Regression guard for the exact mistake this module exists to avoid: 0.65
        # (risk_score.py's MODERATE_HIGH_BOUNDARY) must never appear as a severity_band boundary.
        # A severity of 0.5 is well below 0.65 but well above STABLE_SEVERITY_CAP (0.15) -- if
        # this function ever started using 0.65 as an implicit cutoff, 0.5 would misleadingly
        # stay in a "not yet elevated" state. It must not.
        assert severity_band(0.5) == "exceeds_stable_range"
        assert severity_band(0.64) == "exceeds_stable_range"


class TestDetermineSimulationStatus:
    def test_not_run_when_pulse_never_attempted(self):
        assert determine_simulation_status("acute_deterioration", 0.7, pulse_attempted=False, pulse_succeeded=False) == "not_run"

    def test_unstable_when_pulse_failed_outside_crash_zone(self):
        # A failure is "unstable" regardless of whether it was inside the known crash zone --
        # any Pulse failure means there's no reliable risk_score.
        assert determine_simulation_status("acute_deterioration", 0.2, pulse_attempted=True, pulse_succeeded=False) == "unstable"

    def test_unstable_when_succeeded_but_inside_crash_zone(self):
        # The "lucky success" case -- succeeded, but still flagged, per is_known_unstable_configuration().
        assert determine_simulation_status("acute_deterioration", 0.7, pulse_attempted=True, pulse_succeeded=True) == "unstable"

    def test_valid_when_succeeded_outside_crash_zone(self):
        assert determine_simulation_status("acute_deterioration", 0.3, pulse_attempted=True, pulse_succeeded=True) == "valid"

    def test_valid_for_scenario_types_not_characterized_by_the_crash_check(self):
        # fluid_overload isn't audited by is_known_unstable_configuration() -- a successful run
        # there is "valid", not "unstable", since nothing flags it.
        assert determine_simulation_status("fluid_overload", 0.7, pulse_attempted=True, pulse_succeeded=True) == "valid"


class TestConfidenceScore:
    def test_valid_has_highest_confidence(self):
        assert confidence_score("valid") > confidence_score("not_run") > confidence_score("unstable")

    def test_matches_the_documented_table(self):
        for status, value in CONFIDENCE_BY_STATUS.items():
            assert confidence_score(status) == value

    def test_all_confidence_values_are_valid_probabilities(self):
        for value in CONFIDENCE_BY_STATUS.values():
            assert 0.0 <= value <= 1.0


class TestAlertDecision:
    def test_unstable_with_high_severity_falls_back_to_classifier_alert(self):
        # The crash zone is only reachable because the classifier already said "severe" --
        # an unstable simulation must not silence the alert for the sickest patients. Holds
        # even at the (low) "unstable" confidence, which is below MIN_CONFIDENCE_FOR_ALERT.
        assert alert_decision(0.7, confidence=CONFIDENCE_BY_STATUS["unstable"], simulation_status="unstable") == "alert"
        assert alert_decision(0.95, confidence=0.9, simulation_status="unstable") == "alert"

    def test_unstable_with_low_severity_is_indeterminate(self):
        # An unstable run can't confirm a low severity either -- no confident "no_alert".
        assert alert_decision(0.05, confidence=0.9, simulation_status="unstable") == "indeterminate"

    def test_unstable_with_none_severity_is_indeterminate(self):
        assert alert_decision(None, confidence=0.9, simulation_status="unstable") == "indeterminate"

    def test_none_severity_is_indeterminate(self):
        assert alert_decision(None, confidence=0.9, simulation_status="valid") == "indeterminate"

    def test_low_severity_with_high_confidence_is_no_alert(self):
        assert alert_decision(0.05, confidence=0.9, simulation_status="valid") == "no_alert"

    def test_high_severity_with_sufficient_confidence_is_alert(self):
        assert alert_decision(0.9, confidence=MIN_CONFIDENCE_FOR_ALERT, simulation_status="valid") == "alert"

    def test_high_severity_with_insufficient_confidence_is_no_alert(self):
        assert alert_decision(0.9, confidence=MIN_CONFIDENCE_FOR_ALERT - 0.01, simulation_status="not_run") == "no_alert"

    def test_never_derives_from_065(self):
        # Regression guard: 0.5 severity is above STABLE_SEVERITY_CAP but well below 0.65 -- if
        # alert_decision() ever silently adopted risk_score's 0.65 boundary, this would wrongly
        # stay "no_alert".
        assert alert_decision(0.5, confidence=0.9, simulation_status="valid") == "alert"


class TestBuildScoreReport:
    def test_extends_score_provenance_not_a_parallel_structure(self):
        report = build_score_report(
            classifier_severity=0.7, pulse_risk_score=0.55, scenario_type="acute_deterioration",
            pulse_attempted=True, pulse_succeeded=True,
        )
        # Every score_provenance() key is still present, unchanged.
        provenance = score_provenance(0.7, 0.55)
        for key, value in provenance.items():
            assert report[key] == value
        # Plus the Sprint 2 additions.
        assert set(report.keys()) >= {"severity_score", "severity_band", "alert", "confidence", "simulation_status"}
        assert report["severity_score"] == 0.7

    def test_full_shape_for_a_successful_valid_run(self):
        report = build_score_report(0.3, 0.2, "acute_deterioration", pulse_attempted=True, pulse_succeeded=True)
        assert report["simulation_status"] == "valid"
        assert report["severity_band"] == "exceeds_stable_range"
        assert report["confidence"] == CONFIDENCE_BY_STATUS["valid"]

    def test_full_shape_for_a_crash_zone_run(self):
        report = build_score_report(0.7, 0.6, "acute_deterioration", pulse_attempted=True, pulse_succeeded=True)
        assert report["simulation_status"] == "unstable"
        assert report["alert"] == "alert"
        assert report["alert_basis"] == "classifier_only"
        assert report["confidence"] == CONFIDENCE_BY_STATUS["unstable"]

    def test_failed_pulse_run_with_high_severity_still_alerts_classifier_only(self):
        report = build_score_report(0.7, None, "acute_deterioration", pulse_attempted=True, pulse_succeeded=False)
        assert report["simulation_status"] == "unstable"
        assert report["alert"] == "alert"
        assert report["alert_basis"] == "classifier_only"

    def test_alert_basis_reflects_simulation_status(self):
        valid = build_score_report(0.3, 0.2, "acute_deterioration", pulse_attempted=True, pulse_succeeded=True)
        not_run = build_score_report(0.3, None, "acute_deterioration", pulse_attempted=False, pulse_succeeded=False)
        assert valid["alert_basis"] == "classifier_and_simulation"
        assert not_run["alert_basis"] == "classifier_only"

    def test_threshold_clinically_validated_is_always_present_and_false(self):
        # Sprint 2.5 task 5: an explicit, always-present field, not left to be inferred from
        # docstrings. Checked across several different report shapes -- always False, never
        # conditionally True regardless of simulation_status/confidence/alert.
        for kwargs in [
            dict(classifier_severity=0.3, pulse_risk_score=0.2, scenario_type="acute_deterioration", pulse_attempted=True, pulse_succeeded=True),
            dict(classifier_severity=0.7, pulse_risk_score=0.6, scenario_type="acute_deterioration", pulse_attempted=True, pulse_succeeded=True),
            dict(classifier_severity=0.9, pulse_risk_score=None, scenario_type="acute_deterioration", pulse_attempted=False, pulse_succeeded=False),
        ]:
            report = build_score_report(**kwargs)
            assert "threshold_clinically_validated" in report
            assert report["threshold_clinically_validated"] is False
        assert THRESHOLD_CLINICALLY_VALIDATED is False


class TestHysteresisAlertStates:
    """Structure tests -- see TestHysteresisOnStressTestData below for the retroactive
    application to subject 14/102's actual 21-day trends."""

    def test_stays_no_alert_below_threshold(self):
        states = hysteresis_alert_states([0.05] * 10)
        assert all(s == "no_alert" for s in states)

    def test_stays_alert_once_entered_and_sustained(self):
        states = hysteresis_alert_states([0.9] * 10)
        assert states[0] == "no_alert"  # day 1 alone never qualifies (ENTER_N defaults to 2)
        assert all(s == "alert" for s in states[ENTER_N - 1 :])

    def test_single_day_spike_does_not_trigger_alert(self):
        # One day above threshold, surrounded by low days -- ENTER_N=2 by default means a lone
        # spike must not flip the state.
        severities = [0.05, 0.05, 0.9, 0.05, 0.05]
        states = hysteresis_alert_states(severities)
        assert all(s == "no_alert" for s in states)

    def test_single_day_dip_does_not_exit_alert(self):
        # Once in "alert", one low day (below EXIT_THRESHOLD) surrounded by high days must not
        # flip back to "no_alert" with EXIT_N=2.
        severities = [0.9, 0.9, 0.9, 0.05, 0.9, 0.9]
        states = hysteresis_alert_states(severities)
        assert states[3] == "alert"  # the lone dip day stays "alert"

    def test_none_values_are_gaps_not_disqualifying(self):
        severities = [0.9, 0.9, None, 0.9, 0.9]
        states = hysteresis_alert_states(severities)
        assert states[2] == states[1]  # a gap holds the current state, doesn't reset streaks

    def test_custom_thresholds_and_counts_are_honored(self):
        states = hysteresis_alert_states([0.5, 0.5, 0.5], enter_threshold=0.4, enter_n=1)
        assert states[0] == "alert"  # enter_n=1 -> qualifies immediately

    def test_genuine_sustained_recovery_clears_alert_state(self):
        # Positive-case complement to test_single_day_dip_does_not_exit_alert above: a
        # SUSTAINED improvement (not a transient one-day dip) must actually clear "alert", not be
        # suppressed by the same deadband that (correctly) ignores a single noisy low day.
        severities = [0.9, 0.9, 0.9, 0.05, 0.05, 0.05, 0.05, 0.05]
        states = hysteresis_alert_states(severities)
        assert states[2] == "alert"  # entered by day 3 (2 consecutive >= threshold)
        assert states[3] == "alert"  # day 4: only 1 consecutive low day so far -- EXIT_N=2 not yet met
        assert states[4] == "no_alert"  # day 5: 2nd consecutive low day -- genuinely exits
        assert all(s == "no_alert" for s in states[4:])  # stays cleared for the rest of the recovery

    def test_recovery_then_relapse_re_enters_alert(self):
        # A full round-trip: enter -> genuinely exit on sustained recovery -> genuinely re-enter
        # on a later sustained relapse. Confirms the mechanism isn't a one-way latch.
        severities = [0.9, 0.9, 0.05, 0.05, 0.05, 0.9, 0.9, 0.9]
        states = hysteresis_alert_states(severities)
        assert states[1] == "alert"
        assert states[3] == "no_alert"  # cleared after 2 consecutive low days (index 2,3)
        assert states[6] == "alert"  # re-entered after 2 consecutive high days (index 5,6)


class TestHysteresisOnStressTestData:
    """Retroactive application to the real synthetic-deterioration-stress-test trajectories
    (docs/synthetic_deterioration_stress_test.md) -- reports the result either way, not massaged
    to look like a win. Severities are the fixed-seed, reproducible values from that document's
    Sec 3 tables (subject14_hr_baseline seed=1400, subject102 seed=1020), days 6-20."""

    SUBJECT_14_SEVERITIES = [
        0.3695, 0.3942, 0.4561, 0.3422, 0.4245, 0.5027, 0.5419, 0.5751,
        0.5842, 0.6131, 0.6346, 0.7340, 0.7775, 0.8294, 0.8661,
    ]  # days 6-20

    SUBJECT_102_SEVERITIES = [
        0.2547, 0.3162, 0.3476, 0.3948, 0.4131, 0.5004, 0.5709, 0.5786,
        0.6132, 0.6014, 0.6756, 0.7353, 0.7860, 0.8099, 0.8783,
    ]  # days 6-20

    def test_subject14_alert_state_at_default_stable_severity_cap_threshold(self):
        states = hysteresis_alert_states(self.SUBJECT_14_SEVERITIES)
        # Documented finding: severity clears ENTER_THRESHOLD (STABLE_SEVERITY_CAP=0.15) on the
        # very first day tested (0.3695 >> 0.15) and never approaches it again (min subsequent
        # value is the day-9 dip at 0.3422, still >> 0.15) -- so hysteresis at this specific,
        # non-arbitrary reference threshold has NO suppression effect on the documented
        # non-monotonic dips for this data: entry happens almost immediately regardless, and no
        # dip ever comes close to threatening an exit. Reported as found, not massaged.
        assert states[0] == "no_alert"  # day 6 alone (ENTER_N=2)
        assert states[1] == "alert"  # day 7 -- 2nd consecutive qualifying day
        assert all(s == "alert" for s in states[1:])  # never exits for the rest of the trajectory

    def test_subject102_alert_state_at_default_stable_severity_cap_threshold(self):
        states = hysteresis_alert_states(self.SUBJECT_102_SEVERITIES)
        assert states[1] == "alert"
        assert all(s == "alert" for s in states[1:])  # same finding: no suppression effect here either

    def test_hysteresis_mechanism_does_suppress_a_dip_near_an_illustrative_threshold(self):
        # The finding above is about THIS data relative to STABLE_SEVERITY_CAP specifically, not
        # a claim the hysteresis mechanism itself is broken. Demonstrated here with an
        # ILLUSTRATIVE threshold placed so the trajectory actually enters "alert" BEFORE the
        # day-9 dip (days 6-7, 0.3695/0.3942, are the 2 consecutive qualifying days) and the dip
        # itself (0.3422) sits below the illustrative exit line -- NOT proposed as a real/
        # validated threshold, purely to confirm the mechanism suppresses a transient dip when a
        # threshold happens to be near the data, unlike a naive per-day alert_decision() would.
        illustrative_enter, illustrative_exit = 0.36, 0.35
        states = hysteresis_alert_states(
            self.SUBJECT_14_SEVERITIES, enter_threshold=illustrative_enter, exit_threshold=illustrative_exit
        )
        assert states[1] == "alert"  # entered at day 7 (2nd consecutive day >= 0.36)
        # Day index 3 is the day-9 dip (0.3422 < illustrative_exit=0.35) -- a naive single-day
        # threshold check would drop out of alert there; EXIT_N=2 requires a SECOND consecutive
        # qualifying day, and day 10 (0.4245) doesn't qualify, so hysteresis holds through it.
        assert self.SUBJECT_14_SEVERITIES[3] < illustrative_exit  # confirms the dip really is below exit
        assert states[3] == "alert"  # ... but hysteresis keeps it "alert" through the single-day dip

    def test_scenario_type_misclassification_is_out_of_scope_for_this_mechanism(self):
        # Documents a real scope boundary, not a bug: subject 14's day 6-10 scenario_type
        # misclassification ("fluid_overload" instead of "acute_deterioration",
        # docs/synthetic_deterioration_stress_test.md Sec 3) is a categorical-field error.
        # hysteresis_alert_states() operates on severity -> alert state only; it has no mechanism
        # to correct or suppress a wrong scenario_type, and was never designed to. A SEPARATE
        # mechanism (scenario_type_persistence(), below) now exists for exactly that categorical
        # case -- see TestScenarioTypePersistence.
        states = hysteresis_alert_states(self.SUBJECT_14_SEVERITIES)
        assert isinstance(states[0], str)  # sanity: this function only ever returns alert labels,
        # never a scenario_type -- confirming the two are, correctly, never conflated here.


class TestScenarioTypePersistence:
    """Sprint 2.5: root-caused before building this (see score_reporting.py's own module comment
    for the full investigation, or docs/methodology.md Sec 8) -- confirmed NOT a feature-
    extraction bug, NOT a scenario-mapping bug, NOT a fixed-threshold artifact. Real cause:
    acute_deterioration's frac**2 trend-acceleration curve keeps early-window deltas small and
    proportionally closer to a mild fluid_overload profile, at genuinely close-to-fairly-confident
    probability margins (0.047-0.240 across the 5 misclassified days)."""

    # Real subject 14 sequence, days 6-20 (docs/synthetic_deterioration_stress_test.md Sec 3).
    SUBJECT_14_RAW_SCENARIO_TYPES = ["fluid_overload"] * 5 + ["acute_deterioration"] * 10

    # Constructed genuine, PERMANENT change -- NOT from either real subject's data, so N isn't
    # being tuned to fit only what's already been observed. Deliberately longer (15 days) than
    # every N tested below, so a large N can't trivially "pass" by never running long enough to
    # matter.
    GENUINE_PERMANENT_CHANGE = ["stable"] * 10 + ["acute_deterioration"] * 15

    def test_default_n_suppresses_the_real_misclassification(self):
        confirmed = scenario_type_persistence(self.SUBJECT_14_RAW_SCENARIO_TYPES)
        assert "fluid_overload" not in confirmed  # never confirmed -- the 5-day streak never reaches N=6

    def test_default_n_still_confirms_the_constructed_genuine_change(self):
        confirmed = scenario_type_persistence(self.GENUINE_PERMANENT_CHANGE)
        assert "acute_deterioration" in confirmed
        # Confirmed with the structurally-expected N-1-day lag after the real onset (index 10).
        first_confirmed_at = confirmed.index("acute_deterioration")
        assert first_confirmed_at == 10 + SCENARIO_TYPE_PERSISTENCE_N - 1

    def test_n_equal_to_the_streak_length_fails_to_suppress_it(self):
        # The empirical boundary: N must EXCEED the spurious streak length, not just match it.
        # N=5 on a 5-day streak confirms the wrong value on exactly the last day of the streak.
        confirmed = scenario_type_persistence(self.SUBJECT_14_RAW_SCENARIO_TYPES, n=5)
        assert "fluid_overload" in confirmed

    def test_n_sweep_documents_the_suppression_vs_lag_tradeoff(self):
        # N=4,5 confirm the wrong value; N=6+ don't -- but every increase in N also delays the
        # constructed genuine change's confirmation by exactly one more day. Both sides of the
        # tradeoff checked together, not just the suppression side in isolation.
        for n in (4, 5, 6, 7, 8, 10):
            wrong_confirmed = "fluid_overload" in scenario_type_persistence(self.SUBJECT_14_RAW_SCENARIO_TYPES, n=n)
            genuine = scenario_type_persistence(self.GENUINE_PERMANENT_CHANGE, n=n)
            genuine_confirmed_at = genuine.index("acute_deterioration") if "acute_deterioration" in genuine else None

            if n <= 5:
                assert wrong_confirmed is True
            else:
                assert wrong_confirmed is False
            # Genuine change is always eventually confirmed (15-day run exceeds every n tested),
            # always with exactly an n-1 day lag from its real onset at index 10.
            assert genuine_confirmed_at == 10 + n - 1

    def test_before_any_streak_reaches_n_the_type_is_unconfirmed_not_guessed(self):
        # Days 0-4 of the real sequence (4 fluid_overload days, one short of N=6) must report
        # None, not a guess in either direction -- "not enough evidence yet" is a real, distinct
        # state, not silently defaulted to the eventual correct answer.
        confirmed = scenario_type_persistence(self.SUBJECT_14_RAW_SCENARIO_TYPES[:4])
        assert all(c is None for c in confirmed)

    def test_none_values_break_the_streak(self):
        # Unlike hysteresis_alert_states()'s severity gaps, a missing categorical prediction
        # cannot be assumed to agree with anything -- it must reset progress toward confirmation.
        sequence = ["fluid_overload"] * 5 + [None] + ["fluid_overload"] * 5
        confirmed = scenario_type_persistence(sequence, n=6)
        assert confirmed[10] is None  # the restarted streak (5 days post-gap) hasn't reached 6 yet

    def test_a_single_stable_value_throughout_confirms_immediately_at_n(self):
        confirmed = scenario_type_persistence(["stable"] * 8, n=6)
        assert confirmed[4] is None
        assert confirmed[5] == "stable"
        assert all(c == "stable" for c in confirmed[5:])


# ---------------------------------------------------------------------------------------------
# decide_alert() -- fix/unified-alert-decision, 2026-10-03. ONE function, single source of truth
# for ALERT/WATCH/NONE; see its own docstring for the "ML-severity alert" vs. "risk-scorer alert"
# background and exactly how callers derive `simulation_status` for it.
# ---------------------------------------------------------------------------------------------
class TestDecideAlertRiskScorerPath:
    def test_high_bucket_no_streak_is_alert(self):
        view = AlertAssessmentView(severity=0.2, risk_score=0.9, risk_bucket="HIGH",
                                    dominant_mechanism="acute", baseline_high_streak_days=1,
                                    instability_seen_in_streak=False)
        report = decide_alert(view, "valid")
        assert report.level == "ALERT"
        assert report.source == "risk_scorer"

    def test_moderate_bucket_is_watch(self):
        view = AlertAssessmentView(severity=0.2, risk_score=0.5, risk_bucket="MODERATE",
                                    dominant_mechanism="acute")
        report = decide_alert(view, "valid")
        assert report.level == "WATCH"
        assert report.source == "moderate"

    def test_low_bucket_is_none(self):
        view = AlertAssessmentView(severity=0.05, risk_score=0.1, risk_bucket="LOW",
                                    dominant_mechanism="acute")
        report = decide_alert(view, "valid")
        assert report.level == "NONE"

    def test_moderate_never_none_even_at_zero(self):
        # MODERATE is WATCH regardless of streak state -- C3 only ever touches HIGH.
        view = AlertAssessmentView(severity=0.2, risk_score=0.35, risk_bucket="MODERATE",
                                    dominant_mechanism="baseline", baseline_high_streak_days=99,
                                    instability_seen_in_streak=False)
        assert decide_alert(view, "valid").level == "WATCH"


class TestDecideAlertC3Downgrade:
    """The exact rule already selected and evaluated (dev seeds 42-44, held-out seeds 45-47,
    and the original fluid_overload validation dataset) in
    results/scenario_tests/alert_fix_plan.md / alert_fix_results.md / alert_fix_results_heldout.md
    on feature/scenario-testing -- reproduced here as the live decision, not re-derived."""

    def test_short_baseline_high_streak_is_still_alert(self):
        for streak in (1, 2, C3_STREAK_THRESHOLD_DAYS):  # not yet "more than" the threshold
            view = AlertAssessmentView(severity=0.2, risk_score=0.9, risk_bucket="HIGH",
                                        dominant_mechanism="baseline",
                                        baseline_high_streak_days=streak,
                                        instability_seen_in_streak=False)
            report = decide_alert(view, "valid")
            assert report.level == "ALERT", f"streak={streak} should still be ALERT"
            assert report.source == "risk_scorer"

    def test_long_baseline_only_high_streak_downgrades_to_watch_never_none(self):
        view = AlertAssessmentView(severity=0.2, risk_score=0.9, risk_bucket="HIGH",
                                    dominant_mechanism="baseline",
                                    baseline_high_streak_days=C3_STREAK_THRESHOLD_DAYS + 1,
                                    instability_seen_in_streak=False)
        report = decide_alert(view, "valid")
        assert report.level == "WATCH"  # NEVER "NONE" -- C3 only ever downgrades, never silences
        assert report.source == "c3_downgraded"

    def test_instability_seen_in_streak_blocks_the_downgrade(self):
        # The exact mechanism that keeps C3 safe for genuine fluid_overload detections
        # (docs/c3_fluid_overload_blindspot_check.md): once instability_flag==1 is seen anywhere
        # in the streak, the guard never fires, no matter how long the streak runs after that.
        view = AlertAssessmentView(severity=0.2, risk_score=1.0, risk_bucket="HIGH",
                                    dominant_mechanism="baseline",
                                    baseline_high_streak_days=50,
                                    instability_seen_in_streak=True)
        report = decide_alert(view, "valid")
        assert report.level == "ALERT"
        assert report.source == "risk_scorer"

    def test_synthetic_fluid_overload_like_case_never_reaches_none(self):
        """A synthetic multi-day trajectory shaped like P04/P08's diagnosed mechanism
        (scorer_diagnosis.md): risk_bucket=="HIGH", dominant_mechanism=="baseline", no
        instability_flag ever, sustained for many days. Must never read as NONE at any point --
        only ALERT (days 1..3) then WATCH (day 4 onward), per the pre-registered rule."""
        prev_streak, prev_instability = None, None
        levels = []
        for day in range(1, 11):
            streak, instability = compute_baseline_high_streak(
                previous_streak_days=prev_streak, previous_instability_seen=prev_instability,
                risk_bucket="HIGH", dominant_mechanism="baseline", instability_flag=0,
            )
            view = AlertAssessmentView(severity=0.2, risk_score=0.8, risk_bucket="HIGH",
                                        dominant_mechanism="baseline",
                                        baseline_high_streak_days=streak,
                                        instability_seen_in_streak=instability)
            report = decide_alert(view, "valid")
            levels.append(report.level)
            prev_streak, prev_instability = streak, instability

        assert "NONE" not in levels
        assert levels[:C3_STREAK_THRESHOLD_DAYS] == ["ALERT"] * C3_STREAK_THRESHOLD_DAYS
        assert all(level == "WATCH" for level in levels[C3_STREAK_THRESHOLD_DAYS:])


class TestDecideAlertFallbackPaths:
    def test_failed_run_high_severity_is_alert_failed_fallback(self):
        view = AlertAssessmentView(severity=0.8)
        report = decide_alert(view, "unstable_failed")
        assert report.level == "ALERT"
        assert report.source == "failed_fallback"

    def test_failed_run_low_severity_is_none_not_indeterminate(self):
        # The old alert_decision() returned "indeterminate" here, which nothing downstream ever
        # surfaced as an alert anyway -- decide_alert() maps it to NONE, not a new silent state.
        view = AlertAssessmentView(severity=0.05)
        report = decide_alert(view, "unstable_failed")
        assert report.level == "NONE"
        assert report.source == "failed_fallback"

    def test_unstable_completed_high_severity_is_alert(self):
        # Pulse succeeded but landed in the documented crash zone -- same classifier-only
        # fallback as a failure, UNCHANGED threshold, different source label.
        view = AlertAssessmentView(severity=0.8)
        report = decide_alert(view, "unstable_completed")
        assert report.level == "ALERT"
        assert report.source == "unstable_completed"

    def test_not_run_is_none(self):
        view = AlertAssessmentView(severity=None)
        assert decide_alert(view, "not_run").level == "NONE"


class TestComputeBaselineHighStreak:
    def test_first_ever_day_high_baseline_starts_streak_at_one(self):
        streak, instability = compute_baseline_high_streak(
            previous_streak_days=None, previous_instability_seen=None,
            risk_bucket="HIGH", dominant_mechanism="baseline", instability_flag=0,
        )
        assert streak == 1
        assert instability is False

    def test_streak_increments_across_days(self):
        streak, instability = compute_baseline_high_streak(
            previous_streak_days=3, previous_instability_seen=False,
            risk_bucket="HIGH", dominant_mechanism="baseline", instability_flag=0,
        )
        assert streak == 4

    def test_acute_dominant_day_resets_streak(self):
        streak, instability = compute_baseline_high_streak(
            previous_streak_days=10, previous_instability_seen=False,
            risk_bucket="HIGH", dominant_mechanism="acute", instability_flag=0,
        )
        assert streak == 0
        assert instability is False

    def test_dropping_below_high_resets_streak(self):
        streak, _ = compute_baseline_high_streak(
            previous_streak_days=10, previous_instability_seen=False,
            risk_bucket="MODERATE", dominant_mechanism="baseline", instability_flag=0,
        )
        assert streak == 0

    def test_instability_seen_persists_across_days_within_streak(self):
        # Day N: instability_flag fires once. Day N+1 onward (still baseline-HIGH): the guard
        # must remember it saw instability earlier in this same streak, per
        # alert_fix_results.md's confirmed P04 mechanism (not reassumed here, reproduced).
        streak1, instability1 = compute_baseline_high_streak(
            previous_streak_days=2, previous_instability_seen=False,
            risk_bucket="HIGH", dominant_mechanism="baseline", instability_flag=1,
        )
        assert instability1 is True
        streak2, instability2 = compute_baseline_high_streak(
            previous_streak_days=streak1, previous_instability_seen=instability1,
            risk_bucket="HIGH", dominant_mechanism="baseline", instability_flag=0,
        )
        assert streak2 == streak1 + 1
        assert instability2 is True  # still remembered, even though today's own flag is 0


class TestBothSignals:
    """ml_severity_alert() / signals_disagree() (fix/alert-both-signals)."""

    def test_ml_alert_uses_existing_cap_no_new_threshold(self):
        from src.analytics.score_reporting import STABLE_SEVERITY_CAP, ml_severity_alert
        assert ml_severity_alert(STABLE_SEVERITY_CAP)["level"] == "NONE"  # <= cap is within stable range
        assert ml_severity_alert(STABLE_SEVERITY_CAP + 1e-6)["level"] == "ALERT"
        assert ml_severity_alert(0.6)["threshold"] == STABLE_SEVERITY_CAP
        assert ml_severity_alert(None) is None

    @pytest.mark.parametrize("twin,ml,expected", [
        ("NONE", "ALERT", True),
        ("ALERT", "NONE", True),
        ("WATCH", "NONE", True),
        ("WATCH", "ALERT", False),
        ("ALERT", "ALERT", False),
        ("NONE", "NONE", False),
    ])
    def test_disagree_truth_table(self, twin, ml, expected):
        from src.analytics.score_reporting import signals_disagree
        assert signals_disagree(twin, {"level": ml}) is expected

    def test_disagree_none_when_a_signal_is_missing(self):
        from src.analytics.score_reporting import signals_disagree
        assert signals_disagree(None, {"level": "ALERT"}) is None
        assert signals_disagree("NONE", None) is None
