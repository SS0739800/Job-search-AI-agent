"""Live test against a real Lever board. Run with: pytest -m integration"""

import pytest

from app.config import load_companies
from app.scrapers.http import create_http_client
from app.scrapers.lever import LeverScraper

pytestmark = pytest.mark.integration


def test_fetches_real_postings_from_registry_board():
    company = next(c for c in load_companies() if c.board_id == "palantir")

    with create_http_client() as client:
        result = LeverScraper(client).fetch(company)

    assert result.jobs, "expected a live board to have at least one posting"
    assert result.skipped_postings == 0
    job_ids = [job.job_id for job in result.jobs]
    assert len(job_ids) == len(set(job_ids))
    for job in result.jobs:
        assert job.job_id.startswith("lever:palantir:")
        assert job.title
        assert job.application_url.startswith("https://jobs.lever.co/palantir/")
        assert job.posted_at is not None and job.posted_at.tzinfo is not None
    assert any(job.description for job in result.jobs)
