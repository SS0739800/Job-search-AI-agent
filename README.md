# Claude Job Agent

AI-assisted discovery of SWE / data internships and co-ops. Currently in **Phase 1: job discovery** (Greenhouse and Lever adapters done; Ashby next).

## Setup (Windows, PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Usage

```powershell
# Preview normalized postings (nothing is saved yet)
python -m app.cli fetch --company MongoDB --keyword intern
python -m app.cli fetch --keyword intern --limit 3          # all active companies
python -m app.cli fetch --company stripe --json > stripe.json

# Check every board_id in config/companies.yaml against the live API
python -m app.cli verify-companies
```

## Tests

```powershell
pytest                  # fast offline unit tests
pytest -m integration   # live calls to real job board APIs
```

## Adding a company

Find the board identifier in the company's careers links (e.g. `job-boards.greenhouse.io/<board_id>` or `jobs.lever.co/<board_id>`), add it to `config/companies.yaml`, then run `python -m app.cli verify-companies`. Never add an identifier that has not been verified.
