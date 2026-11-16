"""Greenhouse public Job Board API adapter.

API: GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
No authentication. With content=true each job includes its description (as
entity-escaped HTML), departments and offices.
"""

import html
import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.schemas.company import ATSProvider, CompanyConfig
from app.schemas.job import NormalizedJob
from app.scrapers.base import FetchResult, JobBoardScraper, SourceFetchError
from app.scrapers.normalization import (
    clean_optional,
    html_to_text,
    infer_workplace_type,
    to_utc,
    unique_in_order,
)

logger = logging.getLogger(__name__)

API_BASE_URL = "https://boards-api.greenhouse.io/v1/boards"
HOSTED_BOARD_URL = "https://job-boards.greenhouse.io"


# --- Raw response models: only the fields we use. Unknown fields are ignored,
# --- so Greenhouse adding new fields will not break validation.

class GreenhouseLocation(BaseModel):
    name: str | None = None


class GreenhouseDepartment(BaseModel):
    name: str


class GreenhouseOffice(BaseModel):
    name: str | None = None
    location: str | None = None  # e.g. "Austin, TX, United States"


class GreenhousePosting(BaseModel):
    id: int
    title: str = Field(min_length=1)
    absolute_url: str = Field(min_length=1)
    updated_at: datetime | None = None
    first_published: datetime | None = None
    location: GreenhouseLocation | None = None
    content: str | None = None
    departments: list[GreenhouseDepartment] = Field(default_factory=list)
    offices: list[GreenhouseOffice] = Field(default_factory=list)


class GreenhouseScraper(JobBoardScraper):
    provider = ATSProvider.GREENHOUSE

    def build_request(self, company: CompanyConfig) -> tuple[str, dict[str, str]]:
        return f"{API_BASE_URL}/{company.board_id}/jobs", {"content": "true"}

    def parse_payload(
        self, company: CompanyConfig, payload: Any, *, fetched_at: datetime
    ) -> FetchResult:
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise SourceFetchError(
                company, "unexpected response shape: missing 'jobs' list", retryable=False
            )

        jobs: list[NormalizedJob] = []
        skipped = 0
        for raw_posting in payload["jobs"]:
            try:
                posting = GreenhousePosting.model_validate(raw_posting)
            except ValidationError as exc:
                skipped += 1
                posting_id = raw_posting.get("id") if isinstance(raw_posting, dict) else None
                logger.warning(
                    "Skipping malformed Greenhouse posting %s from %s: %d validation error(s)",
                    posting_id, company.name, exc.error_count(),
                )
                continue
            jobs.append(self._normalize(company, posting, fetched_at))

        return FetchResult(company=company, jobs=jobs, fetched_at=fetched_at, skipped_postings=skipped)

    def _normalize(
        self, company: CompanyConfig, posting: GreenhousePosting, fetched_at: datetime
    ) -> NormalizedJob:
        location_text = clean_optional(posting.location.name if posting.location else None)
        # Offices give structured "City, ST, Country" strings; fall back to
        # splitting the display text ("Austin; New York City") when absent.
        locations = unique_in_order(office.location or office.name for office in posting.offices)
        if not locations and location_text:
            locations = unique_in_order(location_text.split(";"))

        department_names = unique_in_order(department.name for department in posting.departments)
        # Greenhouse double-encodes descriptions: "&lt;p&gt;" -> "<p>" -> text.
        description = html_to_text(html.unescape(posting.content)) if posting.content else None

        return NormalizedJob(
            job_id=f"{self.provider}:{company.board_id}:{posting.id}",
            source=self.provider,
            source_job_id=str(posting.id),
            company=company.name,
            title=posting.title.strip(),
            location=location_text,
            locations=locations,
            employment_type=None,  # Greenhouse has no standard field for this
            workplace_type=infer_workplace_type(location_text, *locations),
            department=", ".join(department_names) or None,
            description=description or None,
            posted_at=to_utc(posting.first_published),
            updated_at=to_utc(posting.updated_at),
            # absolute_url is the employer's own careers page (where you apply);
            # the hosted board URL is a stable reference that survives site redesigns.
            application_url=posting.absolute_url,
            original_job_url=f"{HOSTED_BOARD_URL}/{company.board_id}/jobs/{posting.id}",
            fetched_at=fetched_at,
        )
