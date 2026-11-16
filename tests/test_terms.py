import pytest

from app.discovery.terms import TermMatcher


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Software Engineer Intern", "Intern"),
        ("Internal Audit Manager", None),      # whole words only
        ("International Tax", None),
        ("Software Engineering Co-op", "Co-op"),
        ("Data Analytics Coop", "Coop"),       # flexible separators
        ("CO OP Program", "CO OP"),
        (None, None),
        ("", None),
    ],
)
def test_matches_whole_words_case_insensitively(text, expected):
    assert TermMatcher(["intern", "co op"]).find(text) == expected


def test_prefers_longest_term():
    assert TermMatcher(["analytics", "data analytics"]).find("Data Analytics Intern") == "Data Analytics"


def test_terms_ending_in_punctuation_still_match():
    matcher = TermMatcher(["sr."])

    assert matcher.find("Sr. Software Engineer") == "Sr."
    assert matcher.find("Srinivas Team") is None


def test_empty_term_list_never_matches():
    assert TermMatcher([]).find("anything") is None
    assert TermMatcher(["  "]).find("anything") is None
