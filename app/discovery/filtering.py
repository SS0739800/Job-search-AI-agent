"""Deciding whether a normalized posting is relevant to the candidate."""

import re
from dataclasses import dataclass

from app.discovery.locations import LocationClassifier, LocationMatch
from app.discovery.terms import TermMatcher
from app.schemas.job import NormalizedJob
from app.schemas.preferences import JobPreferences

_YEAR_PATTERN = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


@dataclass(frozen=True)
class FilterDecision:
    is_relevant: bool
    role_category: str | None
    location_match: LocationMatch
    # Every reason the posting was rejected (empty when relevant). All reasons
    # are collected, not just the first, to make tuning the rules easier.
    rejection_reasons: tuple[str, ...]


class JobFilter:
    """Applies config/job_preferences.yaml rules to NormalizedJob objects.

    Matchers are compiled once here and reused for every posting.
    """

    def __init__(self, preferences: JobPreferences) -> None:
        titles = preferences.titles
        self._early_career = TermMatcher(titles.early_career_terms)
        self._target_years = {str(year) for year in titles.target_years}
        self._role_categories = {
            category: TermMatcher(terms) for category, terms in titles.role_categories.items()
        }
        self._exclusions = {
            group: TermMatcher(terms) for group, terms in titles.excluded_title_terms.items()
        }
        self._non_software = TermMatcher(titles.non_software_terms)
        self._software_signal = TermMatcher(titles.software_signal_terms)
        self._locations = LocationClassifier(preferences.locations)

    def role_category(self, title: str) -> str | None:
        for category, matcher in self._role_categories.items():
            if matcher.find(title):
                return category
        return None

    def evaluate(self, job: NormalizedJob) -> FilterDecision:
        title = job.title
        reasons: list[str] = []

        # Lever/Ashby report employment type ("Internship/Co-op", "Intern"),
        # which catches interns whose title doesn't say so.
        if not (self._early_career.find(title) or self._early_career.find(job.employment_type)):
            reasons.append("not an internship or co-op")

        role_category = self.role_category(title)
        if role_category is None:
            reasons.append("no matching role keyword")

        for group, matcher in self._exclusions.items():
            term = matcher.find(title)
            if term:
                reasons.append(f"excluded {group} term '{term}'")

        non_software_term = self._non_software.find(title)
        if non_software_term and not self._software_signal.find(title):
            reasons.append(f"non-software role term '{non_software_term}'")

        years = set(_YEAR_PATTERN.findall(title))
        if years and self._target_years and not years & self._target_years:
            reasons.append(f"title targets {', '.join(sorted(years))}")

        location_match = self._locations.classify(job)
        if location_match is LocationMatch.NON_US:
            reasons.append("location outside the US")

        return FilterDecision(
            is_relevant=not reasons,
            role_category=role_category,
            location_match=location_match,
            rejection_reasons=tuple(reasons),
        )
