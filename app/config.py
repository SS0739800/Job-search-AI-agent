"""Loading settings (.env) and validating YAML configuration files."""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from app.schemas.company import CompanyConfig
from app.schemas.preferences import JobPreferences

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
COMPANIES_FILE = CONFIG_DIR / "companies.yaml"
JOB_PREFERENCES_FILE = CONFIG_DIR / "job_preferences.yaml"
DEFAULT_SQLITE_PATH = PROJECT_ROOT / "data" / "jobs.db"


def get_database_url() -> str:
    """DATABASE_URL from the environment or .env, else a local SQLite file.

    Relative SQLite paths are resolved against the project root, so commands
    work no matter which directory they are run from.
    """
    load_dotenv(PROJECT_ROOT / ".env")
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"
    prefix = "sqlite:///"
    if url.startswith(prefix) and not Path(url.removeprefix(prefix)).is_absolute():
        return f"{prefix}{(PROJECT_ROOT / url.removeprefix(prefix)).as_posix()}"
    return url


def load_job_preferences(path: Path = JOB_PREFERENCES_FILE) -> JobPreferences:
    with path.open(encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file) or {}
    try:
        return JobPreferences.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"{path}: invalid job preferences: {exc}") from exc


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
