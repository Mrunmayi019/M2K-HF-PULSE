"""Score provenance, descriptive severity banding, alert decision, and confidence/simulation-
status reporting -- reporting-layer utilities, not new scoring logic. Sprint 1 (2026-09-10) added
score_provenance()/severity_band() alongside the severity/risk_score scale-mismatch fix (see
docs/methodology.md Sec 8, "severity and risk_score are not on comparable scales"). Sprint 2
(same day) adds the architectural split this module's own name implies: SCORE PRODUCTION
(severity, risk_score -- computed elsewhere, in ML Model 1 and risk_score.py) is now structurally
separate from ALERT DECISION (alert_decision() below) -- project_severity() only ever produces a
number; it never decided alert/no-alert, and neither does anything else that produces a score.

Deliberately does NOT fuse ML Model 1's classifier `severity` and Pulse-derived `risk_score` into
one combined number -- that fusion needs real outcome-calibration data this project does not have
(docs/methodology.md Sec 8's "blocked on data" note). This module keeps the two visible and
separately labeled instead of inventing a combined score. `score_provenance()` names which of the
two produced a given pipeline output; `severity_band()` gives `severity` a descriptive label
without borrowing `risk_score.py`'s `MODERATE_HIGH_BOUNDARY` (0.65) the way an earlier version of
this project's projection code briefly did -- that threshold is calibrated for `risk_score`'s own
scale, not `severity`'s, and applying it to `severity` was exactly the bug this module's sibling
fix (`src/analytics/projection.py`'s `project_severity()`) corrected.

EVERY THRESHOLD-LIKE CONSTANT IN THIS FILE (MIN_CONFIDENCE_FOR_ALERT, CONFIDENCE_BY_STATUS's
values, ENTER_THRESHOLD/EXIT_THRESHOLD/ENTER_N/EXIT_N) IS AN UNVALIDATED PLACEHOLDER, same
category and same discipline as Sprint 1's SD_RATE_TO_SEVERITY_PER_DAY: named, documented, and
explicitly flagged as not derived from real outcome data, not silently presented as validated.
Real calibration for any of these remains blocked on data this project does not have (Sprint 3+5).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from src.data_synthesis.generate_patients import STABLE_SEVERITY_CAP
from src.pulse_runner.runner import is_known_unstable_configuration

ScoreSource = Literal["classifier_only", "pulse_only", "not_fused"]
SimulationStatus = Literal["valid", "unstable", "not_run"]
AlertState = Literal["alert", "no_alert", "indeterminate"]

# fix/unified-alert-decision (2026-10-03): the 4-way status decide_alert() itself consumes.
# Built from determine_simulation_status()'s own 3-way output (reused, not reimplemented) plus
# the one extra bit ("did Pulse actually succeed") every caller already has in scope whenever
# that output is "unstable" -- see decide_alert()'s docstring for exactly how to derive this.
DecideAlertStatus = Literal["not_run", "valid", "unstable_failed", "unstable_completed"]


def score_provenance(
    classifier_severity: Optional[float], pulse_risk_score: Optional[float]
) -> dict:
    """Returns {"classifier_severity": ..., "pulse_risk_score": ..., "source": ...}.

    `source` names which component(s) actually produced the values present, so a caller (or a
    future reader of stored data) can never mistake "only the classifier ran" for "both ran and
    were combined" -- they are never combined here at all.
      - "classifier_only": ML Model 1 produced a severity, Pulse either hasn't run yet or failed
        (`src/api/services.py`'s `SimulationRun.status="failed"` case -- no `RiskAssessment` row
        is created there today, so this state currently isn't surfaced through the API's response
        schema yet; the field exists for when/if that gap is closed).
      - "pulse_only": a risk_score exists with no classifier severity -- not a state the current
        pipeline produces (severity is always computed before Pulse runs), included for
        completeness/future use, not because it's reachable today.
      - "not_fused": both are present -- the current pipeline's normal, only-reachable state once
        a `RiskAssessment` row exists. Explicitly NOT "combined" or "averaged" -- both values are
        exactly what each component independently produced.
    """
    if classifier_severity is None and pulse_risk_score is None:
        raise ValueError("score_provenance() needs at least one of classifier_severity/pulse_risk_score")

    if classifier_severity is not None and pulse_risk_score is not None:
        source: ScoreSource = "not_fused"
    elif classifier_severity is not None:
        source = "classifier_only"
    else:
        source = "pulse_only"

    return {
        "classifier_severity": classifier_severity,
        "pulse_risk_score": pulse_risk_score,
        "source": source,
    }


def severity_band(severity: Optional[float]) -> Optional[str]:
    """Descriptive label for `severity`, explicitly NOT a clinical alert threshold.

    Uses `generate_patients.py`'s `STABLE_SEVERITY_CAP` (0.15). Stated plainly, not left as an
    ambiguous "reference"/"marker": **`STABLE_SEVERITY_CAP` is an ENGINEERING CONSTANT, not a
    clinical threshold** -- a hard-coded property of this project's own synthetic training-data
    generation (`stable` scenario patients are capped at this severity by construction), reused
    here only because it is the one non-arbitrary NUMBER already in this codebase, not because
    0.15 carries any clinical meaning. Validated in `docs/synthetic_deterioration_stress_test.md` as
    "the point a trajectory first clearly exceeds what `stable` looks like in training data."

    Deliberately only two bands. A finer-grained banding (e.g. a third "high" tier) would need
    another cutoff, and no further non-arbitrary reference point currently exists in this
    project's data for one -- adding one would repeat the exact mistake (`risk_score.py`'s
    `MODERATE_HIGH_BOUNDARY=0.65`, calibrated for a different quantity) this module exists to
    avoid. Returns None for severity=None (e.g. before ML Model 1 has run).
    """
    if severity is None:
        return None
    return "within_stable_range" if severity <= STABLE_SEVERITY_CAP else "exceeds_stable_range"


# ---------------------------------------------------------------------------------------------
# Simulation status + confidence, added Sprint 2 (2026-09-10).

def determine_simulation_status(
    scenario_type: Optional[str], severity: Optional[float], pulse_attempted: bool, pulse_succeeded: bool
) -> SimulationStatus:
    """Labels the reliability of the Pulse-derived side of an assessment. Does NOT label
    `severity` itself (the classifier always either has run or hasn't -- that's `source` in
    score_provenance(), not this).

      - "not_run": Pulse has not been invoked yet for this severity (classifier-only state).
      - "unstable": Pulse was invoked and EITHER failed OR landed in/near the documented crash
        zone (`src.pulse_runner.runner.is_known_unstable_configuration()`, reused not
        reimplemented) -- checked regardless of whether the run happened to succeed. A "lucky"
        success inside the crash zone is still not a reliable data point (4/8 failure rate
        documented in docs/synthetic_deterioration_stress_test.md); this function deliberately
        does not let a successful outcome override that.
      - "valid": Pulse ran successfully AND was outside any documented instability zone.
    """
    if not pulse_attempted:
        return "not_run"
    if not pulse_succeeded:
        return "unstable"
    if scenario_type is not None and severity is not None and is_known_unstable_configuration(scenario_type, severity):
        return "unstable"
    return "valid"


# PLACEHOLDER, unvalidated -- see module docstring. Two different things here, not one:
# - The ORDERING (Pulse-confirmed-valid > classifier-only ("not_run") > Pulse-unstable-or-failed)
#   was specified as this sprint's explicit scope.
# - The three specific NUMBERS below (0.3/0.5/0.8) were NOT specified in that scope -- they were
#   chosen during implementation as round placeholders satisfying the ordering above. Not
#   empirically derived, not learned by any model, not specified by the sprint's own scope either.
# No real outcome data exists yet to calibrate either the ordering or the numbers
# (docs/methodology.md Sec 8, blocked on data).
CONFIDENCE_BY_STATUS: dict[SimulationStatus, float] = {
    "unstable": 0.3,  # LOWER than classifier-only -- we specifically know this configuration is suspect
    "not_run": 0.5,  # baseline -- classifier's own opinion only, no independent physiological check
    "valid": 0.8,  # HIGHER than baseline -- independently confirmed by a stable Pulse simulation
}


def confidence_score(simulation_status: SimulationStatus) -> float:
    """Confidence in the severity/risk signal for one assessment, derived purely from
    `simulation_status` via CONFIDENCE_BY_STATUS above. PLACEHOLDER values -- see module
    docstring; flagged, not hidden."""
    return CONFIDENCE_BY_STATUS[simulation_status]


# PLACEHOLDER, unvalidated (see module docstring). Minimum confidence required before
# alert_decision() will commit to "alert" even when severity itself exceeds the stable range --
# an unvalidated engineering choice, same status as everything else in this file.
MIN_CONFIDENCE_FOR_ALERT = 0.5


def alert_decision(severity: Optional[float], confidence: float, simulation_status: SimulationStatus) -> AlertState:
    """Consumes a severity score + confidence + simulation_status and decides alert state --
    architecturally separate from score PRODUCTION (project_severity(), ML Model 1, risk_score.py
    all only ever produce a number; none of them decide alert/no-alert). This is that decision
    point, added Sprint 2 so the split is real, not just documented.

    Returns "alert" | "no_alert" | "indeterminate". PLACEHOLDER logic -- the actual cutoffs used
    here (MIN_CONFIDENCE_FOR_ALERT, severity_band()'s STABLE_SEVERITY_CAP) are unvalidated
    engineering choices, not derived from real outcome data (docs/methodology.md Sec 8). This is
    an architecture change, not a threshold-validation change.

      - severity is None -> "indeterminate" (nothing to decide from).
      - simulation_status == "unstable" AND severity exceeds STABLE_SEVERITY_CAP -> "alert",
        regardless of confidence (classifier fallback). The documented crash zone
        (acute_deterioration, severity 0.6-0.85) is reachable only because the classifier already
        produced a high severity, so going silent there would suppress alerts for exactly the
        sickest patients. The Pulse side is still untrusted -- build_score_report()'s
        `alert_basis` reports "classifier_only" for this case. The crash itself is NOT treated as
        a clinical signal: the alert comes from the classifier's severity, not from the failure.
      - simulation_status == "unstable" otherwise -> "indeterminate". An unstable Pulse run can't
        confirm a low classifier severity either, so no confident "no_alert" is issued.
      - Otherwise: "alert" if severity exceeds STABLE_SEVERITY_CAP (severity_band() ==
        "exceeds_stable_range") AND confidence >= MIN_CONFIDENCE_FOR_ALERT; "no_alert" otherwise.
    """
    if severity is None:
        return "indeterminate"
    if simulation_status == "unstable":
        return "alert" if severity_band(severity) == "exceeds_stable_range" else "indeterminate"
    if severity_band(severity) == "exceeds_stable_range" and confidence >= MIN_CONFIDENCE_FOR_ALERT:
        return "alert"
    return "no_alert"


# Sprint 2.5 (2026-09-10), task 5: an explicit, always-present field on every score/alert output,
# rather than leaving "is any of this clinically validated?" to be inferred from scattered
# docstrings. False today and for the whole foreseeable duration of this project -- every
# threshold this file uses (STABLE_SEVERITY_CAP, MIN_CONFIDENCE_FOR_ALERT, CONFIDENCE_BY_STATUS,
# ENTER/EXIT_THRESHOLD, SCENARIO_TYPE_PERSISTENCE_N) is an engineering placeholder, none derived
# from or checked against real outcome data. Not a per-call computation -- a fixed, honest
# statement of this system's current validation status.
THRESHOLD_CLINICALLY_VALIDATED = False


def build_score_report(
    classifier_severity: Optional[float],
    pulse_risk_score: Optional[float],
    scenario_type: Optional[str],
    pulse_attempted: bool,
    pulse_succeeded: bool,
) -> dict:
    """The full severity/risk reporting object for one assessment. Built BY COMPOSING
    score_provenance(), severity_band(), determine_simulation_status(), confidence_score(), and
    alert_decision() -- an extension of score_provenance()'s output, not a parallel/competing
    structure: every key score_provenance() returns is still present here unchanged.

    Returns {"classifier_severity", "pulse_risk_score", "source" (from score_provenance()),
    "severity_score" (alias of classifier_severity, for response-shape clarity), "severity_band",
    "alert", "alert_basis", "confidence", "simulation_status", "threshold_clinically_validated"
    (always False, see that constant's own comment)}.

    `alert_basis` is "classifier_and_simulation" only when simulation_status == "valid", and
    "classifier_only" otherwise ("not_run" or "unstable") -- so a classifier-fallback alert (see
    alert_decision()) is never mistaken for one a stable Pulse run backed up.
    """
    provenance = score_provenance(classifier_severity, pulse_risk_score)
    simulation_status = determine_simulation_status(
        scenario_type, classifier_severity, pulse_attempted, pulse_succeeded
    )
    confidence = confidence_score(simulation_status)
    band = severity_band(classifier_severity)
    alert = alert_decision(classifier_severity, confidence, simulation_status)

    return {
        **provenance,
        "severity_score": classifier_severity,
        "severity_band": band,
        "alert": alert,
        "alert_basis": "classifier_and_simulation" if simulation_status == "valid" else "classifier_only",
        "confidence": confidence,
        "simulation_status": simulation_status,
        "threshold_clinically_validated": THRESHOLD_CLINICALLY_VALIDATED,
    }


# ---------------------------------------------------------------------------------------------
# Temporal persistence (hysteresis), added Sprint 2 (2026-09-10). Structure only -- the specific
# threshold/persistence-count VALUES below are unvalidated placeholders, same discipline as
# everything else in this file. Purpose: avoid flipping alert state on a single noisy day (the
# non-monotonic severity dips documented in docs/synthetic_deterioration_stress_test.md are the
# motivating real example -- see that document's Sec 3 and this module's own test suite for
# whether this mechanism actually changes anything for that specific data).

# PLACEHOLDER, unvalidated. ENTER uses the same non-arbitrary STABLE_SEVERITY_CAP reference
# point as severity_band()/alert_decision() rather than inventing a new number. EXIT is set
# slightly below ENTER (a deadband) so hovering exactly at the boundary doesn't flap every day --
# the deadband's specific width (20% below ENTER) is itself an unvalidated engineering choice.
ENTER_THRESHOLD = STABLE_SEVERITY_CAP
EXIT_THRESHOLD = STABLE_SEVERITY_CAP * 0.8
ENTER_N = 2  # consecutive days >= ENTER_THRESHOLD required before flipping no_alert -> alert
EXIT_N = 2  # consecutive days < EXIT_THRESHOLD required before flipping alert -> no_alert


def hysteresis_alert_states(
    severities: list[Optional[float]],
    enter_threshold: float = ENTER_THRESHOLD,
    exit_threshold: float = EXIT_THRESHOLD,
    enter_n: int = ENTER_N,
    exit_n: int = EXIT_N,
) -> list[str]:
    """Applies N-consecutive-observations persistence to a day-by-day severity sequence, returning
    a same-length sequence of "alert"/"no_alert" labels (never "indeterminate" -- this function
    takes plain severities, not full assessments; compose with alert_decision()/
    determine_simulation_status() upstream if per-day simulation_status also needs to gate this).

    Starts in "no_alert". Entering "alert" requires `enter_n` consecutive days with
    severity >= `enter_threshold`; once in "alert", returning to "no_alert" requires `exit_n`
    consecutive days with severity < `exit_threshold`. A day with severity=None does not count
    toward either streak (treated as a gap, not a qualifying or disqualifying observation) and
    keeps the current state.

    This is the STRUCTURE only -- `enter_threshold`/`exit_threshold`/`enter_n`/`exit_n`'s defaults
    are unvalidated placeholders (see module docstring), overridable by the caller once real
    calibration data exists.
    """
    states = []
    state = "no_alert"
    enter_streak = 0
    exit_streak = 0

    for severity in severities:
        if severity is None:
            states.append(state)
            continue

        if severity >= enter_threshold:
            enter_streak += 1
        else:
            enter_streak = 0

        if severity < exit_threshold:
            exit_streak += 1
        else:
            exit_streak = 0

        if state == "no_alert" and enter_streak >= enter_n:
            state = "alert"
        elif state == "alert" and exit_streak >= exit_n:
            state = "no_alert"

        states.append(state)

    return states


# ---------------------------------------------------------------------------------------------
# Scenario-type persistence, added Sprint 2.5 (2026-09-10) -- separate from severity's hysteresis
# above, because `scenario_type` is a categorical ML Model 1 output, not a threshold-crossing
# continuous value; a consecutive-agreement requirement on a category is a different mechanism
# from an enter/exit deadband on a number, even though both exist to suppress noisy day-to-day
# flips before they're acted on.
#
# ROOT-CAUSED, not assumed, before this was built (docs/synthetic_deterioration_stress_test.md /
# docs/methodology.md Sec 8 carry the full investigation): subject 14's day 6-10
# `scenario_type="fluid_overload"` (5 consecutive days) before correcting to
# `"acute_deterioration"` at day 11 was checked against the classifier's own predict_proba()
# margins, the raw wearable-trend feature deltas, and SCENARIO_SIGNAL_DELTAS' per-scenario
# profiles on the real subject 14 data in data/synthetic_deterioration_stress_test/. Findings:
# feature extraction was computing exactly the values the trend data implies (no bug there); the
# argmax/scenario-mapping logic correctly picked the highest-probability class each day (no bug
# there either); the actual cause is that acute_deterioration's own trend-generation curve
# accelerates as frac**2 (generate_wearable_trends.py's _trend_curve()) -- deliberately small
# early on -- so early-window HR/weight/SpO2 deltas are proportionally closer to a mild
# fluid_overload profile (weight-dominant) than to acute_deterioration's own (HR/steps/HRV-
# dominant) profile, which hasn't ramped up yet. Margins were real, not razor-thin noise: days
# 6-8/10 favored fluid_overload by 0.15-0.24 probability (a fairly confident, if wrong, call);
# only day 9 was a near-tie (0.047). Subject 102's own day-9 margin (0.020, correctly favoring
# acute_deterioration) confirms this is genuine, patient-specific feature-space overlap at low
# signal magnitude -- not a fixed threshold artifact, not a coding bug.
#
# PLACEHOLDER, unvalidated, but empirically derived from an actual N-sweep (not guessed): tested
# N=4..10 against subject 14's real 5-day fluid_overload streak AND a constructed 15-day genuine,
# permanent stable->acute_deterioration change (long enough to exceed every N tested, so a large N
# can't trivially "pass" by never being long enough to matter). N=5 still confirms the wrong
# fluid_overload streak (5 == 5); N=6 is the minimum that suppresses it (see
# tests/test_score_reporting.py's TestScenarioTypePersistence for the full sweep) while still
# correctly confirming the constructed genuine change, at the structurally unavoidable cost of an
# N-1-day detection lag on every real, permanent change too. The general principle (N must exceed
# the longest observed spurious streak) is sound; N=6 itself rests on a single observed spurious
# streak length (n=1), not a validated bound on how long spurious streaks can get in general --
# real outcome/deployment data would be needed to set this with any real confidence.
SCENARIO_TYPE_PERSISTENCE_N = 6


def scenario_type_persistence(
    scenario_types: list[Optional[str]], n: int = SCENARIO_TYPE_PERSISTENCE_N
) -> list[Optional[str]]:
    """Requires `n` consecutive agreeing days before accepting a `scenario_type` (change OR
    initial confirmation) -- returns a same-length sequence of "confirmed" scenario_types.

    Starts unconfirmed (`None`) until any value streaks for `n` consecutive days, then stays
    confirmed as that value until a DIFFERENT value streaks for `n` consecutive days in turn. A
    day with `scenario_type=None` breaks the current streak (unlike hysteresis_alert_states()'s
    severity gaps) since a missing categorical prediction can't be assumed to agree with anything.

    This is the STRUCTURE only -- `n`'s default is an empirically-derived-but-still-unvalidated
    placeholder (see module comment above), overridable by the caller once real calibration data
    (or a larger sample of observed spurious-streak lengths) exists.
    """
    confirmed = None
    streak_value = None
    streak_len = 0
    out = []

    for value in scenario_types:
        if value is not None and value == streak_value:
            streak_len += 1
        else:
            streak_value = value
            streak_len = 1 if value is not None else 0

        if value is not None and streak_len >= n and confirmed != streak_value:
            confirmed = streak_value

        out.append(confirmed)

    return out


# ---------------------------------------------------------------------------------------------
# Unified alert decision (fix/unified-alert-decision, 2026-10-03).
#
# Background: this codebase had TWO independent "alert" signals before this change.
# (1) alert_decision() above, gated on the ML classifier's own `severity` (STABLE_SEVERITY_CAP,
#     0.15) -- real, reachable backend code (StatusResponse.current_alert), called this project's
#     "ML-severity alert" from here on.
# (2) risk_bucket == "HIGH" (src/analytics/risk_score.py, MODERATE_HIGH_BOUNDARY=0.65), gated on
#     Pulse's own simulated hemodynamics -- called this project's "risk-scorer alert" from here
#     on. Every frontend component that displays risk/alert state reads THIS one; nothing in the
#     frontend ever read (1). Confirmed by a full-repo grep before this change
#     (docs/c3_fluid_overload_blindspot_check.md's companion analysis doc has the detail).
#
# decide_alert() replaces both with ONE decision, built on the risk-scorer alert (since that's
# the one the product actually surfaces), with two additions found necessary by the scenario-test
# post-hoc analysis (results/scenario_tests/alert_fix_plan.md on feature/scenario-testing):
#   - a WATCH tier for risk_bucket=="MODERATE" (previously invisible to any alert signal at all);
#   - the C3 persistence guard, which downgrades (never removes) a HIGH alert that has been
#     driven by baseline_deficit_score alone, with no corroborating instability_flag, for more
#     than 3 consecutive days -- the mechanism diagnosed for a specific false-alarm case
#     (results/scenario_tests/scorer_diagnosis.md) and confirmed, on both dev and held-out seeds
#     and against the original fluid_overload validation dataset, NEVER to suppress a genuine
#     fluid_overload detection (docs/c3_fluid_overload_blindspot_check.md) -- those checks all
#     passed VACUOUSLY (no fluid_overload case in any of the three ever reached HIGH at all); the
#     WATCH tier, not the vacuous C3 check, is what actually protects a future case where one
#     does: C3 can only ever push a HIGH down to WATCH, never down to NONE.
#
# compute_risk_score() itself, its weights, and its LOW/MODERATE/HIGH thresholds are UNCHANGED by
# this -- this is reporting-layer composition, exactly this module's existing charter.

AlertLevel = Literal["ALERT", "WATCH", "NONE"]
AlertSource = Literal["risk_scorer", "c3_downgraded", "failed_fallback", "unstable_completed", "moderate"]

# Not re-derived/re-tuned here -- the exact value already selected and evaluated in
# results/scenario_tests/alert_fix_plan.md / alert_fix_results.md / alert_fix_results_heldout.md
# (both on feature/scenario-testing): "more than 3 consecutive days" of a baseline-only HIGH
# streak before downgrading to WATCH.
C3_STREAK_THRESHOLD_DAYS = 3


@dataclass(frozen=True)
class AlertReport:
    level: AlertLevel
    source: AlertSource


@dataclass(frozen=True)
class AlertAssessmentView:
    """Duck-typed input to decide_alert() -- either a real RiskAssessment ORM row (which already
    has every one of these as a column or property, see src/api/models.py's RiskAssessment) or
    this lightweight stand-in, built by callers for a run that never produced a RiskAssessment at
    all (a failed Pulse run -- src/api/routes.py's _build_status())."""
    severity: Optional[float]
    risk_score: Optional[float] = None
    risk_bucket: Optional[str] = None
    dominant_mechanism: Optional[str] = None
    baseline_high_streak_days: int = 0
    instability_seen_in_streak: bool = False


def decide_alert(assessment, simulation_status: DecideAlertStatus) -> AlertReport:
    """ONE function, single source of truth for ALERT/WATCH/NONE across the API and every
    consumer (routes.py's _build_status(), RiskAssessment.alert, and -- via the API --
    every frontend component; nothing else should decide alert/watch state).

    `assessment` -- a real RiskAssessment row or an AlertAssessmentView, see that class's
    docstring. Only `.severity` is read when `simulation_status` starts with "unstable"; the
    risk-scorer fields are only read for "valid" (a RiskAssessment row always has them; an
    AlertAssessmentView for a failed run correctly leaves them at their None/0/False defaults,
    never consulted on that path).

    `simulation_status` -- NOT determine_simulation_status()'s raw 3-way output. That function's
    "unstable" collapses two different cases (Pulse failed outright vs. Pulse succeeded but
    landed in the documented crash zone) that this function's `source` output must tell apart,
    and only the CALLER knows which one it is (it already has `pulse_succeeded` in scope wherever
    determine_simulation_status() gets called). Callers resolve it like this, reusing that
    function's output rather than reimplementing its logic:

        status = determine_simulation_status(scenario_type, severity, pulse_attempted, pulse_succeeded)
        if status == "unstable":
            status = "unstable_failed" if not pulse_succeeded else "unstable_completed"
        report = decide_alert(assessment, status)

    Decision table:
      - "unstable_failed" / "unstable_completed": existing classifier-only fallback, UNCHANGED
        threshold/logic (alert_decision()'s own unstable branch, STABLE_SEVERITY_CAP) --
        severity > STABLE_SEVERITY_CAP -> ALERT (source matches which case this was); otherwise
        NONE (nothing concerning to flag; this is the old "indeterminate" case, which nothing
        downstream ever surfaced as an alert anyway).
      - "valid" (risk-scorer alert, Pulse ran and wasn't in the crash zone): risk_bucket=="HIGH"
        -> ALERT (source "risk_scorer"), UNLESS the C3 guard fires (baseline_high_streak_days >
        C3_STREAK_THRESHOLD_DAYS and not instability_seen_in_streak) -> WATCH (source
        "c3_downgraded"), never NONE. risk_bucket=="MODERATE" -> WATCH (source "moderate").
        Otherwise ("LOW") -> NONE.
      - "not_run": NONE (nothing to decide from yet) -- not expected to actually reach this
        function in practice (see RiskAssessment.alert's and _build_status()'s own
        preconditions), handled defensively rather than raising.
    """
    if simulation_status in ("unstable_failed", "unstable_completed"):
        source: AlertSource = "failed_fallback" if simulation_status == "unstable_failed" else "unstable_completed"
        if assessment.severity is not None and severity_band(assessment.severity) == "exceeds_stable_range":
            return AlertReport("ALERT", source)
        return AlertReport("NONE", source)

    if simulation_status == "valid":
        if assessment.risk_bucket == "HIGH":
            if (
                assessment.baseline_high_streak_days is not None
                and assessment.baseline_high_streak_days > C3_STREAK_THRESHOLD_DAYS
                and not assessment.instability_seen_in_streak
            ):
                return AlertReport("WATCH", "c3_downgraded")
            return AlertReport("ALERT", "risk_scorer")
        if assessment.risk_bucket == "MODERATE":
            return AlertReport("WATCH", "moderate")
        return AlertReport("NONE", "risk_scorer")

    return AlertReport("NONE", "risk_scorer")  # "not_run" -- nothing to decide from yet


def ml_severity_alert(severity: Optional[float]) -> Optional[dict]:
    """The ML-severity signal, reported ALONGSIDE decide_alert()'s twin-based level rather than
    folded into it (fix/alert-both-signals). No new threshold: this is the existing rule
    severity_band() / alert_decision() already apply -- ML Model 1's severity above
    STABLE_SEVERITY_CAP (0.15, an unvalidated engineering placeholder, docs/data_provenance.md).
    For a valid Pulse run decide_alert() ignores severity entirely, so this is the only place the
    classifier's own opinion still reaches the response. None when there is no severity yet."""
    if severity is None:
        return None
    fires = severity_band(severity) == "exceeds_stable_range"
    return {
        "level": "ALERT" if fires else "NONE",
        "severity": severity,
        "threshold": STABLE_SEVERITY_CAP,
        "source": "ml_severity",
    }


def signals_disagree(twin_level: Optional[str], ml_alert: Optional[dict]) -> Optional[bool]:
    """True when exactly one of the two signals fires. The twin "fires" at ALERT or WATCH (any
    level other than NONE); the ML signal fires at ALERT. None when either signal is missing.

    On a failed or crash-zone Pulse run decide_alert() itself falls back to the same severity rule
    as ml_severity_alert(), so the two can't disagree there -- disagreement only arises when the
    twin produced a valid risk score."""
    if twin_level is None or ml_alert is None:
        return None
    return (twin_level != "NONE") != (ml_alert["level"] == "ALERT")


def compute_baseline_high_streak(
    previous_streak_days: Optional[int],
    previous_instability_seen: Optional[bool],
    risk_bucket: Optional[str],
    dominant_mechanism: Optional[str],
    instability_flag: int,
) -> tuple[int, bool]:
    """C3's persistence bookkeeping, computed incrementally (O(1): reads only the patient's most
    recent prior RiskAssessment, never the full history) at RiskAssessment write-time by
    src/api/services.py and src/api/continuous_state_pipeline.py. Exactly reproduces the offline
    per-day state machine already evaluated in results/scenario_tests/posthoc_analysis.py /
    alert_fix_eval.py (feature/scenario-testing) -- not a new rule, the same one, now computed
    live instead of re-derived from saved CSVs after the fact.

    `previous_streak_days`/`previous_instability_seen` are the prior RiskAssessment's own stored
    values for this patient (None if there is no prior assessment, or it predates this field).
    """
    prev_streak = previous_streak_days or 0
    prev_instability_seen = bool(previous_instability_seen)

    if risk_bucket == "HIGH" and dominant_mechanism == "baseline":
        streak = prev_streak + 1
        instability_seen = prev_instability_seen
    else:
        streak = 0
        instability_seen = False
    if instability_flag:
        instability_seen = True
    return streak, instability_seen


# ---------------------------------------------------------------------------------------------
# Wiring for ENABLE_ALERT_HYSTERESIS and ENABLE_SCENARIO_PERSISTENCE (feature/wire-research-
# features). No new thresholds: hysteresis_alert_states() and scenario_type_persistence() above are
# called with their existing defaults (ENTER/EXIT 0.15/0.12, ENTER_N/EXIT_N 2/2,
# SCENARIO_TYPE_PERSISTENCE_N 6).
#
# Order of operations for one day, flags on:
#   1. classifier -> raw scenario_type + severity
#   2. scenario persistence: effective scenario_type = confirmed label (before Pulse; it decides
#      which actions Pulse is given)
#   3. hysteresis state from this patient's severity history incl. today (needs no Pulse output)
#   4. Pulse -> risk_score -> compute_baseline_high_streak() (C3) on today's RAW risk_bucket --
#      hysteresis never feeds C3, and C3 never feeds hysteresis
#   5. decide_alert() exactly as before
#   6. apply_severity_hysteresis(): replaces the level ONLY where decide_alert() itself used the
#      severity rule (failed_fallback / unstable_completed). A valid twin level -- risk_scorer,
#      moderate WATCH, c3_downgraded WATCH -- is never touched: the hysteresis parameters are
#      severity thresholds and say nothing about risk_bucket.
#   7. apply_hysteresis_to_ml_alert(): same replacement for the separately-reported ML signal.

_SEVERITY_FALLBACK_SOURCES = ("failed_fallback", "unstable_completed")


def severity_hysteresis_state(severities: list[Optional[float]]) -> str:
    """The hysteresis state after the last day of `severities` (chronological, today last)."""
    return hysteresis_alert_states(severities)[-1]


def apply_severity_hysteresis(report: AlertReport, hysteresis_state: Optional[str]) -> AlertReport:
    """Step 6 above. `hysteresis_state` None (flag off for that run) returns `report` unchanged."""
    if hysteresis_state is None or report.source not in _SEVERITY_FALLBACK_SOURCES:
        return report
    return AlertReport("ALERT" if hysteresis_state == "alert" else "NONE", report.source)


def apply_hysteresis_to_ml_alert(ml_alert: Optional[dict], hysteresis_state: Optional[str]) -> Optional[dict]:
    """Step 7 above. Adds `hysteresis_applied: True` so a reader can tell the level came from the
    multi-day state, not from today's severity alone. Unchanged (no extra key) when None."""
    if ml_alert is None or hysteresis_state is None:
        return ml_alert
    return {**ml_alert, "level": "ALERT" if hysteresis_state == "alert" else "NONE", "hysteresis_applied": True}


def effective_scenario_type(raw_history: list[Optional[str]], today_raw: str) -> tuple[str, Optional[str]]:
    """Step 2 above. `raw_history` is this patient's earlier raw classifier labels, oldest first.
    Returns (scenario_type to simulate, confirmed label or None).

    Until any label has held for SCENARIO_TYPE_PERSISTENCE_N days, scenario_type_persistence()
    has nothing confirmed and returns None; Pulse still needs a scenario, so today's raw label is
    used in that case. This fallback is the one choice here not taken from the existing function;
    it means persistence only starts to hold a label back once a first label is confirmed."""
    confirmed = scenario_type_persistence([*raw_history, today_raw])[-1]
    return (confirmed if confirmed is not None else today_raw), confirmed
