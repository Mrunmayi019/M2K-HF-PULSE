"""Phase 6: database engine/session setup.

SQLite by default (a local file under data/db/, gitignored -- runtime state, not source-controlled
data). `DATABASE_URL` env var overrides this, so switching to Postgres later ("stretch/deploy
claim" per the planning PDF) is a config change, not a code change -- no Postgres server is
actually stood up here.
"""
from __future__ import annotations

import os
import pathlib

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "db" / "m2k_hf_pulse.db"
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
