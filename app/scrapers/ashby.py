"""Ashby public Job Posting API adapter.

API: GET https://api.ashbyhq.com/posting-api/job-board/{job_board_name}
No authentication. Returns {"apiVersion": "1", "jobs": [...]}. An unknown
board returns 404 with a non-JSON body.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.company import ATSProvider, CompanyConfig
from app.schemas.job import NormalizedJob, WorkplaceType
from app.scrapers.base import JobBoardScraper, SourceFetchError
from app.scrapers.normalization import (
    clean_optional,
    html_to_text,
    infer_workplace_type,
    normalize_country,
    to_utc,
    unique_in_order,
)

API_BASE_URL = "https://api.ashbyhq.com/posting-api/job-board"

# Ashby's isRemote flag is True for hybrid jobs too, so only workplaceType is
# trusted. When it is null, workplace is inferred from location text instead.
_WORKPLACE_TYPES = {
    "onsite": WorkplaceType.ONSITE,
    "remote": WorkplaceType.REMOTE,
    "hybrid": WorkplaceType.HYBRID,
}

_EMPLOYMENT_TYPES = {
    "FullTime": "Full-time",
    "PartTime": "Part-time",
    "Intern": "Intern",
    "Contract": "Contract",
    "Temporary": "Temporary",
}


class AshbyPostalAddress(BaseModel):
    addressCountry: str | None = None


class AshbyAddress(BaseModel):
    postalAddress: AshbyPostalAddress | None = None


class AshbySecondaryLocation(BaseModel):
    location: str | None = None


class AshbyPosting(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    jobUrl: str = Field(min_length=1)
    applyUrl: str = Field(min_length=1)
    department: str | None = None
    team: str | None = None
    employmentType: str | None = None
    location: str | None = None
    secondaryLocations: list[AshbySecondaryLocation] = Field(default_factory=list)
    workplaceType: str | None = None
    address: AshbyAddress | None = None
    publishedAt: datetime | None = None
    descriptionHtml: str | None = None


def _country(posting: AshbyPosting) -> str | None:
    if posting.address and posting.address.postalAddress:
        return normalize_country(posting.address.postalAddress.addressCountry)
    return None


class AshbyScraper(JobBoardScraper):
    provider = ATSProvider.ASHBY

    def build_request(self, company: CompanyConfig) -> tuple[str, dict[str, str]]:
        return f"{API_BASE_URL}/{company.board_id}", {}

    def extract_postings(self, company: CompanyConfig, payload: Any) -> list[Any]:
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise SourceFetchError(
                company, "unexpected response shape: missing 'jobs' list", retryable=False
            )
        # Unlisted postings are hidden from the public board; ignore them.
        return [
            posting for posting in payload["jobs"]
            if not (isinstance(posting, dict) and posting.get("isListed") is False)
        ]

    def normalize_posting(
        self, company: CompanyConfig, raw_posting: Any, fetched_at: datetime
    ) -> NormalizedJob:
        posting = AshbyPosting.model_validate(raw_posting)
        location_text = clean_optional(posting.location)
        locations = unique_in_order(
            [location_text, *(secondary.location for secondary in posting.secondaryLocations)]
        )

        workplace_type = _WORKPLACE_TYPES.get((posting.workplaceType or "").lower())
        if workplace_type is None:
            workplace_type = infer_workplace_type(*locations)

        employment_type = clean_optional(posting.employmentType)
        if employment_type:
            employment_type = _EMPLOYMENT_TYPES.get(employment_type, employment_type)

        department = " - ".join(unique_in_order([posting.department, posting.team])) or None
        description = html_to_text(posting.descriptionHtml) if posting.descriptionHtml else None

        return NormalizedJob(
            job_id=f"{self.provider}:{company.board_id}:{posting.id}",
            source=self.provider,
            source_job_id=posting.id,
            company=company.name,
            title=posting.title.strip(),
            location=location_text,
            locations=locations,
            country=_country(posting),
            employment_type=employment_type,
            workplace_type=workplace_type,
            department=department,
            description=description or None,
            posted_at=to_utc(posting.publishedAt),
            updated_at=None,  # the public Ashby API exposes no last-updated time
            application_url=posting.applyUrl,
            original_job_url=posting.jobUrl,
            fetched_at=fetched_at,
        )
