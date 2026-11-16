"""Helpers for turning provider data into clean, comparable values."""

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from html.parser import HTMLParser

from app.schemas.job import WorkplaceType

_BLOCK_TAGS = frozenset(
    {"p", "div", "br", "ul", "ol", "table", "tr", "section", "article", "blockquote",
     "h1", "h2", "h3", "h4", "h5", "h6"}
)
_SKIPPED_TAGS = frozenset({"script", "style"})
# Some boards (e.g. Ashby) wrap bullet text in <p>: <li><p>Python</p></li>.
# Inside a list item these are treated as inline so the bullet stays on one line.
_INLINE_INSIDE_LIST_ITEM = frozenset({"p", "div"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._list_item_depth = 0

    def _is_inline_in_list_item(self, tag: str) -> bool:
        return self._list_item_depth > 0 and tag in _INLINE_INSIDE_LIST_ITEM

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1
        elif tag == "li":
            self._list_item_depth += 1
            self.parts.append("\n- ")
        elif tag in _BLOCK_TAGS and not self._is_inline_in_list_item(tag):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag == "li":
            self._list_item_depth = max(0, self._list_item_depth - 1)
        elif tag in _BLOCK_TAGS and tag != "br" and not self._is_inline_in_list_item(tag):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            # Like a browser: whitespace inside text collapses to one space.
            self.parts.append(re.sub(r"\s+", " ", data))


def html_to_text(markup: str) -> str:
    """Convert job description HTML to readable plain text.

    Paragraphs are separated by blank lines and list items become "- " bullets,
    which keeps descriptions readable for humans and for Claude in Phase 2.
    """
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    lines = (line.strip() for line in "".join(parser.parts).split("\n"))
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def to_utc(value: datetime | None) -> datetime | None:
    """Store every timestamp in UTC so comparisons across providers are safe."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def infer_workplace_type(*location_texts: str | None) -> WorkplaceType:
    """Infer remote/hybrid only from explicit wording in location fields.

    Job descriptions are deliberately not used: phrases like "remote-friendly
    team" are too ambiguous. Anything not explicit stays UNKNOWN rather than
    being assumed to be onsite.
    """
    combined = " ".join(text for text in location_texts if text).lower()
    if re.search(r"\bhybrid\b", combined):
        return WorkplaceType.HYBRID
    if re.search(r"\bremote\b", combined):
        return WorkplaceType.REMOTE
    return WorkplaceType.UNKNOWN


_US_COUNTRY_NAMES = frozenset(
    {"us", "u.s.", "usa", "u.s.a.", "united states", "united states of america"}
)


def normalize_country(value: str | None) -> str | None:
    """Map the many spellings of the United States to "US".

    Providers disagree (Lever: "US", Ashby: "United States" or "USA"). Only the
    US needs a single canonical value for location filtering; other countries
    are kept as reported.
    """
    cleaned = clean_optional(value)
    if cleaned and cleaned.lower() in _US_COUNTRY_NAMES:
        return "US"
    return cleaned


def clean_optional(value: str | None) -> str | None:
    """Strip whitespace and turn empty strings into None."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def unique_in_order(values: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = clean_optional(value)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result
