from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.schemas.job import WorkplaceType
from app.scrapers.normalization import (
    html_to_text,
    infer_workplace_type,
    normalize_country,
    to_utc,
    unique_in_order,
)


def test_html_to_text_keeps_paragraphs_and_bullets():
    markup = (
        "<h2>About</h2><p>We build\n   tools.</p>"
        "<ul>\n<li>Python</li>\n<li>Go&nbsp;or Java</li>\n</ul><p>Line<br>break</p>"
    )

    assert html_to_text(markup) == "About\n\nWe build tools.\n\n- Python\n- Go or Java\n\nLine\nbreak"


def test_html_to_text_keeps_paragraph_wrapped_bullets_on_one_line():
    markup = "<ul><li><p>Python</p></li><li><div>SQL</div></li></ul><p>After</p>"

    assert html_to_text(markup) == "- Python\n- SQL\n\nAfter"


def test_html_to_text_drops_scripts_and_styles():
    assert html_to_text("<style>p{}</style><p>Hi</p><script>alert(1)</script>") == "Hi"


def test_to_utc_converts_offsets_and_treats_naive_as_utc():
    eastern = timezone(timedelta(hours=-5))

    assert to_utc(datetime(2026, 1, 1, 8, tzinfo=eastern)) == datetime(2026, 1, 1, 13, tzinfo=UTC)
    assert to_utc(datetime(2026, 1, 1, 8)) == datetime(2026, 1, 1, 8, tzinfo=UTC)
    assert to_utc(None) is None


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        (("Remote - US",), WorkplaceType.REMOTE),
        (("New York", "Hybrid"), WorkplaceType.HYBRID),
        (("Boston, MA",), WorkplaceType.UNKNOWN),
        ((None,), WorkplaceType.UNKNOWN),
        (("Remotely-located HQ",), WorkplaceType.UNKNOWN),  # whole word only
    ],
)
def test_infer_workplace_type(texts, expected):
    assert infer_workplace_type(*texts) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("United States", "US"),
        ("USA", "US"),
        (" us ", "US"),
        ("United States of America", "US"),
        ("GB", "GB"),
        ("Canada", "Canada"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_country(raw, expected):
    assert normalize_country(raw) == expected


def test_unique_in_order_strips_and_drops_blanks():
    assert unique_in_order([" Boston ", "Boston", "", None, "NYC"]) == ["Boston", "NYC"]
