"""Company registry entries loaded from config/companies.yaml."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ATSProvider(StrEnum):
    """Applicant tracking systems we can read public job boards from."""

    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"


class CompanyConfig(BaseModel):
    """One employer and where its public job board lives."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    ats: ATSProvider
    # The identifier the ATS uses in its public API URL, e.g. "mongodb" in
    # https://boards-api.greenhouse.io/v1/boards/mongodb/jobs
    board_id: str = Field(min_length=1, pattern=r"^[^\s/]+$")
    careers_url: HttpUrl
    active: bool = True
