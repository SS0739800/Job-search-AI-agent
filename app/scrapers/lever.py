"""Lever public Postings API adapter.

API: GET https://api.lever.co/v0/postings/{site}?mode=json
No authentication. Returns a JSON list of published postings. An unknown site
returns 404; a known site with no openings returns 200 with an empty list.
"""

import html
from datetime import UTC, datetime
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
    unique_in_order,
)

API_BASE_URL = "https://api.lever.co/v0/postings"

# Lever reports workplace type directly; "unspecified" (or anything new) falls
# back to inferring from the location text.
_WORKPLACE_TYPES = {
    "onsite": WorkplaceType.ONSITE,
    "remote": WorkplaceType.REMOTE,
    "hybrid": WorkplaceType.HYBRID,
}


class LeverCategories(BaseModel):
    commitment: str | None = None  # e.g. "Internship/Co-op", "Full-time"
    department: str | None = None
    team: str | None = None
    location: str | None = None
    allLocations: list[str] = Field(default_factory=list)


class LeverList(BaseModel):
    """A titled section such as "Qualifications", with <li> items as HTML."""

    text: str = ""
    content: str = ""


class LeverPosting(BaseModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)  # the job title
    hostedUrl: str = Field(min_length=1)
    applyUrl: str = Field(min_length=1)
    createdAt: int | None = None  # epoch milliseconds
    categories: LeverCategories = Field(default_factory=LeverCategories)
    country: str | None = None
    workplaceType: str | None = None
    description: str | None = None
    lists: list[LeverList] = Field(default_factory=list)
    additional: str | None = None


def build_full_description_html(posting: LeverPosting) -> str:
    """Join Lever's description pieces into one HTML document.

    Lever keeps only the intro in `description`; responsibilities and
    requirements live in `lists`, and compensation/benefits in `additional`.
    """
    sections = [posting.description or ""]
    for section in posting.lists:
        heading = f"<h3>{html.escape(section.text)}</h3>" if section.text.strip() else ""
        sections.append(f"{heading}<ul>{section.content}</ul>")
    sections.append(posting.additional or "")
    return "".join(sections)


class LeverScraper(JobBoardScraper):
    provider = ATSProvider.LEVER

    def build_request(self, company: CompanyConfig) -> tuple[str, dict[str, str]]:
        return f"{API_BASE_URL}/{company.board_id}", {"mode": "json"}

    def extract_postings(self, company: CompanyConfig, payload: Any) -> list[Any]:
        if not isinstance(payload, list):
            raise SourceFetchError(
                company, "unexpected response shape: expected a list of postings", retryable=False
            )
        return payload

    def normalize_posting(
        self, company: CompanyConfig, raw_posting: Any, fetched_at: datetime
    ) -> NormalizedJob:
        posting = LeverPosting.model_validate(raw_posting)
        categories = posting.categories
        location_text = clean_optional(categories.location)
        locations = unique_in_order([*categories.allLocations, location_text])

        workplace_type = _WORKPLACE_TYPES.get((posting.workplaceType or "").lower())
        if workplace_type is None:
            workplace_type = infer_workplace_type(location_text, *locations)

        department = " - ".join(
            unique_in_order([categories.department, categories.team])
        ) or None
        description = html_to_text(build_full_description_html(posting))
        posted_at = (
            datetime.fromtimestamp(posting.createdAt / 1000, tz=UTC)
            if posting.createdAt is not None
            else None
        )

        return NormalizedJob(
            job_id=f"{self.provider}:{company.board_id}:{posting.id}",
            source=self.provider,
            source_job_id=posting.id,
            company=company.name,
            title=posting.text.strip(),
            location=location_text,
            locations=locations,
            country=normalize_country(posting.country),
            employment_type=clean_optional(categories.commitment),
            workplace_type=workplace_type,
            department=department,
            description=description or None,
            posted_at=posted_at,
            updated_at=None,  # the public Lever API exposes no last-updated time
            application_url=posting.applyUrl,
            original_job_url=posting.hostedUrl,
            fetched_at=fetched_at,
        )
