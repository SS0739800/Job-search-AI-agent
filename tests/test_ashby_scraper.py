from datetime import UTC, datetime

import httpx
import pytest

from app.schemas.company import ATSProvider, CompanyConfig
from app.schemas.job import WorkplaceType
from app.scrapers.ashby import AshbyScraper
from app.scrapers.base import SourceFetchError

COMPANY = CompanyConfig(
    name="Example Inc",
    ats=ATSProvider.ASHBY,
    board_id="example",
    careers_url="https://www.example.com/careers",
)


def make_scraper(client: httpx.Client) -> AshbyScraper:
    return AshbyScraper(client, sleep=lambda seconds: None)


@pytest.fixture
def board_result(load_fixture, make_http_client):
    payload = load_fixture("ashby_job_board.json")
    client = make_http_client(lambda request: httpx.Response(200, json=payload))
    return make_scraper(client).fetch(COMPANY)


def test_requests_job_board_endpoint(make_http_client):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"apiVersion": "1", "jobs": []})

    make_scraper(make_http_client(handler)).fetch(COMPANY)

    assert str(seen[0].url) == "https://api.ashbyhq.com/posting-api/job-board/example"


def test_unlisted_postings_are_ignored_and_malformed_are_skipped(board_result):
    titles = [job.title for job in board_result.jobs]

    assert titles == ["Software Engineer Intern (Summer 2027)", "Account Executive"]
    assert board_result.skipped_postings == 1  # the posting without URLs, not the unlisted one


def test_normalizes_full_posting(board_result):
    job = board_result.jobs[0]

    assert job.job_id == "ashby:example:3fba1c39-c5cb-47d7-9ad2-1cec4d7e9d0c"
    assert job.source is ATSProvider.ASHBY
    assert job.location == "San Francisco, California"
    assert job.locations == ["San Francisco, California", "New York, New York"]
    assert job.country == "US"  # "USA" normalized
    assert job.employment_type == "Intern"
    # isRemote is true in the payload, but workplaceType says Hybrid.
    assert job.workplace_type is WorkplaceType.HYBRID
    assert job.department == "Early Career"  # department == team, not repeated
    assert job.posted_at == datetime(2026, 8, 14, 19, 7, 13, 459000, tzinfo=UTC)
    assert job.updated_at is None
    assert job.description == "Who We Are\n\nWe build tools.\n\n- Python\n- TypeScript"
    assert job.application_url.endswith("/application")
    assert job.original_job_url == "https://jobs.ashbyhq.com/example/3fba1c39-c5cb-47d7-9ad2-1cec4d7e9d0c"


def test_null_workplace_type_falls_back_to_location(board_result):
    job = board_result.jobs[1]

    assert job.workplace_type is WorkplaceType.REMOTE
    assert job.employment_type == "Full-time"
    assert job.country == "Canada"
    assert job.department == "Sales - Enterprise"
    assert job.description is None


def test_unknown_board_404_with_html_body_is_not_retried(make_http_client):
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404, text="<html>Not Found</html>")

    with pytest.raises(SourceFetchError, match="board not found") as excinfo:
        make_scraper(make_http_client(handler)).fetch(COMPANY)

    assert excinfo.value.retryable is False
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [{"apiVersion": "1"}, [], {"jobs": None}])
def test_unexpected_response_shape_raises(make_http_client, payload):
    client = make_http_client(lambda request: httpx.Response(200, json=payload))

    with pytest.raises(SourceFetchError, match="unexpected response shape"):
        make_scraper(client).fetch(COMPANY)
