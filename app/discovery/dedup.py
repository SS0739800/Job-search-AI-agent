"""Identity helpers for duplicate detection and change tracking.

Three levels of "same job":
  1. job_key      - same provider posting (exact, e.g. "lever:zoox:<uuid>")
  2. fingerprint  - same company + title + location, from any source
  3. normalized_url - same application URL once tracking noise is removed
Levels 2 and 3 catch the same job appearing under different IDs or sources.
"""

import hashlib
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.schemas.job import NormalizedJob

# Query parameters that only track where a click came from.
_TRACKING_PARAMS = frozenset(
    {"gh_src", "source", "src", "ref", "referrer", "lever-source", "lever-origin", "utm"}
)
# Apply-page suffixes; "/jobs/123/apply" is the same job as "/jobs/123".
_APPLY_SUFFIXES = ("/apply", "/application")


def normalize_url(url: str) -> str:
    """Canonical form of a job URL for comparison.

    Identifying query parameters are kept (Greenhouse company pages use
    "?gh_jid=123" as the job identifier); tracking ones are dropped.
    """
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    for suffix in _APPLY_SUFFIXES:
        if path.lower().endswith(suffix):
            path = path[: -len(suffix)]
    query = sorted(
        (key, value)
        for key, value in parse_qsl(parts.query)
        if key.lower() not in _TRACKING_PARAMS and not key.lower().startswith("utm_")
    )
    return urlunsplit(("https", host, path, urlencode(query), ""))


def _normalize_text(value: str | None) -> str:
    """Lowercase words only: "Software Engineer, Intern" == "software engineer intern"."""
    return " ".join(re.findall(r"[a-z0-9]+", (value or "").lower()))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def job_fingerprint(company: str, title: str, location: str | None, locations: list[str]) -> str:
    """Company + title + where.

    Both the display text and the structured location list are included,
    because either one alone can be vague: Cloudflare's display text is just
    "In-Office", while Stripe's office list is just "US". Combined, two
    postings only match when both agree.
    """
    where = [_normalize_text(location), *sorted(_normalize_text(item) for item in locations)]
    parts = (_normalize_text(company), _normalize_text(title), ";".join(where))
    return _sha256("|".join(parts))


def content_hash(job: NormalizedJob) -> str:
    """Hash of the fields whose change means "this posting was updated".

    fetched_at is excluded (it changes every run) and so is provider
    updated_at (Greenhouse bumps it without visible changes).
    """
    tracked = job.model_dump(
        mode="json",
        include={
            "title", "location", "locations", "country", "employment_type", "workplace_type",
            "department", "description", "posted_at", "application_url",
        },
    )
    return _sha256(json.dumps(tracked, sort_keys=True))
