"""Phase 6: database engine/session setup.

SQLite by default (a local file under data/db/, gitignored -- runtime state, not source-controlled
data). `DATABASE_URL` env var overrides this, so switching to Postgres later ("stretch/deploy
claim" per the planning PDF) is a config change, not a code change -- no Postgres server is
actually stood up here.
"""
from __future__ import annotations

import os
import pathlib

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "db" / "m2k_hf_pulse.db"
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def add_missing_columns(bind=None) -> None:
    """Schema-drift guard (fix/unified-alert-decision, 2026-10-06). `Base.metadata.create_all()`
    only creates TABLES that don't exist yet -- it never alters a table that already exists, so
    a model field added after a DB file was first created (e.g. `RiskAssessment.baseline_high_
    streak_days`/`instability_seen_in_streak`) would otherwise raise `OperationalError: no such
    column` on the very first write to an old DB file. Run after `create_all()`.

    Only handles the one case every nullable column in this project's models actually needs:
    adding a column with no server-side default/constraint, which SQLite supports directly via
    `ALTER TABLE ... ADD COLUMN`. Refuses (raises, does not guess a default) for a new column
    that isn't nullable -- that needs a real backfill migration, not this.
    """
    bind = bind or engine
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all() already handles a brand-new table
            existing_columns = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                if not column.nullable:
                    raise RuntimeError(
                        f"{table.name}.{column.name} is new and NOT NULL -- cannot be added to "
                        "an existing table without a backfill value. Add it as nullable, or "
                        "write an explicit migration for this one instead of relying on this "
                        "guard."
                    )
                col_type = column.type.compile(bind.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))


def init_db() -> None:
    DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    add_missing_columns()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
