"""The discovery run: fetch every board, filter, and sync results to the database.

For each company board:
    fetch postings -> evaluate with JobFilter -> sync with stored jobs
        new + relevant   -> insert (or insert marked as a duplicate)
        already stored   -> refresh last_seen; detect content updates; reopen if closed
        stored, missing  -> mark closed, but ONLY if the fetch fully succeeded
A failed board is recorded and skipped; it never causes closures.
"""

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from app.database.models import Job, JobStatus, RunStatus, SearchRun, SearchSourceResult
from app.database.repositories import JobRepository
from app.discovery.dedup import content_hash, job_fingerprint, normalize_url
from app.discovery.filtering import FilterDecision, JobFilter
from app.schemas.company import ATSProvider, CompanyConfig
from app.schemas.job import NormalizedJob
from app.scrapers.base import FetchResult, SourceFetchError

logger = logging.getLogger(__name__)


class JobSource(Protocol):
    def fetch(self, company: CompanyConfig) -> FetchResult: ...


@dataclass
class BoardSyncStats:
    relevant: int = 0
    new: int = 0
    duplicates: int = 0
    updated: int = 0
    reopened: int = 0
    closed: int = 0
    closure_note: str | None = None
    new_jobs: list[Job] = field(default_factory=list)


@dataclass
class RunSummary:
    run: SearchRun
    new_jobs: list[Job]
    failures: list[str]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _apply_posting(row: Job, posting: NormalizedJob) -> None:
    """Copy provider data from a NormalizedJob onto a database row."""
    row.company = posting.company
    row.title = posting.title
    row.location = posting.location
    row.locations = list(posting.locations)
    row.country = posting.country
    row.employment_type = posting.employment_type
    row.workplace_type = posting.workplace_type.value
    row.department = posting.department
    row.description = posting.description
    row.posted_at = posting.posted_at
    row.provider_updated_at = posting.updated_at
    row.application_url = posting.application_url
    row.original_job_url = posting.original_job_url
    row.fingerprint = job_fingerprint(
        posting.company, posting.title, posting.location, list(posting.locations)
    )
    row.normalized_url = normalize_url(posting.application_url)
    row.content_hash = content_hash(posting)


class DiscoveryPipeline:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        sources: Mapping[ATSProvider, JobSource],
        job_filter: JobFilter,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._sources = sources
        self._filter = job_filter
        self._clock = clock

    def run(self, companies: Sequence[CompanyConfig]) -> RunSummary:
        new_jobs: list[Job] = []
        failures: list[str] = []
        with self._session_factory() as session:
            run = SearchRun(started_at=self._clock(), status=RunStatus.RUNNING)
            session.add(run)
            session.commit()  # the run is recorded even if the process dies mid-way

            for company in companies:
                error = self._process_board(session, run, company, new_jobs)
                if error:
                    failures.append(error)
                session.commit()  # one transaction per board

            run.finished_at = self._clock()
            if run.sources_failed == 0:
                run.status = RunStatus.SUCCESS
            elif run.sources_failed < run.sources_queried:
                run.status = RunStatus.PARTIAL
            else:
                run.status = RunStatus.FAILED
            session.commit()
        return RunSummary(run=run, new_jobs=new_jobs, failures=failures)

    def _process_board(
        self, session: Session, run: SearchRun, company: CompanyConfig, new_jobs: list[Job]
    ) -> str | None:
        """Fetch and sync one board. Returns an error message if it failed."""
        board_key = f"{company.ats}:{company.board_id}"
        started = time.perf_counter()
        try:
            result = self._sources[company.ats].fetch(company)
            stats = self._sync_board(session, board_key, result)
        except SourceFetchError as exc:
            return self._record_failure(session, run, company, board_key, str(exc), started)
        except Exception as exc:  # a bug or DB error must not stop other boards
            logger.exception("Unexpected error while processing %s", board_key)
            session.rollback()  # discard this board's partial changes
            error = f"{company.name} ({board_key}): unexpected error: {exc!r}"
            return self._record_failure(session, run, company, board_key, error, started)

        run.sources_queried += 1
        run.jobs_fetched += len(result.jobs)
        run.relevant_jobs += stats.relevant
        run.new_jobs += stats.new
        run.duplicate_jobs += stats.duplicates
        run.updated_jobs += stats.updated
        run.reopened_jobs += stats.reopened
        run.closed_jobs += stats.closed
        new_jobs.extend(stats.new_jobs)
        session.add(SearchSourceResult(
            run=run, board_key=board_key, company=company.name, succeeded=True,
            duration_seconds=time.perf_counter() - started,
            jobs_fetched=len(result.jobs), skipped_postings=result.skipped_postings,
            relevant_jobs=stats.relevant, new_jobs=stats.new, closed_jobs=stats.closed,
            note=stats.closure_note,
        ))
        logger.info(
            "%s: %d fetched, %d relevant, %d new, %d updated, %d closed",
            board_key, len(result.jobs), stats.relevant, stats.new, stats.updated, stats.closed,
        )
        return None

    def _record_failure(
        self, session: Session, run: SearchRun, company: CompanyConfig,
        board_key: str, error: str, started: float,
    ) -> str:
        # Counters are updated here, after any rollback, which would otherwise undo them.
        logger.error("Source failed: %s", error)
        run.sources_queried += 1
        run.sources_failed += 1
        session.add(SearchSourceResult(
            run=run, board_key=board_key, company=company.name, succeeded=False,
            duration_seconds=time.perf_counter() - started, error=error,
        ))
        return error

    def _sync_board(self, session: Session, board_key: str, result: FetchResult) -> BoardSyncStats:
        repo = JobRepository(session)
        now = self._clock()
        stats = BoardSyncStats()
        evaluated: list[tuple[NormalizedJob, FilterDecision]] = [
            (posting, self._filter.evaluate(posting)) for posting in result.jobs
        ]
        stored = repo.get_by_keys(posting.job_id for posting, _ in evaluated)

        for posting, decision in evaluated:
            stats.relevant += decision.is_relevant
            row = stored.get(posting.job_id)
            if row is None:
                if decision.is_relevant:
                    self._insert(repo, board_key, posting, decision, now, stats)
                continue
            self._refresh(row, posting, decision, now, stats)

        self._close_missing(repo, board_key, result, {p.job_id for p, _ in evaluated}, now, stats)
        return stats

    def _insert(
        self, repo: JobRepository, board_key: str, posting: NormalizedJob,
        decision: FilterDecision, now: datetime, stats: BoardSyncStats,
    ) -> None:
        row = Job(
            job_key=posting.job_id, board_key=board_key, source=posting.source.value,
            source_job_id=posting.source_job_id, status=JobStatus.ACTIVE,
            first_seen_at=now, last_seen_at=now, last_changed_at=now,
            role_category=decision.role_category, location_match=decision.location_match.value,
        )
        _apply_posting(row, posting)
        original = repo.find_duplicate_of(row.fingerprint, row.normalized_url, row.job_key)
        if original is not None:
            row.duplicate_of_id = original.id
            stats.duplicates += 1
            logger.info("%s looks like a duplicate of %s", row.job_key, original.job_key)
        else:
            stats.new += 1
            stats.new_jobs.append(row)
        repo.add(row)

    def _refresh(
        self, row: Job, posting: NormalizedJob, decision: FilterDecision,
        now: datetime, stats: BoardSyncStats,
    ) -> None:
        row.last_seen_at = now
        # Re-evaluated every run so edits to job_preferences.yaml take effect.
        row.role_category = decision.role_category
        row.location_match = decision.location_match.value
        if row.status == JobStatus.CLOSED:
            row.status = JobStatus.ACTIVE
            row.closed_at = None
            stats.reopened += 1
        if content_hash(posting) != row.content_hash:
            _apply_posting(row, posting)
            row.last_changed_at = now
            stats.updated += 1

    def _close_missing(
        self, repo: JobRepository, board_key: str, result: FetchResult,
        fetched_keys: set[str], now: datetime, stats: BoardSyncStats,
    ) -> None:
        active = repo.active_for_board(board_key)
        missing = [row for row in active if row.job_key not in fetched_keys]
        if not missing:
            return
        # Guard rails: only close when the fetch clearly showed the full board.
        if not result.jobs:
            stats.closure_note = (
                f"board returned no postings; kept {len(missing)} job(s) open in case of an API glitch"
            )
        elif result.skipped_postings:
            stats.closure_note = (
                f"{result.skipped_postings} malformed posting(s); closures skipped for this run"
            )
        if stats.closure_note:
            logger.warning("%s: %s", board_key, stats.closure_note)
            return
        for row in missing:
            row.status = JobStatus.CLOSED
            row.closed_at = now
            stats.closed += 1
