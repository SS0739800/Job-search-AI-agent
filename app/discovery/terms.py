"""Whole-word, case-insensitive matching of configured terms."""

import re
from collections.abc import Iterable


def _term_pattern(term: str) -> str:
    # Spaces/hyphens inside a term are flexible: "co op" matches "co-op" and "coop".
    parts = [re.escape(part) for part in re.split(r"[\s\-]+", term.strip()) if part]
    return r"[\s\-]*".join(parts)


class TermMatcher:
    """Finds the first configured term that appears as a whole word.

    "Whole word" uses lookarounds instead of \\b so terms ending in punctuation
    (like "sr.") still work: the term must not touch another letter or digit.
    """

    def __init__(self, terms: Iterable[str]) -> None:
        unique_terms = {term.strip() for term in terms if term and term.strip()}
        # Longest first, so "data analytics" is preferred over "analytics".
        ordered = sorted(unique_terms, key=len, reverse=True)
        self._pattern = (
            re.compile(
                r"(?<![a-z0-9])(?:" + "|".join(_term_pattern(t) for t in ordered) + r")(?![a-z0-9])",
                re.IGNORECASE,
            )
            if ordered
            else None
        )

    def find(self, text: str | None) -> str | None:
        """Return the matched text, or None if no term appears."""
        if not text or self._pattern is None:
            return None
        match = self._pattern.search(text)
        return match.group(0) if match else None
