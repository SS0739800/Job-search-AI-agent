# Claude Job Agent

AI-assisted discovery of SWE / data internships and co-ops. Currently in **Phase 1: job discovery** (Greenhouse, Lever and Ashby adapters and relevance filtering done; database next).

## Setup (Windows, PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Usage

```powershell
# Preview relevant postings (nothing is saved yet)
python -m app.cli fetch                                      # all active companies
python -m app.cli fetch --company MongoDB --all              # ignore the filter
python -m app.cli fetch --rejected --keyword intern          # what was filtered out, and why
python -m app.cli fetch --company stripe --json > stripe.json

# Filter rules live in config/job_preferences.yaml

# Check every board_id in config/companies.yaml against the live API
python -m app.cli verify-companies
```

## Tests

```powershell
pytest                  # fast offline unit tests
pytest -m integration   # live calls to real job board APIs
```

## Adding a company

Find the board identifier in the company's careers links (e.g. `job-boards.greenhouse.io/<board_id>` `jobs.lever.co/<board_id>` or `jobs.ashbyhq.com/<board_id>`), add it to `config/companies.yaml`, then run `python -m app.cli verify-companies`. Never add an identifier that has not been verified.
