"""Command-line entry point.

Usage:
    python -m app.cli fetch --company MongoDB --keyword intern
    python -m app.cli verify-companies
"""

import argparse
import json
import logging
import re
import sys
import time
from collections.abc import Sequence

from app.config import load_companies
from app.logging_config import configure_logging
from app.schemas.company import ATSProvider, CompanyConfig
from app.schemas.job import NormalizedJob
from app.scrapers import SCRAPER_CLASSES, FetchResult, JobBoardScraper, SourceFetchError
from app.scrapers.http import create_http_client

logger = logging.getLogger("app.cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser(
        "fetch", help="Fetch and normalize postings (preview only - nothing is saved yet)"
    )
    fetch.add_argument(
        "--company", action="append", metavar="NAME_OR_BOARD_ID",
        help="Company to fetch; repeatable. Default: all active supported companies.",
    )
    fetch.add_argument("--keyword", help="Only show titles containing this whole word, e.g. intern")
    fetch.add_argument("--limit", type=int, default=10, help="Max postings shown per company")
    fetch.add_argument("--json", action="store_true", help="Print normalized postings as JSON")

    commands.add_parser(
        "verify-companies", help="Check every registry entry against its live ATS API"
    )
    return parser


def select_companies(requested: Sequence[str] | None) -> list[CompanyConfig]:
    supported = [c for c in load_companies() if c.ats in SCRAPER_CLASSES]
    if not requested:
        return supported

    wanted = {name.lower() for name in requested}
    selected = [c for c in supported if c.name.lower() in wanted or c.board_id.lower() in wanted]
    found = {c.name.lower() for c in selected} | {c.board_id.lower() for c in selected}
    unknown = sorted(wanted - found)
    if unknown:
        raise SystemExit(f"Unknown or unsupported company: {', '.join(unknown)}")
    return selected


def fetch_company(
    company: CompanyConfig, scrapers: dict[ATSProvider, JobBoardScraper]
) -> tuple[FetchResult | None, float]:
    started = time.perf_counter()
    try:
        result = scrapers[company.ats].fetch(company)
    except SourceFetchError as exc:
        logger.error("Fetch failed: %s", exc)
        result = None
    return result, time.perf_counter() - started


def format_job(job: NormalizedJob) -> str:
    posted = job.posted_at.date().isoformat() if job.posted_at else "unknown"
    return (
        f"  {job.title}\n"
        f"    {job.location or 'location not listed'} | posted {posted} | "
        f"dept: {job.department or '-'} | workplace: {job.workplace_type}\n"
        f"    {job.application_url}"
    )


def run_fetch(args: argparse.Namespace) -> int:
    companies = select_companies(args.company)
    title_pattern = re.compile(rf"\b{re.escape(args.keyword)}\b", re.IGNORECASE) if args.keyword else None
    # In JSON mode, stdout carries only JSON so it can be piped to a file.
    status_stream = sys.stderr if args.json else sys.stdout
    json_output: list[dict] = []
    failures = 0

    with create_http_client() as client:
        scrapers = {provider: cls(client) for provider, cls in SCRAPER_CLASSES.items()}
        for company in companies:
            result, elapsed = fetch_company(company, scrapers)
            if result is None:
                failures += 1
                continue

            matches = [j for j in result.jobs if not title_pattern or title_pattern.search(j.title)]
            match_note = f"; {len(matches)} match '{args.keyword}'" if title_pattern else ""
            print(
                f"\n{company.name} [{company.ats}:{company.board_id}] "
                f"{len(result.jobs)} postings ({result.skipped_postings} skipped) "
                f"in {elapsed:.1f}s{match_note}",
                file=status_stream,
            )
            shown = matches[: args.limit]
            if args.json:
                json_output.extend(job.model_dump(mode="json") for job in shown)
            else:
                for job in shown:
                    print(format_job(job))

    if args.json:
        print(json.dumps(json_output, indent=2, ensure_ascii=False))
    print(f"\nDone: {len(companies) - failures} succeeded, {failures} failed.", file=status_stream)
    return 1 if failures else 0


def run_verify_companies() -> int:
    companies = load_companies(include_inactive=True)
    failures = 0
    with create_http_client() as client:
        scrapers = {provider: cls(client) for provider, cls in SCRAPER_CLASSES.items()}
        for company in companies:
            label = f"{company.name:<16} {company.ats}:{company.board_id}"
            if company.ats not in scrapers:
                print(f"SKIP  {label} (no {company.ats} adapter yet)")
                continue
            result, _ = fetch_company(company, scrapers)
            if result is None:
                failures += 1
                print(f"FAIL  {label}")
            else:
                status = "" if company.active else " [inactive]"
                print(f"OK    {label}: {len(result.jobs)} postings{status}")
    return 1 if failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    # Avoid crashes on Windows consoles that can't encode some job titles.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)
    if args.command == "fetch":
        return run_fetch(args)
    return run_verify_companies()


if __name__ == "__main__":
    sys.exit(main())
