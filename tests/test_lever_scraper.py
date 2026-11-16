from datetime import UTC, datetime

import httpx
import pytest

from app.schemas.company import ATSProvider, CompanyConfig
from app.schemas.job import WorkplaceType
from app.scrapers.base import SourceFetchError
from app.scrapers.lever import LeverScraper

COMPANY = CompanyConfig(
    name="Example Co",
    ats=ATSProvider.LEVER,
    board_id="example",
    careers_url="https://www.example.com/careers",
)


def make_scraper(client: httpx.Client) -> LeverScraper:
    return LeverScraper(client, sleep=lambda seconds: None)


@pytest.fixture
def postings_result(load_fixture, make_http_client):
    payload = load_fixture("lever_postings.json")
    client = make_http_client(lambda request: httpx.Response(200, json=payload))
    return make_scraper(client).fetch(COMPANY)


def test_requests_postings_endpoint_in_json_mode(make_http_client):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    result = make_scraper(make_http_client(handler)).fetch(COMPANY)

    assert str(seen[0].url) == "https://api.lever.co/v0/postings/example?mode=json"
    assert result.jobs == []


def test_valid_postings_are_normalized_and_malformed_are_skipped(postings_result):
    assert len(postings_result.jobs) == 2
    assert postings_result.skipped_postings == 1


def test_normalizes_full_posting(postings_result):
    job = postings_result.jobs[0]

    assert job.job_id == "lever:example:85c6aec7-8da2-445d-9c4d-812365dbce97"
    assert job.source is ATSProvider.LEVER
    assert job.title == "Data Science Intern [Summer 2027]"
    assert job.location == "Foster City, CA"
    assert job.locations == ["Foster City, CA", "Boston, MA"]
    assert job.country == "US"
    assert job.employment_type == "Internship/Co-op"
    assert job.workplace_type is WorkplaceType.HYBRID
    assert job.department == "Example Internships - Data Science"
    assert job.posted_at == datetime(2026, 11, 6, 23, 14, 17, 184000, tzinfo=UTC)
    assert job.updated_at is None
    assert job.application_url.endswith("/apply")
    assert job.original_job_url == "https://jobs.lever.co/example/85c6aec7-8da2-445d-9c4d-812365dbce97"


def test_description_includes_lists_and_additional_sections(postings_result):
    assert postings_result.jobs[0].description == (
        "About Our Internship Program\nHands-on experience.\n\n"
        "Qualifications\n\n- Proficiency in Python and SQL\n- Coursework in statistics\n\n"
        "Bonus & Extras\n\n- Spark\n\n"
        "Compensation\n\n$6,500 to $9,500 per month."
    )


def test_sparse_posting_falls_back_to_location_for_workplace(postings_result):
    job = postings_result.jobs[1]

    assert job.workplace_type is WorkplaceType.REMOTE  # "unspecified" -> inferred from "Remote - US"
    assert job.locations == ["Remote - US"]
    assert job.employment_type is None
    assert job.department is None
    assert job.description is None
    assert job.posted_at is None
    assert job.country is None


def test_unknown_site_is_not_retried(make_http_client):
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404, json={"ok": False, "error": "Document not found"})

    with pytest.raises(SourceFetchError, match="board not found") as excinfo:
        make_scraper(make_http_client(handler)).fetch(COMPANY)

    assert excinfo.value.retryable is False
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [{"ok": False, "error": "oops"}, {"jobs": []}, "text"])
def test_unexpected_response_shape_raises(make_http_client, payload):
    client = make_http_client(lambda request: httpx.Response(200, json=payload))

    with pytest.raises(SourceFetchError, match="unexpected response shape"):
        make_scraper(client).fetch(COMPANY)
