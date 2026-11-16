"""Behaviour shared by every ATS adapter: HTTP, retries and error reporting."""

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx
from pydantic import ValidationError

from app.schemas.company import ATSProvider, CompanyConfig
from app.schemas.job import NormalizedJob

logger = logging.getLogger(__name__)

# Status codes that usually mean "try again later" rather than "this is wrong".
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class SourceFetchError(Exception):
    """A job board could not be fetched, or its response could not be understood.

    The discovery pipeline catches this per company and records the source as
    failed, so a temporary outage never makes jobs look like they were removed.
    """

    def __init__(self, company: CompanyConfig, message: str, *, retryable: bool) -> None:
        super().__init__(f"{company.name} ({company.ats}:{company.board_id}): {message}")
        self.company = company
        self.retryable = retryable


@dataclass(frozen=True)
class FetchResult:
    company: CompanyConfig
    jobs: list[NormalizedJob]
    fetched_at: datetime
    # Postings present in the response but dropped because they failed validation.
    skipped_postings: int = 0


class JobBoardScraper(ABC):
    """Base class for a provider adapter.

    Subclasses describe *what* to request (build_request), *where* the postings
    are in the response (extract_postings) and *how* to map one posting
    (normalize_posting). Fetching, retrying, error classification and skipping
    malformed postings happen here once for all providers.
    """

    provider: ClassVar[ATSProvider]

    def __init__(
        self,
        http_client: httpx.Client,
        *,
        max_retries: int = 2,
        backoff_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http_client
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep

    def fetch(self, company: CompanyConfig) -> FetchResult:
        if company.ats is not self.provider:
            raise ValueError(f"{type(self).__name__} cannot fetch {company.ats} board for {company.name}")
        url, params = self.build_request(company)
        payload = self._get_json(company, url, params)
        return self.parse_payload(company, payload, fetched_at=datetime.now(UTC))

    @abstractmethod
    def build_request(self, company: CompanyConfig) -> tuple[str, dict[str, str]]:
        """Return the URL and query parameters for the company's job board."""

    @abstractmethod
    def extract_postings(self, company: CompanyConfig, payload: Any) -> list[Any]:
        """Return the list of raw postings, or raise SourceFetchError if the
        response does not have the expected overall shape."""

    @abstractmethod
    def normalize_posting(
        self, company: CompanyConfig, raw_posting: Any, fetched_at: datetime
    ) -> NormalizedJob:
        """Validate one raw posting and map it to a NormalizedJob.

        Raises pydantic.ValidationError when the posting is malformed.
        """

    def parse_payload(
        self, company: CompanyConfig, payload: Any, *, fetched_at: datetime
    ) -> FetchResult:
        jobs: list[NormalizedJob] = []
        skipped = 0
        for raw_posting in self.extract_postings(company, payload):
            try:
                jobs.append(self.normalize_posting(company, raw_posting, fetched_at))
            except ValidationError as exc:
                # One bad posting should not hide the rest of the board.
                skipped += 1
                posting_id = raw_posting.get("id") if isinstance(raw_posting, dict) else None
                logger.warning(
                    "Skipping malformed %s posting %s from %s: %d validation error(s)",
                    self.provider, posting_id, company.name, exc.error_count(),
                )
        return FetchResult(company=company, jobs=jobs, fetched_at=fetched_at, skipped_postings=skipped)

    def _get_json(self, company: CompanyConfig, url: str, params: dict[str, str]) -> Any:
        total_attempts = self._max_retries + 1
        for attempt in range(1, total_attempts + 1):
            try:
                response = self._http.get(url, params=params)
            except httpx.TransportError as exc:  # connection errors and timeouts
                error = SourceFetchError(company, f"network error: {exc!r}", retryable=True)
            else:
                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise SourceFetchError(
                            company, "response was not valid JSON", retryable=False
                        ) from exc

                retryable = response.status_code in RETRYABLE_STATUS_CODES
                hint = " (board not found - check board_id)" if response.status_code == 404 else ""
                error = SourceFetchError(
                    company, f"HTTP {response.status_code}{hint}", retryable=retryable
                )
                if not retryable:
                    raise error

            if attempt < total_attempts:
                delay = self._backoff_seconds * 2 ** (attempt - 1)
                logger.warning(
                    "%s; retrying in %.1fs (attempt %d/%d)", error, delay, attempt, total_attempts
                )
                self._sleep(delay)

        raise error
