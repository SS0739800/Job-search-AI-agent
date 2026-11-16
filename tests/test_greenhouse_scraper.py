from datetime import UTC, datetime

import httpx
import pytest

from app.schemas.company import ATSProvider, CompanyConfig
from app.schemas.job import WorkplaceType
from app.scrapers.base import SourceFetchError
from app.scrapers.greenhouse import GreenhouseScraper

COMPANY = CompanyConfig(
    name="Example Corp",
    ats=ATSProvider.GREENHOUSE,
    board_id="examplecorp",
    careers_url="https://www.example.com/careers",
)


def make_scraper(client: httpx.Client, sleeps: list[float] | None = None) -> GreenhouseScraper:
    recorded = sleeps if sleeps is not None else []
    return GreenhouseScraper(client, max_retries=2, backoff_seconds=1.0, sleep=recorded.append)


@pytest.fixture
def board_result(load_fixture, make_http_client):
    payload = load_fixture("greenhouse_board.json")
    client = make_http_client(lambda request: httpx.Response(200, json=payload))
    return make_scraper(client).fetch(COMPANY)


def test_requests_board_endpoint_with_content(load_fixture, make_http_client):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"jobs": []})

    make_scraper(make_http_client(handler)).fetch(COMPANY)

    assert str(seen[0].url) == "https://boards-api.greenhouse.io/v1/boards/examplecorp/jobs?content=true"


def test_valid_postings_are_normalized_and_malformed_are_skipped(board_result):
    assert [job.source_job_id for job in board_result.jobs] == ["1001", "1002"]
    assert board_result.skipped_postings == 1


def test_normalizes_full_posting(board_result):
    job = board_result.jobs[0]

    assert job.job_id == "greenhouse:examplecorp:1001"
    assert job.source is ATSProvider.GREENHOUSE
    assert job.company == "Example Corp"
    assert job.title == "2027 - Software Engineering Intern, AMER"
    assert job.location == "Austin; New York City; San Francisco"
    # Structured office locations win; an office without one falls back to its name.
    assert job.locations == ["Austin, TX, United States", "New York, NY, United States", "San Francisco"]
    assert job.department == "Engineering, Intern"
    assert job.employment_type is None
    assert job.workplace_type is WorkplaceType.UNKNOWN
    assert job.application_url == "https://www.example.com/careers/job/?gh_jid=1001"
    assert job.original_job_url == "https://job-boards.greenhouse.io/examplecorp/jobs/1001"


def test_dates_are_converted_to_utc(board_result):
    job = board_result.jobs[0]

    assert job.posted_at == datetime(2026, 10, 23, 12, 57, 16, tzinfo=UTC)
    assert job.updated_at == datetime(2026, 11, 16, 14, 27, 51, tzinfo=UTC)
    assert job.fetched_at == board_result.fetched_at


def test_double_escaped_html_description_becomes_plain_text(board_result):
    assert board_result.jobs[0].description == "Join our Platform team.\n\n- Python\n- SQL"


def test_sparse_posting_uses_safe_defaults(board_result):
    job = board_result.jobs[1]

    assert job.description is None
    assert job.posted_at is None
    assert job.department is None
    assert job.locations == ["Remote - US"]
    assert job.workplace_type is WorkplaceType.REMOTE


def test_board_not_found_is_not_retried(make_http_client):
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404, json={"status": 404, "error": "Job not found"})

    with pytest.raises(SourceFetchError, match="board not found") as excinfo:
        make_scraper(make_http_client(handler)).fetch(COMPANY)

    assert excinfo.value.retryable is False
    assert len(calls) == 1


def test_transient_server_error_is_retried_then_succeeds(make_http_client):
    responses = iter([httpx.Response(503), httpx.Response(200, json={"jobs": []})])
    sleeps: list[float] = []

    result = make_scraper(make_http_client(lambda request: next(responses)), sleeps).fetch(COMPANY)

    assert result.jobs == []
    assert sleeps == [1.0]


def test_persistent_timeout_raises_retryable_error_after_backoff(make_http_client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    sleeps: list[float] = []
    with pytest.raises(SourceFetchError, match="network error") as excinfo:
        make_scraper(make_http_client(handler), sleeps).fetch(COMPANY)

    assert excinfo.value.retryable is True
    assert sleeps == [1.0, 2.0]  # exponential backoff between the 3 attempts


@pytest.mark.parametrize("payload", [{"unexpected": []}, [], {"jobs": "nope"}])
def test_unexpected_response_shape_raises(make_http_client, payload):
    client = make_http_client(lambda request: httpx.Response(200, json=payload))

    with pytest.raises(SourceFetchError, match="unexpected response shape"):
        make_scraper(client).fetch(COMPANY)


def test_invalid_json_raises(make_http_client):
    client = make_http_client(lambda request: httpx.Response(200, text="<html>maintenance</html>"))

    with pytest.raises(SourceFetchError, match="not valid JSON"):
        make_scraper(client).fetch(COMPANY)


def test_rejects_company_from_another_provider(make_http_client):
    lever_company = COMPANY.model_copy(update={"ats": ATSProvider.LEVER})
    client = make_http_client(lambda request: httpx.Response(200, json={"jobs": []}))

    with pytest.raises(ValueError):
        make_scraper(client).fetch(lever_company)
