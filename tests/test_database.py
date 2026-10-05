"""Tests for src/api/database.py's add_missing_columns() -- the schema-drift guard
(fix/unified-alert-decision, 2026-10-06). Pure SQLite, no Docker/Pulse required.

Run from repo root: pytest tests/test_database.py -v
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from src.api import models
from src.api.database import Base, add_missing_columns


@pytest.fixture()
def old_schema_engine():
    """A SQLite DB built with the CURRENT models (so every other column/table is right), then
    with RiskAssessment's two newest columns dropped -- simulating a database file that existed
    before fix/unified-alert-decision added them. Modern SQLite (3.35+) supports DROP COLUMN
    directly, which is exactly what this needs to construct the "old" shape without maintaining
    a separate, parallel old model definition."""
    tmp_dir = tempfile.mkdtemp()
    db_path = pathlib.Path(tmp_dir) / "old.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE risk_assessments DROP COLUMN baseline_high_streak_days"))
        conn.execute(text("ALTER TABLE risk_assessments DROP COLUMN instability_seen_in_streak"))
    yield engine
    engine.dispose()


class TestAddMissingColumns:
    def test_old_db_is_missing_the_two_new_columns(self, old_schema_engine):
        cols = {c["name"] for c in inspect(old_schema_engine).get_columns("risk_assessments")}
        assert "baseline_high_streak_days" not in cols
        assert "instability_seen_in_streak" not in cols

    def test_adds_the_missing_columns(self, old_schema_engine):
        add_missing_columns(bind=old_schema_engine)
        cols = {c["name"] for c in inspect(old_schema_engine).get_columns("risk_assessments")}
        assert "baseline_high_streak_days" in cols
        assert "instability_seen_in_streak" in cols

    def test_insert_with_the_new_columns_works_after_the_fix(self, old_schema_engine):
        """The actual failure mode this guards against: before the fix, this INSERT raises
        OperationalError("no such column"). After it, it must just work."""
        add_missing_columns(bind=old_schema_engine)
        Session = sessionmaker(bind=old_schema_engine)
        db = Session()
        try:
            db.add(models.Patient(age=65, sex="Male", height_cm=175, weight_kg=80))
            db.commit()
            patient = db.query(models.Patient).first()
            run = models.SimulationRun(patient_id=patient.id, scenario_type="stable", severity=0.1, status="complete")
            db.add(run)
            db.commit()
            db.add(models.RiskAssessment(
                patient_id=patient.id, simulation_run_id=run.id, risk_score=0.5, risk_bucket="MODERATE",
                component_scores={}, nyha_class="I", baseline_high_streak_days=3,
                instability_seen_in_streak=False,
            ))
            db.commit()  # would raise OperationalError pre-fix
            saved = db.query(models.RiskAssessment).first()
            assert saved.baseline_high_streak_days == 3
            assert saved.instability_seen_in_streak is False
        finally:
            db.close()

    def test_running_it_twice_is_a_no_op_the_second_time(self, old_schema_engine):
        """SQLite's ADD COLUMN fails if the column already exists -- add_missing_columns() must
        not blindly re-issue it for a column that's already there (e.g. init_db() being called
        more than once in a process, or on an already-up-to-date DB)."""
        add_missing_columns(bind=old_schema_engine)
        add_missing_columns(bind=old_schema_engine)  # must not raise
        cols = {c["name"] for c in inspect(old_schema_engine).get_columns("risk_assessments")}
        assert "baseline_high_streak_days" in cols

    def test_brand_new_db_is_unaffected(self):
        """A DB created fresh from the current models already has every column -- create_all()
        handles that case; this guard should find nothing to do and not error."""
        tmp_dir = tempfile.mkdtemp()
        engine = create_engine(f"sqlite:///{pathlib.Path(tmp_dir) / 'new.db'}")
        Base.metadata.create_all(bind=engine)
        add_missing_columns(bind=engine)  # must not raise
        cols = {c["name"] for c in inspect(engine).get_columns("risk_assessments")}
        assert "baseline_high_streak_days" in cols
        assert "instability_seen_in_streak" in cols
