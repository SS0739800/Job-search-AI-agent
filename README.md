# Claude Job Agent

AI-assisted discovery of SWE / data internships and co-ops. **Phase 1 (job discovery) is complete**: Greenhouse, Lever and Ashby boards are fetched, filtered for relevance, de-duplicated and tracked in a database.

## Setup (Windows, PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # optional; defaults to SQLite at data/jobs.db
```

## Usage

```powershell
# Discover: fetch every board, filter, save relevant jobs, log the run
python -m app.cli discover
python -m app.cli discover --company notion     # just one company

# Inspect the database
python -m app.cli jobs                          # active jobs, newest first
python -m app.cli jobs --company Palantir --include-closed
python -m app.cli runs                          # recent runs, failures and notes

# Preview without saving
python -m app.cli fetch                                      # relevant postings
python -m app.cli fetch --company MongoDB --all              # ignore the filter
python -m app.cli fetch --rejected --keyword intern          # what was filtered out, and why

# Check every board_id in config/companies.yaml against the live API
python -m app.cli verify-companies
```

Filter rules live in `config/job_preferences.yaml`.

## How a job is tracked

- **New**: first time a relevant posting is seen (`first_seen_at` = date discovered).
- **Updated**: title, location, description, etc. changed since last run.
- **Closed**: missing from a board that was fetched *successfully*. Failed boards, empty responses and responses with malformed postings never close jobs.
- **Reopened**: a closed job appears again.
- **Duplicate**: same company + title + location, or same application URL, as an existing job. Stored, but linked to the original and not counted as new.

## Tests

```powershell
pytest                  # fast offline tests (fake sources, temporary SQLite DBs)
pytest -m integration   # live calls to real job board APIs
```

## Adding a company

Find the board identifier in the company's careers links (e.g. `job-boards.greenhouse.io/<board_id>`, `jobs.lever.co/<board_id>` or `jobs.ashbyhq.com/<board_id>`), add it to `config/companies.yaml`, then run `python -m app.cli verify-companies`. Never add an identifier that has not been verified.
