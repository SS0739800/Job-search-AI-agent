"""Engine and session setup."""

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_database_url
from app.database.models import Base


def create_db_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_database_url()
    is_sqlite = url.startswith("sqlite")
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(url)
    if is_sqlite:
        # SQLite ignores foreign keys unless this is enabled per connection.
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def init_db(engine: Engine) -> None:
    """Create missing tables. (Alembic migrations will replace this once the
    schema starts changing after real data exists.)"""
    Base.metadata.create_all(engine)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False lets objects be read after commit without a reload.
    return sessionmaker(engine, expire_on_commit=False)
