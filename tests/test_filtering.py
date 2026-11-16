"""Filter tests against the real config/job_preferences.yaml.

Titles and locations below come from real postings seen during development.
If you deliberately change job_preferences.yaml, update the affected cases.
"""

from datetime import UTC, datetime

import pytest

from app.config import load_job_preferences
from app.discovery.filtering import JobFilter
from app.discovery.locations import LocationMatch
from app.schemas.company import ATSProvider
from app.schemas.job import NormalizedJob, WorkplaceType


@pytest.fixture(scope="module")
def job_filter() -> JobFilter:
    return JobFilter(load_job_preferences())


def make_job(
    title: str,
    location: str | None = "New York, NY",
    locations: list[str] | None = None,
    *,
    employment_type: str | None = None,
    country: str | None = None,
    workplace_type: WorkplaceType = WorkplaceType.UNKNOWN,
) -> NormalizedJob:
    return NormalizedJob(
        job_id="greenhouse:test:1",
        source=ATSProvider.GREENHOUSE,
        source_job_id="1",
        company="Test Co",
        title=title,
        location=location,
        locations=locations if locations is not None else ([location] if location else []),
        country=country,
        employment_type=employment_type,
        workplace_type=workplace_type,
        department=None,
        description=None,
        posted_at=None,
        updated_at=None,
        application_url="https://example.com/apply",
        original_job_url="https://example.com/job",
        fetched_at=datetime(2026, 11, 16, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("title", "category"),
    [
        ("2027 - Software Engineering Intern, AMER", "software_engineering"),
        ("Software Engineer Intern, Backend (Summer 2027 - SF)", "backend"),
        ("Data Analyst, Intern", "data_analytics"),
        ("Analytics Engineer Intern", "data_analytics"),
        ("Data Engineer Intern (2027)", "data_engineering"),
        ("Data Science Intern (2027 Start)", "data_science"),
        ("Master's Machine Learning Engineer, Intern", "machine_learning"),
        ("Software Engineering Co-op (Spring 2027)", "software_engineering"),
        ("Full-Stack Developer Intern", "full_stack"),
        ("Python Developer Intern", "python"),
        ("Privacy and Civil Liberties Software Engineer, Internship", "software_engineering"),
        ("Sales Analytics Intern 2027 (USA)", "data_analytics"),
    ],
)
def test_relevant_titles(job_filter, title, category):
    decision = job_filter.evaluate(make_job(title))

    assert decision.is_relevant, decision.rejection_reasons
    assert decision.role_category == category


@pytest.mark.parametrize(
    ("title", "expected_reason"),
    [
        ("Senior Software Engineer", "not an internship or co-op"),
        ("Internal Audit Manager", "not an internship or co-op"),
        ("Product Design Intern (2027)", "no matching role keyword"),
        ("Staff Software Engineer, Intern Program", "excluded seniority term 'Staff'"),
        ("PhD Machine Learning Engineer, Intern", "excluded education term 'PhD'"),
        ("High School Internship, Software Engineering (Summer 2027)", "excluded education term 'High School'"),
        ("Hardware Engineer Intern, Vehicle Systems [Summer 2027]", "non-software role term 'Hardware'"),
        ("Software Engineer Intern (Summer 2026)", "title targets 2026"),
    ],
)
def test_rejected_titles(job_filter, title, expected_reason):
    decision = job_filter.evaluate(make_job(title))

    assert not decision.is_relevant
    assert expected_reason in decision.rejection_reasons


def test_employment_type_identifies_interns_without_intern_in_title(job_filter):
    decision = job_filter.evaluate(make_job("Software Engineer", employment_type="Internship/Co-op"))

    assert decision.is_relevant


def test_all_rejection_reasons_are_reported(job_filter):
    decision = job_filter.evaluate(make_job("Senior Product Manager", location="London, United Kingdom"))

    assert decision.rejection_reasons == (
        "not an internship or co-op",
        "no matching role keyword",
        "excluded seniority term 'Senior'",  # one reason per exclusion group
        "location outside the US",
    )


@pytest.mark.parametrize(
    ("location", "locations", "kwargs", "expected"),
    [
        ("Austin; New York City; San Francisco", None, {}, LocationMatch.PRIORITY_HUB),
        ("Honolulu, HI", None, {}, LocationMatch.US),
        ("Remote - US", None, {"workplace_type": WorkplaceType.REMOTE}, LocationMatch.REMOTE),
        ("Remote", None, {"workplace_type": WorkplaceType.REMOTE}, LocationMatch.REMOTE),
        ("In-Office", None, {}, LocationMatch.UNKNOWN),
        ("Dublin", None, {}, LocationMatch.NON_US),
        ("Remote - Canada", None, {"workplace_type": WorkplaceType.REMOTE}, LocationMatch.NON_US),
        # "CA" here is Canada, not California.
        ("Toronto, ON, CA", None, {}, LocationMatch.NON_US),
        # Provider gives a country but no recognisable location text.
        ("Office", None, {"country": "GB"}, LocationMatch.NON_US),
        ("Office", None, {"country": "US"}, LocationMatch.US),
        # Real cities only in the display text; the office list just says "US".
        ("San Francisco, Seattle, New York City", ["US"], {}, LocationMatch.PRIORITY_HUB),
        # Display text has no geography; the office list does.
        ("In-Office", ["Lisboa, Lisboa, Portugal"], {}, LocationMatch.NON_US),
        # Kept when ANY listed location is in the US.
        ("London; New York", ["London, United Kingdom", "New York, NY"], {}, LocationMatch.PRIORITY_HUB),
    ],
)
def test_location_classification(job_filter, location, locations, kwargs, expected):
    job = make_job("Software Engineer Intern", location, locations, **kwargs)

    assert job_filter.evaluate(job).location_match is expected
