"""SQLAlchemy ORM models.

Tables:
    jobs                  one row per discovered posting (only relevant ones are added)
    search_runs           one row per discovery run, with totals
    search_source_results one row per company board queried in a run
"""

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Stores datetimes as UTC and always returns timezone-aware values.

    SQLite has no timezone support and would hand back naive datetimes; this
    keeps behaviour identical on SQLite and PostgreSQL.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetimes are not allowed; use timezone-aware UTC")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None else None


class Base(DeclarativeBase):
    pass


class JobStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"  # no longer listed on a board that was fetched successfully


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"  # some sources failed
    FAILED = "failed"    # every source failed


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    # "greenhouse:mongodb:8209134" - the provider-based identity of a posting.
    job_key: Mapped[str] = mapped_column(String(255), unique=True)
    # "greenhouse:mongodb" - which board the posting came from (used for closures).
    board_key: Mapped[str] = mapped_column(String(255), index=True)
    source: Mapped[str] = mapped_column(String(20))
    source_job_id: Mapped[str] = mapped_column(String(255))

    company: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(500))
    location: Mapped[str | None] = mapped_column(String(500))
    locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    country: Mapped[str | None] = mapped_column(String(100))
    employment_type: Mapped[str | None] = mapped_column(String(100))
    workplace_type: Mapped[str] = mapped_column(String(20))
    department: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    provider_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    application_url: Mapped[str] = mapped_column(String(2000))
    original_job_url: Mapped[str] = mapped_column(String(2000))

    # Filter results, refreshed on every run.
    role_category: Mapped[str | None] = mapped_column(String(50))
    location_match: Mapped[str] = mapped_column(String(20))

    # Cross-source duplicate detection (see app/discovery/dedup.py).
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    normalized_url: Mapped[str] = mapped_column(String(2000), index=True)
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"))
    # Hash of the posting's meaningful fields; a change means the job was updated.
    content_hash: Mapped[str] = mapped_column(String(64))

    status: Mapped[str] = mapped_column(String(20), default=JobStatus.ACTIVE, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)  # "date discovered"
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_changed_at: Mapped[datetime] = mapped_column(UTCDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    def __repr__(self) -> str:
        return f"<Job {self.job_key} {self.title!r} {self.status}>"


class SearchRun(Base):
    __tablename__ = "search_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.RUNNING)

    sources_queried: Mapped[int] = mapped_column(Integer, default=0)
    sources_failed: Mapped[int] = mapped_column(Integer, default=0)
    jobs_fetched: Mapped[int] = mapped_column(Integer, default=0)
    relevant_jobs: Mapped[int] = mapped_column(Integer, default=0)
    new_jobs: Mapped[int] = mapped_column(Integer, default=0)
    updated_jobs: Mapped[int] = mapped_column(Integer, default=0)
    reopened_jobs: Mapped[int] = mapped_column(Integer, default=0)
    closed_jobs: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_jobs: Mapped[int] = mapped_column(Integer, default=0)

    source_results: Mapped[list["SearchSourceResult"]] = relationship(
        back_populates="run", order_by="SearchSourceResult.id"
    )


class SearchSourceResult(Base):
    __tablename__ = "search_source_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("search_runs.id"), index=True)
    board_key: Mapped[str] = mapped_column(String(255))
    company: Mapped[str] = mapped_column(String(255))
    succeeded: Mapped[bool] = mapped_column(Boolean)
    duration_seconds: Mapped[float] = mapped_column(Float)
    jobs_fetched: Mapped[int] = mapped_column(Integer, default=0)
    skipped_postings: Mapped[int] = mapped_column(Integer, default=0)
    relevant_jobs: Mapped[int] = mapped_column(Integer, default=0)
    new_jobs: Mapped[int] = mapped_column(Integer, default=0)
    closed_jobs: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    # Why closures were skipped for this board, if they were.
    note: Mapped[str | None] = mapped_column(Text)

    run: Mapped[SearchRun] = relationship(back_populates="source_results")
