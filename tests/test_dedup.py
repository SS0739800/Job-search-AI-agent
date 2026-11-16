from datetime import UTC, datetime

import pytest

from app.discovery.dedup import content_hash, job_fingerprint, normalize_url
from app.schemas.company import ATSProvider
from app.schemas.job import NormalizedJob, WorkplaceType


@pytest.mark.parametrize(
    ("first", "second"),
    [
        # Apply page vs job page, trailing slash, www, scheme
        ("https://jobs.lever.co/zoox/abc/apply", "https://jobs.lever.co/zoox/abc"),
        ("https://jobs.ashbyhq.com/notion/abc/application", "http://jobs.ashbyhq.com/notion/abc/"),
        ("https://www.mongodb.com/careers/job/?gh_jid=1", "https://mongodb.com/careers/job?gh_jid=1"),
        # Tracking parameters dropped, order of others irrelevant
        ("https://x.com/job?gh_jid=1&utm_source=li", "https://x.com/job?gh_jid=1"),
        ("https://x.com/job?b=2&a=1&gh_src=abc", "https://x.com/job?a=1&b=2"),
        ("https://x.com/job#apply", "https://x.com/job"),
    ],
)
def test_equivalent_urls_normalize_identically(first, second):
    assert normalize_url(first) == normalize_url(second)


def test_identifying_query_parameters_are_kept():
    assert normalize_url("https://x.com/job?gh_jid=1") != normalize_url("https://x.com/job?gh_jid=2")


def test_fingerprint_ignores_case_and_punctuation():
    assert job_fingerprint("Stripe", "Software Engineer, Intern", "New York", []) == job_fingerprint(
        "stripe", "software engineer intern", "new york", []
    )


def test_fingerprint_distinguishes_locations():
    assert job_fingerprint("Palantir", "SWE Intern", "New York, NY", []) != job_fingerprint(
        "Palantir", "SWE Intern", "Denver, CO", []
    )


def test_fingerprint_uses_structured_locations_when_display_text_is_vague():
    lisbon = job_fingerprint("Cloudflare", "SWE Intern", "In-Office", ["Lisboa, Portugal"])
    austin = job_fingerprint("Cloudflare", "SWE Intern", "In-Office", ["Austin, TX, United States"])

    assert lisbon != austin


def make_posting(**overrides) -> NormalizedJob:
    fields = {
        "job_id": "lever:x:1", "source": ATSProvider.LEVER, "source_job_id": "1",
        "company": "X", "title": "SWE Intern", "location": "Boston, MA", "locations": ["Boston, MA"],
        "employment_type": "Intern", "workplace_type": WorkplaceType.ONSITE, "department": None,
        "description": "Build things.", "posted_at": None, "updated_at": None,
        "application_url": "https://x.com/1", "original_job_url": "https://x.com/1",
        "fetched_at": datetime(2026, 11, 16, tzinfo=UTC),
    }
    return NormalizedJob(**{**fields, **overrides})


def test_content_hash_ignores_fetch_time_and_provider_updated_at():
    original = make_posting()
    refetched = make_posting(
        fetched_at=datetime(2026, 11, 17, tzinfo=UTC), updated_at=datetime(2026, 11, 17, tzinfo=UTC)
    )

    assert content_hash(original) == content_hash(refetched)


def test_content_hash_changes_when_description_changes():
    assert content_hash(make_posting()) != content_hash(make_posting(description="New text."))
