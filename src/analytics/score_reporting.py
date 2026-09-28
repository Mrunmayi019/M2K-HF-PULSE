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

from typing import Literal, Optional

from src.data_synthesis.generate_patients import STABLE_SEVERITY_CAP
from src.pulse_runner.runner import is_known_unstable_configuration

ScoreSource = Literal["classifier_only", "pulse_only", "not_fused"]
SimulationStatus = Literal["valid", "unstable", "not_run"]
AlertState = Literal["alert", "no_alert", "indeterminate"]


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
