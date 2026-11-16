import pytest

from app.config import load_companies
from app.schemas.company import ATSProvider


def write_registry(tmp_path, body: str):
    path = tmp_path / "companies.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_project_registry_is_valid():
    companies = load_companies(include_inactive=True)

    assert companies, "config/companies.yaml should list at least one company"
    assert all(isinstance(company.ats, ATSProvider) for company in companies)


def test_inactive_companies_are_excluded_by_default(tmp_path):
    path = write_registry(
        tmp_path,
        """
companies:
  - {name: A, ats: greenhouse, board_id: a, careers_url: "https://a.example.com"}
  - {name: B, ats: lever, board_id: b, careers_url: "https://b.example.com", active: false}
""",
    )

    assert [c.name for c in load_companies(path)] == ["A"]
    assert [c.name for c in load_companies(path, include_inactive=True)] == ["A", "B"]


def test_duplicate_boards_are_rejected(tmp_path):
    path = write_registry(
        tmp_path,
        """
companies:
  - {name: A, ats: greenhouse, board_id: acme, careers_url: "https://a.example.com"}
  - {name: A again, ats: greenhouse, board_id: ACME, careers_url: "https://a.example.com"}
""",
    )

    with pytest.raises(ValueError, match="duplicate board"):
        load_companies(path)


@pytest.mark.parametrize(
    "entry",
    [
        '{name: A, ats: workday, board_id: a, careers_url: "https://a.example.com"}',
        '{name: A, ats: greenhouse, board_id: "has space", careers_url: "https://a.example.com"}',
        "{name: A, ats: greenhouse, board_id: a, careers_url: not-a-url}",
        '{name: A, ats: greenhouse, board_id: a, careers_url: "https://a.example.com", typo: 1}',
    ],
)
def test_invalid_entries_are_rejected(tmp_path, entry):
    path = write_registry(tmp_path, f"companies:\n  - {entry}\n")

    with pytest.raises(ValueError, match="invalid company entry #1"):
        load_companies(path)


def test_missing_companies_list_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="top-level 'companies' list"):
        load_companies(write_registry(tmp_path, "boards: []\n"))
