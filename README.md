# Academic Job and Fellowship Discovery

Modular Python project for reading a CV, discovering academic jobs and fellowships, scoring relevance, and generating daily outputs.

## Project Structure

```text
.
|-- config.example.json
|-- requirements.txt
|-- README.md
`-- src/
    `-- academic_discovery/
        |-- __init__.py
        |-- config.py
        |-- cv.py
        |-- main.py
        |-- models.py
        |-- pipeline.py
        |-- reporting.py
        |-- fetchers/
        |   |-- __init__.py
        |   |-- base.py
        |   |-- generic.py
        |   `-- jobs_ac_uk.py
        `-- utils/
            |-- __init__.py
            |-- deadlines.py
            |-- dedupe.py
            |-- scoring.py
            `-- text.py
```

## Quick Start

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Copy the example config and point it at your CV PDF:

```bash
copy config.example.json config.json
```

3. Run:

```bash
python run_pipeline.py --config config.json
```

Outputs are written to the configured `output_dir`:
- `jobs.csv`
- `fellowships.csv`
- `report-YYYY-MM-DD.md`
- `dashboard.html`

## Dashboard Server

If you want the dashboard to operate against the runtime database and save status changes safely, run the API server instead of double-clicking the HTML file:

```bash
python serve_dashboard.py --output-dir output --port 8000 --open-browser --config config.json
```

Then open:

```text
http://127.0.0.1:8000/dashboard.html
```

The server now uses SQLite as the runtime source of truth. CSV files in `output/` are exports and backups, not the live store.

## Deployment-Oriented Runtime

The project now supports a more deployment-friendly single-user setup:
- runtime API served by FastAPI
- SQLite database stored at `data/academic_discovery.db` by default
- optional OneDrive sync copy for cross-device state handoff
- `/health` and `/api/health` endpoints for liveness checks
- rotating API logs in `output/logs/dashboard_api.log`
- dashboard reads only from API-backed runtime data

Recommended local commands:

```bash
python run_pipeline.py --config config.json
python serve_dashboard.py --output-dir output --config config.json --host 127.0.0.1 --port 8000
```

For a longer-running personal deployment, set in `config.json`:
- `database_path`
- `sync_database_path`
- `host`
- `port`
- `base_url`
- `log_level`
- `refresh_on_start`

The generated dashboard assets are:
- `output/dashboard.html`
- `output/dashboard.js`
- `output/dashboard.css`

## Dual-Database Mode

For two-computer use, keep:
- `database_path` on the local machine outside OneDrive
- `sync_database_path` inside the synced project folder

The app will:
- import from the synced DB copy when it is newer than the local runtime DB
- continue running against the local runtime DB
- export the latest runtime DB back to the synced copy after refreshes and status changes

This is safer than using a live SQLite database directly inside OneDrive.

## Email Summary

You can optionally email yourself a summary of new matching opportunities after each run.

### Gmail API plugin flow

1. Create Google OAuth desktop-app credentials and save the JSON locally.
2. Update the `email.gmail_api` paths in `config.json`.
3. Set `email.enabled` to `true` and `email.provider` to `gmail_api`.
4. Run the main pipeline; on the first send, Google OAuth consent will be required.

The email includes only newly discovered opportunities from the current run and can be filtered by `email.minimum_score`.

### Local `.env` password flow

For SMTP-based email, you can keep the mail password out of `config.json` by placing it in a local `.env` file:

```env
ACADEMIC_DISCOVERY_GMAIL_APP_PASSWORD=your-app-password
```

Then reference it from `config.json` using `password_env`.

## Notes

- `jobs.ac.uk` support is implemented as a static HTML fetcher with conservative parsing heuristics.
- The generic fetcher can scan a university, funder, or research-group page and follow relevant same-domain links.
- `playwright` is included for later dynamic-site support, but the minimal working version uses `requests` and `BeautifulSoup`.
