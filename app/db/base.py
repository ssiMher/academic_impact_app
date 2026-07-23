"""SQLAlchemy declarative base and table initialization."""

from typing import Optional

from sqlalchemy import Engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def init_db(engine: Optional[Engine] = None) -> None:
    """Create all known tables for the current metadata."""
    from app.db.engine import engine as default_engine
    from app.db.migrations import upgrade_sqlite_schema
    import app.models  # noqa: F401

    target_engine = engine or default_engine
    Base.metadata.create_all(bind=target_engine)
    upgrade_sqlite_schema(target_engine)
