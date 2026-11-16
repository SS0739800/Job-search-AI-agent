from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import StatementError

from app.database.db import create_db_engine, init_db
from app.database.models import SearchRun


def test_datetimes_round_trip_as_timezone_aware_utc(session_factory):
    eastern = timezone(timedelta(hours=-5))
    with session_factory() as session:
        session.add(SearchRun(started_at=datetime(2026, 11, 16, 8, 0, tzinfo=eastern)))
        session.commit()

    with session_factory() as session:
        stored = session.scalars(select(SearchRun)).one()

    assert stored.started_at == datetime(2026, 11, 16, 13, 0, tzinfo=UTC)
    assert stored.started_at.tzinfo is not None


def test_naive_datetimes_are_rejected(session_factory):
    with session_factory() as session:
        session.add(SearchRun(started_at=datetime(2026, 11, 16, 8, 0)))
        with pytest.raises(StatementError, match="naive datetimes"):
            session.commit()


def test_sqlite_file_directory_is_created(tmp_path):
    db_path = tmp_path / "nested" / "dir" / "jobs.db"
    engine = create_db_engine(f"sqlite:///{db_path.as_posix()}")
    init_db(engine)
    engine.dispose()

    assert db_path.exists()
