"""Classifying a posting's location as US / non-US / priority hub."""

import re
from enum import StrEnum

from app.discovery.terms import TermMatcher
from app.schemas.job import NormalizedJob, WorkplaceType
from app.schemas.preferences import LocationRules

_US_STATE_CODES = (
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT "
    "NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY"
).split()

_US_STATE_NAMES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut",
    "Delaware", "District of Columbia", "Florida", "Georgia", "Hawaii", "Idaho", "Illinois",
    "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland",
    "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana",
    "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania",
    "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah",
    "Vermont", "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
    "United States", "United States of America",
]

# State codes must follow a comma ("Austin, TX") and are case-sensitive, so
# words like "in", "or" and "me" are never mistaken for Indiana/Oregon/Maine.
_US_STATE_CODE_PATTERN = re.compile(r",\s*(?:" + "|".join(_US_STATE_CODES) + r")(?![A-Za-z])")
_US_ABBREVIATION_PATTERN = re.compile(r"(?<![A-Za-z])(?:US|USA|U\.S\.A?\.?)(?![A-Za-z])")


class LocationMatch(StrEnum):
    PRIORITY_HUB = "priority_hub"  # a preferred US tech hub
    US = "us"                      # another US location
    REMOTE = "remote"              # remote, not tied to a non-US country
    UNKNOWN = "unknown"            # can't tell; kept and flagged
    NON_US = "non_us"              # no US location, and at least one clearly non-US


class LocationClassifier:
    def __init__(self, rules: LocationRules) -> None:
        self._priority = TermMatcher(rules.priority_terms)
        self._non_us = TermMatcher(rules.non_us_terms)
        self._us_state_names = TermMatcher(_US_STATE_NAMES)

    def is_us(self, location: str) -> bool:
        strong_evidence = bool(
            _US_ABBREVIATION_PATTERN.search(location)
            or self._us_state_names.find(location)
            or self._priority.find(location)  # priority hubs are all US cities
        )
        if strong_evidence:
            return True
        # A two-letter code is weak evidence: in "Toronto, ON, CA" the "CA" is
        # Canada, not California. It counts only if nothing says non-US.
        return bool(_US_STATE_CODE_PATTERN.search(location)) and not self._non_us.find(location)

    def is_non_us(self, location: str) -> bool:
        return bool(self._non_us.find(location)) and not self.is_us(location)

    def classify(self, job: NormalizedJob) -> LocationMatch:
        # Check both the display text and the structured list: some boards put
        # the real cities in one and only "US" or "Remote Zone 1" in the other.
        locations = list(dict.fromkeys([*job.locations, *([job.location] if job.location else [])]))

        # A job listed in several places is kept if ANY of them is in the US.
        if any(self._priority.find(location) for location in locations):
            return LocationMatch.PRIORITY_HUB
        if any(self.is_us(location) for location in locations) or job.country == "US":
            return LocationMatch.REMOTE if job.workplace_type is WorkplaceType.REMOTE else LocationMatch.US
        # No location is in the US. Texts like "In-Office" or "Hybrid" carry no
        # geography, so one clearly non-US location is enough to reject.
        if any(self.is_non_us(location) for location in locations):
            return LocationMatch.NON_US
        if job.country is not None:
            # Provider names a country, it is not the US, and no location says US.
            return LocationMatch.NON_US
        if job.workplace_type is WorkplaceType.REMOTE:
            return LocationMatch.REMOTE
        return LocationMatch.UNKNOWN
