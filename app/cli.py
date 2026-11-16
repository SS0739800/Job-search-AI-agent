"""Command-line entry point.

Usage:
    python -m app.cli discover                    # fetch, filter and save to the database
    python -m app.cli jobs                        # list saved jobs
    python -m app.cli runs                        # recent discovery runs and failures
    python -m app.cli fetch                       # preview relevant postings (no saving)
    python -m app.cli fetch --rejected --keyword intern
    python -m app.cli verify-companies
"""

import argparse
import json
import logging
import re
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict

from sqlalchemy.orm import Session, sessionmaker

from app.config import load_companies, load_job_preferences
from app.database.db import create_db_engine, create_session_factory, init_db
from app.database.models import Job, SearchRun
from app.database.repositories import JobRepository, SearchRunRepository
from app.discovery.filtering import FilterDecision, JobFilter
from app.discovery.pipeline import DiscoveryPipeline
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
    shown = fetch.add_mutually_exclusive_group()
    shown.add_argument("--all", action="store_true", help="Show all postings, ignoring the filter")
    shown.add_argument(
        "--rejected", action="store_true",
        help="Show only postings the filter rejected, with reasons (for tuning job_preferences.yaml)",
    )

    commands.add_parser(
        "verify-companies", help="Check every registry entry against its live ATS API"
    )

    discover = commands.add_parser(
        "discover", help="Fetch all boards, filter, and save relevant jobs to the database"
    )
    discover.add_argument(
        "--company", action="append", metavar="NAME_OR_BOARD_ID",
        help="Limit to these companies; repeatable. Default: all active supported companies.",
    )

    jobs = commands.add_parser("jobs", help="List jobs saved in the database")
    jobs.add_argument("--company", help="Only this company")
    jobs.add_argument("--include-closed", action="store_true", help="Also show closed jobs")
    jobs.add_argument("--include-duplicates", action="store_true", help="Also show duplicates")
    jobs.add_argument("--limit", type=int, default=50)

    runs = commands.add_parser("runs", help="Show recent discovery runs")
    runs.add_argument("--limit", type=int, default=5)
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


def format_job(job: NormalizedJob, decision: FilterDecision) -> str:
    posted = job.posted_at.date().isoformat() if job.posted_at else "unknown"
    if decision.is_relevant:
        verdict = f"{decision.role_category} | location: {decision.location_match}"
    else:
        verdict = "REJECTED: " + "; ".join(decision.rejection_reasons)
    return (
        f"  {job.title}\n"
        f"    {job.location or 'location not listed'} | posted {posted} | "
        f"type: {job.employment_type or '-'} | workplace: {job.workplace_type}\n"
        f"    {verdict}\n"
        f"    {job.application_url}"
    )


def run_fetch(args: argparse.Namespace) -> int:
    companies = select_companies(args.company)
    job_filter = JobFilter(load_job_preferences())
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

            evaluated = [(job, job_filter.evaluate(job)) for job in result.jobs]
            relevant_count = sum(decision.is_relevant for _, decision in evaluated)
            if args.rejected:
                evaluated = [(j, d) for j, d in evaluated if not d.is_relevant]
            elif not args.all:
                evaluated = [(j, d) for j, d in evaluated if d.is_relevant]
            if title_pattern:
                evaluated = [(j, d) for j, d in evaluated if title_pattern.search(j.title)]

            print(
                f"\n{company.name} [{company.ats}:{company.board_id}] "
                f"{len(result.jobs)} postings, {relevant_count} relevant "
                f"({result.skipped_postings} skipped) in {elapsed:.1f}s",
                file=status_stream,
            )
            shown = evaluated[: args.limit]
            if args.json:
                json_output.extend(
                    {**job.model_dump(mode="json"), "filter": asdict(decision)}
                    for job, decision in shown
                )
            else:
                for job, decision in shown:
                    print(format_job(job, decision))

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


def open_database() -> sessionmaker[Session]:
    engine = create_db_engine()
    init_db(engine)
    return create_session_factory(engine)


def format_stored_job(job: Job) -> str:
    seen = job.first_seen_at.strftime("%Y-%m-%d")
    flags = [job.status] if job.status != "active" else []
    if job.duplicate_of_id:
        flags.append(f"duplicate of #{job.duplicate_of_id}")
    flag_text = f" [{', '.join(flags)}]" if flags else ""
    return (
        f"  #{job.id} {job.company} - {job.title}{flag_text}\n"
        f"    {job.location or 'location not listed'} | {job.role_category} | "
        f"{job.location_match} | first seen {seen}\n"
        f"    {job.application_url}"
    )


def format_run(run: SearchRun) -> str:
    started = run.started_at.strftime("%Y-%m-%d %H:%M UTC")
    duration = (
        f"{(run.finished_at - run.started_at).total_seconds():.0f}s" if run.finished_at else "unfinished"
    )
    lines = [
        f"Run #{run.id} {started} ({duration}) - {run.status}",
        f"  sources: {run.sources_queried} queried, {run.sources_failed} failed",
        f"  jobs: {run.jobs_fetched} fetched, {run.relevant_jobs} relevant, {run.new_jobs} new, "
        f"{run.duplicate_jobs} duplicates, {run.updated_jobs} updated, "
        f"{run.reopened_jobs} reopened, {run.closed_jobs} closed",
    ]
    for source in run.source_results:
        if not source.succeeded:
            lines.append(f"  FAILED {source.board_key}: {source.error}")
        elif source.note:
            lines.append(f"  NOTE   {source.board_key}: {source.note}")
    return "\n".join(lines)


def run_discover(args: argparse.Namespace) -> int:
    companies = select_companies(args.company)
    session_factory = open_database()
    job_filter = JobFilter(load_job_preferences())

    with create_http_client() as client:
        sources = {provider: cls(client) for provider, cls in SCRAPER_CLASSES.items()}
        summary = DiscoveryPipeline(session_factory, sources, job_filter).run(companies)

    # The pipeline's session is closed; reload the run with its per-source results.
    with session_factory() as session:
        run = SearchRunRepository(session).get(summary.run.id)
        print("\n" + format_run(run))
    if summary.new_jobs:
        print(f"\nNew jobs ({len(summary.new_jobs)}):")
        for job in summary.new_jobs:
            print(format_stored_job(job))
    return 0 if summary.run.status == "success" else 1


def run_jobs(args: argparse.Namespace) -> int:
    with open_database()() as session:
        found = JobRepository(session).list_jobs(
            include_closed=args.include_closed, include_duplicates=args.include_duplicates,
            company=args.company, limit=args.limit,
        )
        print(f"{len(found)} job(s)")
        for job in found:
            print(format_stored_job(job))
    return 0


def run_runs(args: argparse.Namespace) -> int:
    with open_database()() as session:
        runs = SearchRunRepository(session).recent(args.limit)
        if not runs:
            print("No discovery runs yet. Run: python -m app.cli discover")
        for run in runs:
            print(format_run(run) + "\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    # Avoid crashes on Windows consoles that can't encode some job titles.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)
    handlers = {
        "fetch": lambda: run_fetch(args),
        "verify-companies": run_verify_companies,
        "discover": lambda: run_discover(args),
        "jobs": lambda: run_jobs(args),
        "runs": lambda: run_runs(args),
    }
    return handlers[args.command]()


if __name__ == "__main__":
    sys.exit(main())
