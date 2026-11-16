"""Discovery pipeline tests: fake job sources, real SQLite database."""

from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import load_job_preferences
from app.database.models import Job, SearchSourceResult
from app.discovery.filtering import JobFilter
from app.discovery.pipeline import DiscoveryPipeline
from app.schemas.company import ATSProvider, CompanyConfig
from app.schemas.job import NormalizedJob, WorkplaceType
from app.scrapers.base import FetchResult, SourceFetchError

ACME = CompanyConfig(name="Acme", ats=ATSProvider.GREENHOUSE, board_id="acme", careers_url="https://acme.example.com")
BETA = CompanyConfig(name="Beta", ats=ATSProvider.GREENHOUSE, board_id="beta", careers_url="https://beta.example.com")


class FakeSource:
    """Returns queued responses per board: a list of postings, or an exception."""

    def __init__(self) -> None:
        self.responses: dict[str, deque] = defaultdict(deque)

    def queue(self, company: CompanyConfig, response, skipped: int = 0) -> None:
        self.responses[company.board_id].append((response, skipped))

    def fetch(self, company: CompanyConfig) -> FetchResult:
        response, skipped = self.responses[company.board_id].popleft()
        if isinstance(response, Exception):
            raise response
        return FetchResult(company=company, jobs=response, fetched_at=datetime.now(UTC), skipped_postings=skipped)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 16, 13, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance_days(self, days: int) -> None:
        self.now += timedelta(days=days)


def posting(
    company: CompanyConfig, job_id: str, title: str = "Software Engineer Intern",
    location: str = "Boston, MA", description: str = "Build services.", url: str | None = None,
) -> NormalizedJob:
    return NormalizedJob(
        job_id=f"greenhouse:{company.board_id}:{job_id}", source=ATSProvider.GREENHOUSE,
        source_job_id=job_id, company=company.name, title=title, location=location,
        locations=[location], employment_type=None, workplace_type=WorkplaceType.UNKNOWN,
        department=None, description=description, posted_at=None, updated_at=None,
        application_url=url or f"https://{company.board_id}.example.com/jobs/{job_id}",
        original_job_url=f"https://job-boards.greenhouse.io/{company.board_id}/jobs/{job_id}",
        fetched_at=datetime.now(UTC),
    )


@pytest.fixture(scope="module")
def job_filter() -> JobFilter:
    return JobFilter(load_job_preferences())


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def source() -> FakeSource:
    return FakeSource()


@pytest.fixture
def pipeline(session_factory, source, job_filter, clock) -> DiscoveryPipeline:
    return DiscoveryPipeline(session_factory, {ATSProvider.GREENHOUSE: source}, job_filter, clock=clock)


def stored_jobs(session_factory) -> dict[str, Job]:
    with session_factory() as session:
        return {job.source_job_id: job for job in session.scalars(select(Job))}


def test_first_run_saves_only_relevant_jobs(pipeline, source, session_factory, clock):
    source.queue(ACME, [posting(ACME, "1"), posting(ACME, "2", title="Senior Software Engineer")])

    summary = pipeline.run([ACME])

    jobs = stored_jobs(session_factory)
    assert list(jobs) == ["1"]
    assert jobs["1"].status == "active"
    assert jobs["1"].first_seen_at == clock.now
    assert jobs["1"].role_category == "software_engineering"
    assert jobs["1"].location_match == "priority_hub"
    run = summary.run
    assert (run.status, run.jobs_fetched, run.relevant_jobs, run.new_jobs) == ("success", 2, 1, 1)
    assert [job.source_job_id for job in summary.new_jobs] == ["1"]


def test_repeat_run_refreshes_last_seen_without_new_jobs(pipeline, source, session_factory, clock):
    source.queue(ACME, [posting(ACME, "1")])
    pipeline.run([ACME])
    first_seen = clock.now

    clock.advance_days(1)
    source.queue(ACME, [posting(ACME, "1")])
    summary = pipeline.run([ACME])

    job = stored_jobs(session_factory)["1"]
    assert (summary.run.new_jobs, summary.run.updated_jobs) == (0, 0)
    assert job.first_seen_at == first_seen
    assert job.last_seen_at == clock.now


def test_changed_posting_is_counted_as_updated(pipeline, source, session_factory, clock):
    source.queue(ACME, [posting(ACME, "1")])
    pipeline.run([ACME])

    clock.advance_days(1)
    source.queue(ACME, [posting(ACME, "1", description="Now with Python.")])
    summary = pipeline.run([ACME])

    job = stored_jobs(session_factory)["1"]
    assert summary.run.updated_jobs == 1
    assert job.description == "Now with Python."
    assert job.last_changed_at == clock.now


def test_missing_job_is_closed_then_reopened_when_relisted(pipeline, source, session_factory, clock):
    source.queue(ACME, [posting(ACME, "1"), posting(ACME, "2", title="Data Analyst Intern")])
    pipeline.run([ACME])

    clock.advance_days(1)
    source.queue(ACME, [posting(ACME, "1")])
    closed_run = pipeline.run([ACME]).run
    assert closed_run.closed_jobs == 1
    assert stored_jobs(session_factory)["2"].status == "closed"
    assert stored_jobs(session_factory)["2"].closed_at == clock.now

    clock.advance_days(1)
    source.queue(ACME, [posting(ACME, "1"), posting(ACME, "2", title="Data Analyst Intern")])
    reopened_run = pipeline.run([ACME]).run

    job = stored_jobs(session_factory)["2"]
    assert reopened_run.reopened_jobs == 1
    assert (job.status, job.closed_at) == ("active", None)


def test_failed_source_never_closes_its_jobs(pipeline, source, session_factory):
    source.queue(ACME, [posting(ACME, "1")])
    source.queue(BETA, [posting(BETA, "9")])
    pipeline.run([ACME, BETA])

    source.queue(ACME, SourceFetchError(ACME, "HTTP 503", retryable=True))
    source.queue(BETA, [posting(BETA, "9")])
    summary = pipeline.run([ACME, BETA])

    assert stored_jobs(session_factory)["1"].status == "active"
    assert summary.run.status == "partial"
    assert (summary.run.sources_queried, summary.run.sources_failed) == (2, 1)
    assert "HTTP 503" in summary.failures[0]
    with session_factory() as session:
        failed = session.scalars(select(SearchSourceResult).where(SearchSourceResult.succeeded.is_(False))).one()
    assert failed.board_key == "greenhouse:acme"
    assert "HTTP 503" in failed.error


def test_run_where_every_source_fails_is_marked_failed(pipeline, source):
    source.queue(ACME, SourceFetchError(ACME, "HTTP 404 (board not found)", retryable=False))

    assert pipeline.run([ACME]).run.status == "failed"


def test_empty_board_response_does_not_close_jobs(pipeline, source, session_factory):
    source.queue(ACME, [posting(ACME, "1")])
    pipeline.run([ACME])

    source.queue(ACME, [])
    summary = pipeline.run([ACME])

    assert stored_jobs(session_factory)["1"].status == "active"
    assert summary.run.closed_jobs == 0
    with session_factory() as session:
        latest = session.scalars(select(SearchSourceResult).order_by(SearchSourceResult.id.desc())).first()
    assert "no postings" in latest.note


def test_malformed_postings_skip_closures(pipeline, source, session_factory):
    source.queue(ACME, [posting(ACME, "1"), posting(ACME, "2", title="Data Analyst Intern")])
    pipeline.run([ACME])

    # Job 2 might be the malformed one, so it must not be closed.
    source.queue(ACME, [posting(ACME, "1")], skipped=1)
    pipeline.run([ACME])

    assert stored_jobs(session_factory)["2"].status == "active"


def test_same_job_on_two_boards_is_marked_duplicate(pipeline, source, session_factory):
    source.queue(ACME, [posting(ACME, "1")])
    pipeline.run([ACME])

    # Same company name, title and location on another board.
    twin = posting(BETA, "7").model_copy(update={"company": "Acme"})
    source.queue(BETA, [twin])
    summary = pipeline.run([BETA])

    jobs = stored_jobs(session_factory)
    assert jobs["7"].duplicate_of_id == jobs["1"].id
    assert (summary.run.new_jobs, summary.run.duplicate_jobs) == (0, 1)
    assert summary.new_jobs == []


def test_same_application_url_is_marked_duplicate(pipeline, source, session_factory):
    shared_url = "https://acme.example.com/careers/job?gh_jid=1"
    source.queue(ACME, [posting(ACME, "1", url=shared_url)])
    source.queue(BETA, [posting(BETA, "2", title="SWE Intern", location="NYC", url=shared_url + "&utm_source=x")])

    pipeline.run([ACME, BETA])

    jobs = stored_jobs(session_factory)
    assert jobs["2"].duplicate_of_id == jobs["1"].id


def test_unexpected_error_on_one_board_does_not_stop_others(pipeline, source, session_factory):
    source.queue(ACME, RuntimeError("bug"))
    source.queue(BETA, [posting(BETA, "9")])

    summary = pipeline.run([ACME, BETA])

    assert "9" in stored_jobs(session_factory)
    assert (summary.run.sources_queried, summary.run.sources_failed) == (2, 1)
    assert "unexpected error" in summary.failures[0]
