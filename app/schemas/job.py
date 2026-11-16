"""The common job posting format every ATS adapter produces."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.company import ATSProvider


class WorkplaceType(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class NormalizedJob(BaseModel):
    """A job posting after mapping a provider-specific payload into one shape.

    Fields are only filled with what the provider actually reported. When a
    provider does not supply something (e.g. Greenhouse has no standard
    employment type field), the value stays None instead of being guessed.
    """

    model_config = ConfigDict(frozen=True)

    # Stable key across runs: "{source}:{board_id}:{source_job_id}"
    job_id: str
    source: ATSProvider
    source_job_id: str
    company: str
    title: str = Field(min_length=1)
    # Location as displayed by the employer, plus individual locations when the
    # provider lists them separately (used for location filtering later).
    location: str | None
    locations: list[str] = Field(default_factory=list)
    # Country when the provider reports one. The US is always "US"; other
    # countries are kept as reported (e.g. "GB" from Lever, "Canada" from Ashby).
    country: str | None = None
    # Provider's own wording, e.g. Lever's "Internship/Co-op" or "Full-time".
    employment_type: str | None
    workplace_type: WorkplaceType
    department: str | None
    description: str | None
    posted_at: datetime | None
    updated_at: datetime | None
    application_url: str
    original_job_url: str
    # When this fetch happened. The database (next step) keeps the first time
    # a job was ever seen as its "date discovered".
    fetched_at: datetime
