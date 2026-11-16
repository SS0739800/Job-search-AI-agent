"""ATS adapters. Each provider maps to one JobBoardScraper subclass."""

from app.schemas.company import ATSProvider
from app.scrapers.base import FetchResult, JobBoardScraper, SourceFetchError
from app.scrapers.greenhouse import GreenhouseScraper
from app.scrapers.lever import LeverScraper

SCRAPER_CLASSES: dict[ATSProvider, type[JobBoardScraper]] = {
    ATSProvider.GREENHOUSE: GreenhouseScraper,
    ATSProvider.LEVER: LeverScraper,
}

__all__ = ["SCRAPER_CLASSES", "FetchResult", "JobBoardScraper", "SourceFetchError"]
