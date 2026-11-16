"""Database queries, kept out of the pipeline so its logic stays readable."""

from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.database.models import Job, JobStatus, SearchRun

# Stay well under database limits on the number of parameters in one IN (...).
_IN_CLAUSE_CHUNK = 500


class JobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_keys(self, job_keys: Iterable[str]) -> dict[str, Job]:
        keys = list(job_keys)
        found: dict[str, Job] = {}
        for start in range(0, len(keys), _IN_CLAUSE_CHUNK):
            chunk = keys[start : start + _IN_CLAUSE_CHUNK]
            for job in self._session.scalars(select(Job).where(Job.job_key.in_(chunk))):
                found[job.job_key] = job
        return found

    def active_for_board(self, board_key: str) -> list[Job]:
        query = select(Job).where(Job.board_key == board_key, Job.status == JobStatus.ACTIVE)
        return list(self._session.scalars(query))

    def find_duplicate_of(self, fingerprint: str, normalized_url: str, job_key: str) -> Job | None:
        """Oldest active, non-duplicate job that looks like the same posting."""
        query = (
            select(Job)
            .where(
                Job.job_key != job_key,
                Job.status == JobStatus.ACTIVE,
                Job.duplicate_of_id.is_(None),
                or_(Job.fingerprint == fingerprint, Job.normalized_url == normalized_url),
            )
            .order_by(Job.first_seen_at, Job.id)
            .limit(1)
        )
        return self._session.scalars(query).first()

    def add(self, job: Job) -> None:
        self._session.add(job)

    def list_jobs(
        self, *, include_closed: bool = False, include_duplicates: bool = False,
        company: str | None = None, limit: int = 50,
    ) -> list[Job]:
        query = select(Job)
        if not include_closed:
            query = query.where(Job.status == JobStatus.ACTIVE)
        if not include_duplicates:
            query = query.where(Job.duplicate_of_id.is_(None))
        if company:
            query = query.where(Job.company.ilike(company))
        query = query.order_by(Job.first_seen_at.desc(), Job.company, Job.title).limit(limit)
        return list(self._session.scalars(query))


class SearchRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, run_id: int) -> SearchRun | None:
        query = (
            select(SearchRun)
            .options(selectinload(SearchRun.source_results))
            .where(SearchRun.id == run_id)
        )
        return self._session.scalars(query).first()

    def recent(self, limit: int = 10) -> list[SearchRun]:
        query = (
            select(SearchRun)
            .options(selectinload(SearchRun.source_results))
            .order_by(SearchRun.started_at.desc(), SearchRun.id.desc())
            .limit(limit)
        )
        return list(self._session.scalars(query))
