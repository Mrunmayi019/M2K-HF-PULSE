"""FOUNDATION ONLY -- Sprint 2.5 (2026-09-10), task 6. Defines the data contract that a future
real-outcome calibration pass (repeatedly referenced as "blocked on data" throughout
docs/methodology.md Sec 8 -- the severity/risk_score scale mismatch, MIN_CONFIDENCE_FOR_ALERT,
CONFIDENCE_BY_STATUS, ENTER/EXIT_THRESHOLD, SCENARIO_TYPE_PERSISTENCE_N are all pending exactly
this) would need to consume, so that future work has a defined shape to build against.

DELIBERATELY NOT POPULATED. No real patient data is loaded, referenced, or implied by this file --
it defines types only. No ingestion, storage, or query logic is implemented here either; that is
real design work for whichever future sprint actually acquires longitudinal outcome data, not
something to stub out speculatively now. This module exists purely so that work has a contract to
target rather than inventing one from scratch at that point.

What "calibration" would actually mean against this data, once it exists: fitting/validating the
placeholder constants named throughout src/analytics/score_reporting.py and
src/analytics/deterioration_rate.py (SD_RATE_TO_SEVERITY_PER_DAY, MIN_CONFIDENCE_FOR_ALERT,
CONFIDENCE_BY_STATUS's three values, ENTER_THRESHOLD/EXIT_THRESHOLD/ENTER_N/EXIT_N,
SCENARIO_TYPE_PERSISTENCE_N, and risk_score.py's own LOW_HIGH_BOUNDARY/MODERATE_HIGH_BOUNDARY)
against whether they actually predict the `known_outcome` below -- not implemented here.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Literal, Optional

# Every outcome type this project's own risk-scoring logic could plausibly be evaluated against,
# named explicitly rather than left as a free-text string -- extend this tuple, don't silently
# accept an unlisted value, since a calibration pass needs to know exactly what it's scoring
# against.
OutcomeEventType = Literal[
    "hospitalization",
    "death",
    "ed_visit",  # emergency department visit not resulting in admission
    "none_observed",  # the patient was followed and no qualifying event occurred in-window
]


@dataclass(frozen=True)
class KnownOutcome:
    """What actually happened to a patient, for comparing against this system's own
    severity/risk_score/alert output at some prior point in time. `frozen=True` -- an outcome
    record should never be mutated in place once created; a correction should be a new record.
    """

    event_type: OutcomeEventType
    event_date: Optional[datetime.date]  # None only valid when event_type == "none_observed"
    days_from_observation_to_event: Optional[int]  # None only valid when event_type == "none_observed"
    source: str  # e.g. "EHR discharge record", "manual chart review" -- provenance, not optional
    notes: Optional[str] = None


@dataclass(frozen=True)
class LongitudinalObservation:
    """One dated observation of a real patient's measurements -- the "before" half of a
    calibration record. `measurements` is deliberately a free-form dict rather than a fixed set of
    named fields: which measurements are available will vary by data source (wearable-only,
    wearable+echo, wearable+labs, etc.), and a rigid schema here would force premature decisions
    about what a real dataset must contain before one is even identified. Downstream calibration
    code is responsible for checking which keys it actually needs and handling absence explicitly
    -- this contract does not promise any particular key is present.

    Suggested (not required, not enforced) `measurements` keys, matching this project's own
    existing vocabulary so a real dataset maps onto it without a translation layer:
    `classifier_severity`, `pulse_risk_score`, `severity_band`, `simulation_status`, `confidence`,
    `scenario_type`, `resting_hr_bpm`, `spo2_pct`, `weight_kg`, `steps_per_day`, `sleep_hours`,
    `hrv_rmssd_ms`, `ejection_fraction_pct`, `nt_probnp_pg_ml`.
    """

    patient_id: str
    timestamp: datetime.datetime
    measurements: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CalibrationRecord:
    """The full contract: one longitudinal observation paired with the known outcome that
    followed it (or didn't). A future calibration pass would consume a sequence of these per
    patient -- ordered by `observation.timestamp` -- to fit/validate the placeholder constants
    named in this module's own docstring against whether they actually predicted
    `known_outcome`. Nothing about ordering, deduplication, or storage is defined here; that is
    real design work for whoever builds the actual ingestion path against a real dataset.
    """

    observation: LongitudinalObservation
    known_outcome: KnownOutcome
