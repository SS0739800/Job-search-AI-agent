"""Job relevance rules loaded from config/job_preferences.yaml."""

from pydantic import BaseModel, ConfigDict, Field


class TitleRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    early_career_terms: list[str] = Field(min_length=1)
    target_years: list[int] = Field(default_factory=list)
    # Ordered: the first category with a matching term wins.
    role_categories: dict[str, list[str]] = Field(min_length=1)
    # Always reject (seniority, education, ...), grouped for clearer reasons.
    excluded_title_terms: dict[str, list[str]] = Field(default_factory=dict)
    # Reject only when the title has none of software_signal_terms.
    non_software_terms: list[str] = Field(default_factory=list)
    software_signal_terms: list[str] = Field(default_factory=list)


class LocationRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority_terms: list[str] = Field(default_factory=list)
    non_us_terms: list[str] = Field(default_factory=list)


class JobPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titles: TitleRules
    locations: LocationRules
