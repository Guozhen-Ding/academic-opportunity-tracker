# Personal Deployment Guide

This project is now structured as a single-user web app with:
- FastAPI runtime server
- SQLite runtime database
- optional synced SQLite copy for cross-device handoff
- API-driven dashboard
- CSV and Markdown exports as secondary artifacts

## Recommended Layout

- `config.json`
- `data/academic_discovery.db`
- `data/academic_discovery.sync.db`
- `output/`
- `.env`

## Install

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run Pipeline

```bash
.venv\Scripts\python.exe run_pipeline.py --config config.json
```

## Run API Server

```bash
.venv\Scripts\python.exe serve_dashboard.py --output-dir output --config config.json --host 127.0.0.1 --port 8000 --refresh-on-start
```

## Health Check

- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/api/health`

## Notes

- Runtime state lives in SQLite, not CSV.
- `jobs.csv`, `fellowships.csv`, `statuses.csv`, and `status_history.csv` are exported snapshots.
- Recommended dual-machine setup:
  - `database_path` in local `AppData`
  - `sync_database_path` in the OneDrive project
- For remote access on a private machine, bind `host` to `0.0.0.0` and use a reverse proxy or firewall rules.
- For future cloud deployment, keep this as a single instance; SQLite is not intended for multi-instance concurrent writes.

## Safe Workspace Cleanup

For routine size reduction without breaking the current setup, run:

```bash
clean_workspace.bat
```

This cleanup is safe for the dual-machine workflow:
- it keeps `.venv` and `.venv_local`
- it keeps runtime databases and synced database copies
- it keeps dashboard assets and exported CSV snapshots
- it only removes temporary directories, session files, transient logs, `*.db-journal`, and older report/backup files

If you later want a smaller but less plug-and-play setup, the next step is to keep only one virtual environment and let the second machine rebuild its own `.venv` on first launch.
