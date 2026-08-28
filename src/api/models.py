"""Phase 6: the 5 database tables (patients, clinical_reports, wearable_readings,
simulation_runs, risk_assessments), exactly as specified in the roadmap PDF §6.3.
"""
from __future__ import annotations

import datetime
import uuid
from typing import Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.api.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    age: Mapped[float] = mapped_column(Float)
    sex: Mapped[str] = mapped_column(String)
    height_cm: Mapped[float] = mapped_column(Float)
    weight_kg: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_utcnow)

    clinical_reports: Mapped[list["ClinicalReport"]] = relationship(back_populates="patient")
    wearable_readings: Mapped[list["WearableReading"]] = relationship(back_populates="patient")
    simulation_runs: Mapped[list["SimulationRun"]] = relationship(back_populates="patient")
    risk_assessments: Mapped[list["RiskAssessment"]] = relationship(back_populates="patient")


class ClinicalReport(Base):
    __tablename__ = "clinical_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"))
    ejection_fraction_pct: Mapped[float] = mapped_column(Float)
    nt_probnp_pg_ml: Mapped[float] = mapped_column(Float)
    ef_is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    bnp_is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    reported_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_utcnow)

    patient: Mapped["Patient"] = relationship(back_populates="clinical_reports")


class WearableReading(Base):
    __tablename__ = "wearable_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"))
    recorded_date: Mapped[datetime.date] = mapped_column(Date)
    resting_hr_bpm: Mapped[float] = mapped_column(Float)
    spo2_pct: Mapped[float] = mapped_column(Float)
    weight_kg: Mapped[float] = mapped_column(Float)
    steps_per_day: Mapped[float] = mapped_column(Float)
    sleep_hours: Mapped[float] = mapped_column(Float)
    hrv_rmssd_ms: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_utcnow)

    patient: Mapped["Patient"] = relationship(back_populates="wearable_readings")


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"))
    scenario_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    severity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending|running|complete|failed
    error_message: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    scenario_json_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    # {"cycle_duration_s": ..., "pv_loop": [{"volume_ml", "pressure_mmhg"}, ...], "ecg": [{"t_s",
    # "mv"}, ...]} -- see src.analytics.simulation_features.extract_waveform_data(). Nullable:
    # simulation runs created before this field was added (2026-08-28) have none.
    waveform_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    patient: Mapped["Patient"] = relationship(back_populates="simulation_runs")
    risk_assessment: Mapped[Optional["RiskAssessment"]] = relationship(back_populates="simulation_run")


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"))
    simulation_run_id: Mapped[int] = mapped_column(ForeignKey("simulation_runs.id"))
    risk_score: Mapped[float] = mapped_column(Float)
    risk_bucket: Mapped[str] = mapped_column(String)
    component_scores: Mapped[dict] = mapped_column(JSON)
    # risk_score.compute_risk_score() computes these but they were previously discarded before
    # storage -- for a fluid_overload patient whose score is baseline-driven (§6.1), every
    # component_scores entry can legitimately read 0 while risk_score is nonzero, with nothing in
    # the stored data explaining why. Nullable: existing rows predate this field (2026-08-28).
    baseline_deficit_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dominant_mechanism: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    nyha_class: Mapped[str] = mapped_column(String)
    risk_caveats: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    deterioration_direction: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    days_to_next_stage: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    projection_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Phase 7: the clinical values actually used to produce this assessment (already computed in
    # services.py at pipeline time -- persisted here instead of discarded, so the API can return
    # what powered a given assessment rather than only the current/latest clinical report).
    ejection_fraction_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    nt_probnp_pg_ml: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Per-vital trend slopes from compute_deterioration_rate(), native units/day (e.g. resting_hr_bpm
    # rising 0.8 bpm/day) -- powers the frontend's "7-Day Trend" column instead of a fabricated
    # "Simulation Output" figure that was never actually computed.
    vital_slopes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_utcnow)

    patient: Mapped["Patient"] = relationship(back_populates="risk_assessments")
    simulation_run: Mapped["SimulationRun"] = relationship(back_populates="risk_assessment")

    @property
    def scenario_type(self) -> Optional[str]:
        return self.simulation_run.scenario_type if self.simulation_run else None

    @property
    def severity(self) -> Optional[float]:
        return self.simulation_run.severity if self.simulation_run else None
