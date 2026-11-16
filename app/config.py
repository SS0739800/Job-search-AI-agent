"""Loading and validating YAML configuration files."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from app.schemas.company import CompanyConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
COMPANIES_FILE = CONFIG_DIR / "companies.yaml"


def load_companies(
    path: Path = COMPANIES_FILE, *, include_inactive: bool = False
) -> list[CompanyConfig]:
    """Load the company registry, rejecting invalid or duplicate entries."""
    with path.open(encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file) or {}

    entries = data.get("companies") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError(f"{path}: expected a top-level 'companies' list")

    companies: list[CompanyConfig] = []
    seen_boards: set[tuple[str, str]] = set()
    for index, entry in enumerate(entries, start=1):
        try:
            company = CompanyConfig.model_validate(entry)
        except ValidationError as exc:
            raise ValueError(f"{path}: invalid company entry #{index}: {exc}") from exc

        board_key = (company.ats.value, company.board_id.lower())
        if board_key in seen_boards:
            raise ValueError(
                f"{path}: duplicate board '{company.ats}:{company.board_id}' (entry #{index})"
            )
        seen_boards.add(board_key)
        companies.append(company)

    return [company for company in companies if include_inactive or company.active]
