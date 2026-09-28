"""Tests for src/analytics/outcome_calibration.py -- a FOUNDATION-ONLY contract (Sprint 2.5,
task 6), not real calibration logic. These tests confirm the interface is usable/well-formed;
they do not (and cannot) test calibration itself, since no real outcome data exists yet.

Run from repo root: pytest tests/test_outcome_calibration.py -v
"""
import dataclasses
import datetime

import pytest

from src.analytics.outcome_calibration import (
    CalibrationRecord,
    KnownOutcome,
    LongitudinalObservation,
)


class TestLongitudinalObservation:
    def test_can_be_constructed_with_arbitrary_measurements(self):
        obs = LongitudinalObservation(
            patient_id="P0001",
            timestamp=datetime.datetime(2026, 1, 1, 8, 0),
            measurements={"classifier_severity": 0.7, "resting_hr_bpm": 88},
        )
        assert obs.patient_id == "P0001"
        assert obs.measurements["classifier_severity"] == 0.7

    def test_measurements_defaults_to_empty_dict_not_none(self):
        obs = LongitudinalObservation(patient_id="P0001", timestamp=datetime.datetime.now())
        assert obs.measurements == {}

    def test_is_frozen(self):
        obs = LongitudinalObservation(patient_id="P0001", timestamp=datetime.datetime.now())
        with pytest.raises(dataclasses.FrozenInstanceError):
            obs.patient_id = "P0002"


class TestKnownOutcome:
    def test_can_represent_a_hospitalization(self):
        outcome = KnownOutcome(
            event_type="hospitalization",
            event_date=datetime.date(2026, 1, 15),
            days_from_observation_to_event=14,
            source="EHR discharge record",
        )
        assert outcome.event_type == "hospitalization"
        assert outcome.days_from_observation_to_event == 14

    def test_can_represent_no_event_observed(self):
        outcome = KnownOutcome(
            event_type="none_observed",
            event_date=None,
            days_from_observation_to_event=None,
            source="30-day follow-up call",
        )
        assert outcome.event_type == "none_observed"
        assert outcome.event_date is None

    def test_is_frozen(self):
        outcome = KnownOutcome(
            event_type="none_observed", event_date=None, days_from_observation_to_event=None, source="x"
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            outcome.event_type = "death"


class TestCalibrationRecord:
    def test_pairs_an_observation_with_its_outcome(self):
        obs = LongitudinalObservation(
            patient_id="P0001",
            timestamp=datetime.datetime(2026, 1, 1),
            measurements={"classifier_severity": 0.8, "pulse_risk_score": 0.6},
        )
        outcome = KnownOutcome(
            event_type="hospitalization",
            event_date=datetime.date(2026, 1, 10),
            days_from_observation_to_event=9,
            source="EHR discharge record",
        )
        record = CalibrationRecord(observation=obs, known_outcome=outcome)
        assert record.observation.patient_id == "P0001"
        assert record.known_outcome.event_type == "hospitalization"

    def test_a_sequence_of_records_can_represent_one_patients_longitudinal_history(self):
        # Not testing any real ingestion/ordering logic (deliberately unimplemented) -- just that
        # the contract supports the shape a future calibration pass would need: multiple dated
        # observations for the same patient_id.
        records = [
            CalibrationRecord(
                observation=LongitudinalObservation(
                    patient_id="P0001", timestamp=datetime.datetime(2026, 1, d), measurements={"classifier_severity": 0.1 * d}
                ),
                known_outcome=KnownOutcome(
                    event_type="none_observed", event_date=None, days_from_observation_to_event=None, source="x"
                ),
            )
            for d in range(1, 4)
        ]
        assert len({r.observation.patient_id for r in records}) == 1
        severities = [r.observation.measurements["classifier_severity"] for r in records]
        assert severities == pytest.approx([0.1, 0.2, 0.3])
