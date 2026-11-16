"""Live test against a real Greenhouse board. Run with: pytest -m integration"""

import pytest

from app.config import load_companies
from app.scrapers.greenhouse import GreenhouseScraper
from app.scrapers.http import create_http_client

pytestmark = pytest.mark.integration


def test_fetches_real_postings_from_registry_board():
    company = next(c for c in load_companies() if c.board_id == "mongodb")

    with create_http_client() as client:
        result = GreenhouseScraper(client).fetch(company)

    assert result.jobs, "expected a live board to have at least one posting"
    assert result.skipped_postings == 0
    job_ids = [job.job_id for job in result.jobs]
    assert len(job_ids) == len(set(job_ids))
    for job in result.jobs:
        assert job.job_id.startswith("greenhouse:mongodb:")
        assert job.title
        assert job.application_url.startswith("https://")
        assert job.updated_at is not None and job.updated_at.tzinfo is not None
    assert any(job.description for job in result.jobs)
