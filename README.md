# Academic Opportunity Tracker

A Python-based personal research opportunity tracker for academic jobs, fellowships, and funding calls.

It reads a CV, searches across multiple academic sources, scores relevance, stores runtime data in SQLite, and serves a local dashboard where you can review, filter, correct, and annotate opportunities.

## What It Does

- Extracts profile keywords from a CV PDF
- Crawls academic job and fellowship sources
- Scores relevance against your profile and configured keywords
- Deduplicates overlapping listings from different sources
- Stores runtime data in SQLite instead of treating CSV as the live source
- Exports:
  - `jobs.csv`
  - `fellowships.csv`
  - `report-YYYY-MM-DD.md`
  - dashboard assets
- Provides a local FastAPI dashboard with:
  - filtering and sorting
  - status tracking: `Unprocessed`, `Interested`, `Applied`, `Ignored`
  - source health diagnostics
  - manual field corrections
  - personal notes

## Current Architecture

The project is now structured as a single-user, deployment-oriented application:

- Runtime source of truth: SQLite
- API server: FastAPI
- Dashboard: API-driven HTML/JS/CSS
- Pipeline: Python fetchers + scoring + exports
- CSV and Markdown outputs: exports only, not the live store

Key runtime concepts:

- `opportunities_current`: current run results
- `opportunities_archive`: previously seen items retained for history
- `saved_statuses`: status tracking
- `manual_overrides`: manual corrections and notes

## Supported Sources

Current codebase includes dedicated fetchers for:

- `jobs.ac.uk`
- Imperial College London jobs
- Imperial fellowship pages
- Cambridge jobs
- Oxford engineering jobs
- Royal Society grants
- Leverhulme listings
- UKRI opportunities
- UKRI EPSRC fellowships
- EPFL
- ETH Zurich
- AcademicJobsOnline
- EURAXESS
- NUS
- UNSW
- KU Leuven
- TU Delft
- University of Melbourne

Some sources will still need periodic maintenance when site structure changes. The dashboard exposes source diagnostics so failures are visible.

## Repository Layout

```text
.
|-- config.example.json
|-- requirements.txt
|-- run_pipeline.py
|-- serve_dashboard.py
|-- start_dashboard.bat
|-- clean_workspace.bat
|-- README.md
|-- DEPLOYMENT.md
|-- output/
`-- src/
    `-- academic_discovery/
        |-- config.py
        |-- cv.py
        |-- db.py
        |-- pipeline.py
        |-- reporting.py
        |-- runtime_service.py
        |-- source_registry.py
        |-- webapp.py
        |-- fetchers/
        `-- utils/
```

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Create your config

```bash
copy config.example.json config.json
```

Edit `config.json` and set at least:

- `cv_pdf`
- `output_dir`
- `database_path`
- your enabled sources
- your keywords / filters

### 3. Run the pipeline

```bash
python run_pipeline.py --config config.json
```

### 4. Start the dashboard

```bash
python serve_dashboard.py --output-dir output --config config.json --host 127.0.0.1 --port 8000
```

Then open:

```text
http://127.0.0.1:8000/dashboard.html
```

On Windows, you can also use:

```text
start_dashboard.bat
```

## Dashboard Features

The dashboard supports:

- keyword search
- filtering by type, source, country, institution, deadline window
- source health inspection
- status changes:
  - `Interested`
  - `Applied`
  - `Ignore`
  - `Clear`
- manual corrections for:
  - `Title`
  - `Institution`
  - `Posted`
  - `Deadline`
- personal note storage

Manual corrections and notes are stored in the runtime database and survive future refreshes.

## Configuration Model

The project is gradually moving to a registry-driven source model.

`config.example.json` now separates:

- global runtime settings
- filters / scoring settings
- email settings
- `sources`

Each source entry follows a common shape:

- `enabled`
- `name`
- `type`
- `base_url`
- `refresh_hours`
- `priority`
- `fetcher`
- `supports_dynamic`
- `params`

## Runtime Database

Recommended setup:

- keep `database_path` on the local machine outside OneDrive
- optionally keep `sync_database_path` inside the synced project folder

This lets the app:

- run against a stable local SQLite database
- export a synced copy for handoff between computers
- avoid running SQLite directly inside OneDrive

## Outputs

After a successful pipeline run, the project writes:

- `output/jobs.csv`
- `output/fellowships.csv`
- `output/report-YYYY-MM-DD.md`
- `output/dashboard.html`
- `output/dashboard.js`
- `output/dashboard.css`

These are exports for review and backup. The live runtime state stays in SQLite.

## Email Summaries

Optional email support is available.

Supported flows include:

- Gmail API
- SMTP with secrets stored in `.env`

Typical use case:

- send a summary of newly discovered relevant opportunities after a run

## Safe Cleanup

If the project folder becomes too large, run:

```bash
clean_workspace.bat
```

This performs safe cleanup of temporary files, old logs, stale session files, and excess backups without deleting:

- virtual environments
- runtime databases
- current CSV exports
- dashboard assets

## Cross-Computer Use

For two-computer usage:

- run the app on only one machine at a time
- let OneDrive finish syncing before switching devices
- keep the main runtime DB local
- use the sync DB copy for handoff

This is safer than sharing a live SQLite database inside OneDrive.

## Development Notes

The codebase is evolving toward:

- DB-first runtime state
- API-first dashboard rendering
- fetcher registry for easier source expansion
- source-specific diagnostics instead of silent failures

New sources should ideally be added via:

1. a dedicated fetcher
2. source registry registration
3. config template entry
4. sample-based tests

## Deployment

See:

- [DEPLOYMENT.md](C:/Users/79040/OneDrive%20-%20Imperial%20College%20London/Codex/Job/DEPLOYMENT.md)

That document covers the more deployment-oriented single-user setup.

## Status

This project is suitable for:

- personal use
- long-running use on one machine
- gradual expansion to more sources

It is not yet intended as a polished public multi-user product.
