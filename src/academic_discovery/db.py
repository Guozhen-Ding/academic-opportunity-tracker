from __future__ import annotations

import json
import os
import sqlite3
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


def default_database_path(output_dir: str | Path) -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "AcademicDiscovery" / "academic_discovery.db"
    output_path = Path(output_dir)
    if output_path.suffix:
        output_path = output_path.parent
    base_dir = output_path.parent if output_path.name else output_path
    return base_dir / "data" / "academic_discovery.db"


def connect(database_path: str | Path) -> sqlite3.Connection:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _maybe_migrate_legacy_database(path)
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    return connection


def checkpoint_database(database_path: str | Path) -> None:
    with connect(database_path) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE);")


def import_sync_database(database_path: str | Path, sync_database_path: str | Path | None) -> dict[str, Any]:
    if not sync_database_path:
        return {"imported": False, "reason": "sync-disabled"}
    local_path = Path(database_path)
    sync_path = Path(sync_database_path)
    if not sync_path.exists():
        return {"imported": False, "reason": "sync-missing"}
    if local_path.exists():
        local_mtime = local_path.stat().st_mtime
        sync_mtime = sync_path.stat().st_mtime
        if local_mtime >= sync_mtime:
            return {"imported": False, "reason": "local-newer"}
    local_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sync_path, local_path)
    return {"imported": True, "reason": "sync-newer", "sync_path": str(sync_path)}


def export_sync_database(database_path: str | Path, sync_database_path: str | Path | None) -> dict[str, Any]:
    if not sync_database_path:
        return {"exported": False, "reason": "sync-disabled"}
    local_path = Path(database_path)
    sync_path = Path(sync_database_path)
    if not local_path.exists():
        return {"exported": False, "reason": "local-missing"}
    sync_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_database(local_path)
    temp_copy = sync_path.with_suffix(sync_path.suffix + ".tmp")
    shutil.copy2(local_path, temp_copy)
    temp_copy.replace(sync_path)
    return {"exported": True, "sync_path": str(sync_path)}


def _maybe_migrate_legacy_database(target_path: Path) -> None:
    legacy_path = Path(tempfile.gettempdir()) / "AcademicDiscovery" / "academic_discovery.db"
    if target_path.resolve() == legacy_path.resolve():
        return
    if target_path.name != "academic_discovery.db":
        return
    if not legacy_path.exists() or legacy_path.stat().st_size < 8192:
        return
    if target_path.exists():
        return
    for sidecar in [target_path, target_path.with_name(target_path.name + "-journal"), target_path.with_suffix(target_path.suffix + "-wal"), target_path.with_suffix(target_path.suffix + "-shm")]:
        try:
            sidecar.unlink(missing_ok=True)
        except Exception:
            pass
    shutil.copy2(legacy_path, target_path)


def initialize_database(database_path: str | Path) -> None:
    with connect(database_path) as connection:
        connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;

            CREATE TABLE IF NOT EXISTS opportunities_current (
                url TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                institution TEXT,
                department TEXT,
                location TEXT,
                country TEXT,
                salary TEXT,
                posted_date TEXT,
                application_deadline TEXT,
                deadline_status TEXT,
                days_left INTEGER,
                source_site TEXT,
                source_key TEXT,
                summary TEXT,
                eligibility TEXT,
                status TEXT,
                note TEXT,
                match_score REAL,
                match_reason TEXT,
                matched_keywords TEXT,
                is_new INTEGER DEFAULT 0,
                last_seen_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS saved_statuses (
                url TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                type TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                institution TEXT NOT NULL DEFAULT '',
                source_site TEXT NOT NULL DEFAULT '',
                last_touched_at TEXT,
                last_seen_at TEXT
            );

            CREATE TABLE IF NOT EXISTS opportunities_archive (
                url TEXT PRIMARY KEY,
                type TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                institution TEXT,
                department TEXT,
                location TEXT,
                country TEXT,
                salary TEXT,
                posted_date TEXT,
                application_deadline TEXT,
                deadline_status TEXT,
                days_left INTEGER,
                source_site TEXT,
                source_key TEXT,
                summary TEXT,
                eligibility TEXT,
                status TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                match_score REAL,
                match_reason TEXT,
                matched_keywords TEXT,
                archived_at TEXT NOT NULL,
                last_seen_at TEXT
            );

            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                opportunities_found INTEGER NOT NULL,
                opportunities_saved INTEGER NOT NULL,
                new_jobs INTEGER NOT NULL,
                new_fellowships INTEGER NOT NULL,
                diagnostics_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                url TEXT NOT NULL,
                previous_status TEXT NOT NULL DEFAULT '',
                new_status TEXT NOT NULL DEFAULT '',
                type TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                institution TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS config_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT NOT NULL,
                keywords_json TEXT NOT NULL,
                exclude_terms_json TEXT NOT NULL,
                protected_terms_json TEXT NOT NULL,
                expanded_terms_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runtime_sessions (
                session_key TEXT PRIMARY KEY,
                host TEXT NOT NULL,
                pid INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runtime_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS manual_overrides (
                url TEXT PRIMARY KEY,
                note_override TEXT NOT NULL DEFAULT '',
                note_is_set INTEGER NOT NULL DEFAULT 0,
                title_override TEXT NOT NULL DEFAULT '',
                title_is_set INTEGER NOT NULL DEFAULT 0,
                institution_override TEXT NOT NULL DEFAULT '',
                institution_is_set INTEGER NOT NULL DEFAULT 0,
                posted_date_override TEXT NOT NULL DEFAULT '',
                posted_date_is_set INTEGER NOT NULL DEFAULT 0,
                application_deadline_override TEXT NOT NULL DEFAULT '',
                application_deadline_is_set INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_opportunities_current_type
            ON opportunities_current(type);

            CREATE INDEX IF NOT EXISTS idx_opportunities_current_status
            ON opportunities_current(status);

            CREATE INDEX IF NOT EXISTS idx_saved_statuses_status
            ON saved_statuses(status);

            CREATE INDEX IF NOT EXISTS idx_opportunities_archive_status
            ON opportunities_archive(status);

            CREATE INDEX IF NOT EXISTS idx_status_history_url
            ON status_history(url);

            CREATE INDEX IF NOT EXISTS idx_manual_overrides_updated_at
            ON manual_overrides(updated_at);
            """
        )
        _ensure_column(connection, "pipeline_runs", "diagnostics_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(connection, "status_history", "previous_status", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "status_history", "new_status", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "status_history", "institution", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "opportunities_archive", "note", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "opportunities_archive", "source_key", "TEXT")
        _ensure_column(connection, "opportunities_archive", "last_seen_at", "TEXT")
        _ensure_column(connection, "manual_overrides", "note_override", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "manual_overrides", "note_is_set", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "manual_overrides", "title_override", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "manual_overrides", "title_is_set", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "manual_overrides", "institution_override", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "manual_overrides", "institution_is_set", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "manual_overrides", "posted_date_override", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "manual_overrides", "posted_date_is_set", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "manual_overrides", "application_deadline_override", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "manual_overrides", "application_deadline_is_set", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "manual_overrides", "updated_at", "TEXT NOT NULL DEFAULT ''")


def sync_current_opportunities(
    database_path: str | Path,
    items: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    now = datetime.now().isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []

    with connect(database_path) as connection:
        initialize_database(database_path)
        previous_urls = {
            str(row["url"])
            for row in connection.execute("SELECT url FROM opportunities_current").fetchall()
        }
        previous_current_rows = {
            str(row["url"]): dict(row)
            for row in connection.execute("SELECT * FROM opportunities_current").fetchall()
        }
        previous_archive_rows = {
            str(row["url"]): dict(row)
            for row in connection.execute("SELECT * FROM opportunities_archive").fetchall()
        }
        saved_statuses = {
            str(row["url"]): dict(row)
            for row in connection.execute("SELECT * FROM saved_statuses").fetchall()
        }
        for item in items:
            url = str(item.get("url", "") or "").strip()
            if not url:
                continue
            saved = saved_statuses.get(url, {})
            row = {
                "url": url,
                "type": str(item.get("type", "") or ""),
                "title": str(item.get("title", "") or ""),
                "institution": str(item.get("institution", "") or ""),
                "department": str(item.get("department", "") or ""),
                "location": str(item.get("location", "") or ""),
                "country": str(item.get("country", "") or ""),
                "salary": str(item.get("salary", "") or ""),
                "posted_date": str(item.get("posted_date", "") or ""),
                "application_deadline": str(item.get("application_deadline", "") or ""),
                "deadline_status": str(item.get("deadline_status", "") or ""),
                "days_left": _coerce_int(item.get("days_left")),
                "source_site": str(item.get("source_site", "") or ""),
                "source_key": str(item.get("source_key", "") or ""),
                "summary": str(item.get("summary", "") or ""),
                "eligibility": str(item.get("eligibility", "") or ""),
                "status": str(saved.get("status", "") or str(item.get("status", "") or "")),
                "note": str(saved.get("note", "") or str(item.get("note", "") or "")),
                "match_score": _coerce_float(item.get("match_score")) or 0.0,
                "match_reason": str(item.get("match_reason", "") or ""),
                "matched_keywords": str(item.get("matched_keywords", "") or ""),
                "is_new": 0 if url in previous_urls else 1,
                "last_seen_at": now,
            }
            rows.append(row)

        connection.execute("DELETE FROM opportunities_current")
        connection.executemany(
            """
            INSERT INTO opportunities_current (
                url, type, title, institution, department, location, country,
                salary, posted_date, application_deadline, deadline_status,
                days_left, source_site, source_key, summary, eligibility,
                status, note, match_score, match_reason, matched_keywords,
                is_new, last_seen_at
            ) VALUES (
                :url, :type, :title, :institution, :department, :location, :country,
                :salary, :posted_date, :application_deadline, :deadline_status,
                :days_left, :source_site, :source_key, :summary, :eligibility,
                :status, :note, :match_score, :match_reason, :matched_keywords,
                :is_new, :last_seen_at
            )
            """,
            rows,
        )
        current_urls = {str(row["url"]) for row in rows}
        for row in rows:
            connection.execute(
                """
                INSERT INTO saved_statuses (
                    url, status, note, type, title, institution, source_site, last_touched_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    type = CASE WHEN excluded.type <> '' THEN excluded.type ELSE saved_statuses.type END,
                    title = CASE WHEN excluded.title <> '' THEN excluded.title ELSE saved_statuses.title END,
                    institution = CASE WHEN excluded.institution <> '' THEN excluded.institution ELSE saved_statuses.institution END,
                    source_site = CASE WHEN excluded.source_site <> '' THEN excluded.source_site ELSE saved_statuses.source_site END,
                    last_seen_at = excluded.last_seen_at,
                    status = CASE WHEN saved_statuses.status <> '' THEN saved_statuses.status ELSE excluded.status END,
                    note = CASE WHEN saved_statuses.note <> '' THEN saved_statuses.note ELSE excluded.note END
                """,
                (
                    row["url"],
                    row["status"],
                    row["note"],
                    row["type"],
                    row["title"],
                    row["institution"],
                    row["source_site"],
                    None,
                    now,
                ),
            )
        archive_rows: list[dict[str, Any]] = []
        for url, saved in saved_statuses.items():
            if url in current_urls:
                continue
            if not str(saved.get("status", "") or "").strip() and not str(saved.get("note", "") or "").strip():
                continue
            source = previous_current_rows.get(url) or previous_archive_rows.get(url) or {}
            archive_rows.append(
                {
                    "url": url,
                    "type": str(saved.get("type", "") or source.get("type", "") or ""),
                    "title": str(saved.get("title", "") or source.get("title", "") or ""),
                    "institution": str(saved.get("institution", "") or source.get("institution", "") or ""),
                    "department": str(source.get("department", "") or ""),
                    "location": str(source.get("location", "") or ""),
                    "country": str(source.get("country", "") or ""),
                    "salary": str(source.get("salary", "") or ""),
                    "posted_date": str(source.get("posted_date", "") or ""),
                    "application_deadline": str(source.get("application_deadline", "") or ""),
                    "deadline_status": str(source.get("deadline_status", "") or "saved status only"),
                    "days_left": _coerce_int(source.get("days_left")),
                    "source_site": str(saved.get("source_site", "") or source.get("source_site", "") or ""),
                    "source_key": str(source.get("source_key", "") or ""),
                    "summary": str(source.get("summary", "") or "This opportunity is not in the latest scrape, but its saved status has been preserved."),
                    "eligibility": str(source.get("eligibility", "") or ""),
                    "status": str(saved.get("status", "") or ""),
                    "note": str(saved.get("note", "") or ""),
                    "match_score": _coerce_float(source.get("match_score")) or 0.0,
                    "match_reason": str(source.get("match_reason", "") or "Saved from previous run"),
                    "matched_keywords": str(source.get("matched_keywords", "") or ""),
                    "archived_at": now,
                    "last_seen_at": str(saved.get("last_seen_at", "") or source.get("last_seen_at", "") or ""),
                }
            )
        connection.execute("DELETE FROM opportunities_archive")
        if archive_rows:
            connection.executemany(
                """
                INSERT INTO opportunities_archive (
                    url, type, title, institution, department, location, country,
                    salary, posted_date, application_deadline, deadline_status,
                    days_left, source_site, source_key, summary, eligibility,
                    status, note, match_score, match_reason, matched_keywords,
                    archived_at, last_seen_at
                ) VALUES (
                    :url, :type, :title, :institution, :department, :location, :country,
                    :salary, :posted_date, :application_deadline, :deadline_status,
                    :days_left, :source_site, :source_key, :summary, :eligibility,
                    :status, :note, :match_score, :match_reason, :matched_keywords,
                    :archived_at, :last_seen_at
                )
                """,
                archive_rows,
            )
    return rows


def record_pipeline_run(
    database_path: str | Path,
    *,
    opportunities_found: int,
    opportunities_saved: int,
    new_jobs: int,
    new_fellowships: int,
    diagnostics_json: str = "{}",
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with connect(database_path) as connection:
        initialize_database(database_path)
        connection.execute(
            """
            INSERT INTO pipeline_runs (
                started_at, completed_at, opportunities_found, opportunities_saved, new_jobs, new_fellowships, diagnostics_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (now, now, opportunities_found, opportunities_saved, new_jobs, new_fellowships, diagnostics_json),
        )


def record_config_snapshot(
    database_path: str | Path,
    *,
    keywords_json: str,
    exclude_terms_json: str,
    protected_terms_json: str,
    expanded_terms_json: str,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with connect(database_path) as connection:
        initialize_database(database_path)
        connection.execute(
            """
            INSERT INTO config_snapshots (
                captured_at, keywords_json, exclude_terms_json, protected_terms_json, expanded_terms_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (now, keywords_json, exclude_terms_json, protected_terms_json, expanded_terms_json),
        )


def import_status_history_csv(database_path: str | Path, history_csv_path: str | Path) -> None:
    path = Path(history_csv_path)
    if not path.exists():
        return
    import csv

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for row in reader:
            url = str(row.get("url", "") or "").strip()
            if not url:
                continue
            rows.append(
                (
                    str(row.get("timestamp", "") or ""),
                    url,
                    str(row.get("previous_status", "") or row.get("status", "") or ""),
                    str(row.get("new_status", "") or row.get("status", "") or ""),
                    str(row.get("type", "") or ""),
                    str(row.get("title", "") or ""),
                    str(row.get("institution", "") or ""),
                )
            )
    if not rows:
        return
    with connect(database_path) as connection:
        initialize_database(database_path)
        connection.execute("DELETE FROM status_history")
        connection.executemany(
            """
            INSERT INTO status_history (timestamp, url, previous_status, new_status, type, title, institution)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def import_saved_statuses_csv(database_path: str | Path, statuses_csv_path: str | Path) -> None:
    path = _pick_status_import_source(Path(statuses_csv_path))
    if not path:
        return
    try:
        frame = pd.read_csv(path, keep_default_na=False)
    except Exception:
        return
    if frame.empty or "url" not in frame.columns:
        return
    for column in ["status", "note", "type", "title", "institution"]:
        if column not in frame.columns:
            frame[column] = ""
    with connect(database_path) as connection:
        initialize_database(database_path)
        now = datetime.now().isoformat(timespec="seconds")
        rows = []
        for row in frame.to_dict(orient="records"):
            url = str(row.get("url", "") or "").strip()
            if not url:
                continue
            rows.append(
                (
                    url,
                    str(row.get("status", "") or ""),
                    str(row.get("note", "") or ""),
                    str(row.get("type", "") or ""),
                    str(row.get("title", "") or ""),
                    str(row.get("institution", "") or ""),
                    "",
                    now,
                    None,
                )
            )
        if not rows:
            return
        connection.executemany(
            """
            INSERT INTO saved_statuses (
                url, status, note, type, title, institution, source_site, last_touched_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                status = CASE WHEN saved_statuses.status <> '' THEN saved_statuses.status ELSE excluded.status END,
                note = CASE WHEN saved_statuses.note <> '' THEN saved_statuses.note ELSE excluded.note END,
                type = CASE WHEN saved_statuses.type <> '' THEN saved_statuses.type ELSE excluded.type END,
                title = CASE WHEN saved_statuses.title <> '' THEN saved_statuses.title ELSE excluded.title END,
                institution = CASE WHEN saved_statuses.institution <> '' THEN saved_statuses.institution ELSE excluded.institution END
            """,
            rows,
        )


def run_startup_migrations(output_dir: str | Path, database_path: str | Path) -> None:
    output_path = Path(output_dir)
    with connect(database_path) as connection:
        initialize_database(database_path)
        row = connection.execute(
            "SELECT value FROM runtime_metadata WHERE key = 'startup_migration_v2'"
        ).fetchone()
    if row and str(row["value"] or "") == "done":
        return
    import_saved_statuses_csv(database_path, output_path / "statuses.csv")
    import_status_history_csv(database_path, output_path / "status_history.csv")
    with connect(database_path) as connection:
        initialize_database(database_path)
        connection.execute(
            """
            INSERT INTO runtime_metadata (key, value)
            VALUES ('startup_migration_v2', 'done')
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """
        )


def _pick_status_import_source(path: Path) -> Path | None:
    if path.exists():
        try:
            frame = pd.read_csv(path, keep_default_na=False)
            if "status" in frame.columns and any(str(value or "").strip() for value in frame["status"].tolist()):
                return path
        except Exception:
            pass
    backup_dir = path.parent / "status_backups"
    if not backup_dir.exists():
        return None
    for backup in sorted(backup_dir.glob("statuses-*.csv"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            frame = pd.read_csv(backup, keep_default_na=False)
        except Exception:
            continue
        if "status" not in frame.columns:
            continue
        if any(str(value or "").strip() for value in frame["status"].tolist()):
            return backup
    return None


def read_latest_pipeline_run(database_path: str | Path) -> dict[str, Any] | None:
    with connect(database_path) as connection:
        initialize_database(database_path)
        row = connection.execute(
            """
            SELECT
                id,
                started_at,
                completed_at,
                opportunities_found,
                opportunities_saved,
                new_jobs,
                new_fellowships,
                diagnostics_json
            FROM pipeline_runs
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        return None
    payload = dict(row)
    try:
        payload["diagnostics"] = json.loads(str(payload.get("diagnostics_json", "{}") or "{}"))
    except Exception:
        payload["diagnostics"] = {}
    return payload


def read_latest_config_snapshot(database_path: str | Path) -> dict[str, Any] | None:
    with connect(database_path) as connection:
        initialize_database(database_path)
        row = connection.execute(
            """
            SELECT
                id,
                captured_at,
                keywords_json,
                exclude_terms_json,
                protected_terms_json,
                expanded_terms_json
            FROM config_snapshots
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        return None
    payload = dict(row)
    for key in ["keywords_json", "exclude_terms_json", "protected_terms_json", "expanded_terms_json"]:
        try:
            payload[key] = json.loads(str(payload.get(key, "[]") or "[]"))
        except Exception:
            payload[key] = []
    return payload


def read_status_history_summary(database_path: str | Path) -> dict[str, Any]:
    with connect(database_path) as connection:
        initialize_database(database_path)
        count = connection.execute("SELECT COUNT(*) FROM status_history").fetchone()[0]
        saved_count = connection.execute("SELECT COUNT(*) FROM saved_statuses WHERE TRIM(status) <> ''").fetchone()[0]
        archive_count = connection.execute("SELECT COUNT(*) FROM opportunities_archive").fetchone()[0]
        orphan_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM saved_statuses s
            LEFT JOIN opportunities_current o ON o.url = s.url
            LEFT JOIN opportunities_archive a ON a.url = s.url
            WHERE TRIM(s.status) <> '' AND o.url IS NULL AND a.url IS NULL
            """
        ).fetchone()[0]
        latest = connection.execute(
            """
            SELECT timestamp, url, previous_status, new_status, type, title, institution
            FROM status_history
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    return {
        "count": int(count or 0),
        "saved_count": int(saved_count or 0),
        "archive_count": int(archive_count or 0),
        "orphan_count": int(orphan_count or 0),
        "latest": dict(latest) if latest else None,
    }


def _coerce_int(value: Any) -> int | None:
    if value in {"", None}:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _coerce_float(value: Any) -> float | None:
    if value in {"", None}:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    columns = {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column in columns:
        return
    connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def read_current_opportunities(database_path: str | Path) -> list[dict[str, Any]]:
    with connect(database_path) as connection:
        initialize_database(database_path)
        rows = connection.execute(
            """
            SELECT
                url, type, title, institution, department, location, country,
                salary, posted_date, application_deadline, deadline_status,
                days_left, source_site, source_key, summary, eligibility,
                status, note, match_score, match_reason, matched_keywords,
                is_new, last_seen_at
            FROM opportunities_current
            ORDER BY
                CASE WHEN application_deadline IS NULL OR TRIM(application_deadline) = '' THEN 1 ELSE 0 END,
                application_deadline ASC,
                match_score DESC,
                title ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def read_archived_opportunities(database_path: str | Path) -> list[dict[str, Any]]:
    with connect(database_path) as connection:
        initialize_database(database_path)
        rows = connection.execute(
            """
            SELECT
                url, type, title, institution, department, location, country,
                salary, posted_date, application_deadline, deadline_status,
                days_left, source_site, source_key, summary, eligibility,
                status, note, match_score, match_reason, matched_keywords,
                archived_at, last_seen_at
            FROM opportunities_archive
            ORDER BY
                CASE WHEN application_deadline IS NULL OR TRIM(application_deadline) = '' THEN 1 ELSE 0 END,
                application_deadline ASC,
                archived_at DESC,
                title ASC
            """
        ).fetchall()
    items = [dict(row) for row in rows]
    for item in items:
        item["is_new"] = False
        item["archived"] = True
    return items


def read_combined_opportunities(database_path: str | Path) -> list[dict[str, Any]]:
    current = read_current_opportunities(database_path)
    archived = read_archived_opportunities(database_path)
    for item in current:
        item["archived"] = False
    return _apply_manual_overrides(current + archived, read_manual_overrides(database_path))


def read_display_current_opportunities(database_path: str | Path) -> list[dict[str, Any]]:
    current = read_current_opportunities(database_path)
    for item in current:
        item["archived"] = False
    return _apply_manual_overrides(current, read_manual_overrides(database_path))


def read_manual_overrides(database_path: str | Path) -> dict[str, dict[str, Any]]:
    with connect(database_path) as connection:
        initialize_database(database_path)
        rows = connection.execute(
            """
            SELECT
                url,
                note_override,
                note_is_set,
                title_override,
                title_is_set,
                institution_override,
                institution_is_set,
                posted_date_override,
                posted_date_is_set,
                application_deadline_override,
                application_deadline_is_set,
                updated_at
            FROM manual_overrides
            ORDER BY updated_at DESC
            """
        ).fetchall()
    return {str(row["url"]): dict(row) for row in rows}


def read_saved_statuses(database_path: str | Path) -> list[dict[str, Any]]:
    with connect(database_path) as connection:
        initialize_database(database_path)
        rows = connection.execute(
            """
            SELECT url, status, note, type, title, institution, source_site, last_touched_at, last_seen_at
            FROM saved_statuses
            ORDER BY url ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def read_status_history(database_path: str | Path) -> list[dict[str, Any]]:
    with connect(database_path) as connection:
        initialize_database(database_path)
        rows = connection.execute(
            """
            SELECT id, timestamp, url, previous_status, new_status, type, title, institution
            FROM status_history
            ORDER BY id ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def export_runtime_state(output_dir: str | Path, database_path: str | Path) -> dict[str, Path]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    jobs_path = output_path / "jobs.csv"
    fellowships_path = output_path / "fellowships.csv"
    statuses_path = output_path / "statuses.csv"
    history_path = output_path / "status_history.csv"

    current_rows = _apply_manual_overrides(read_current_opportunities(database_path), read_manual_overrides(database_path))
    jobs = [row for row in current_rows if str(row.get("type", "") or "") == "job"]
    fellowships = [row for row in current_rows if str(row.get("type", "") or "") == "fellowship"]
    status_rows = read_saved_statuses(database_path)
    history_rows = read_status_history(database_path)

    pd.DataFrame(jobs).to_csv(jobs_path, index=False)
    pd.DataFrame(fellowships).to_csv(fellowships_path, index=False)
    pd.DataFrame(status_rows).to_csv(statuses_path, index=False)
    pd.DataFrame(history_rows).to_csv(history_path, index=False)

    return {
        "jobs": jobs_path,
        "fellowships": fellowships_path,
        "statuses": statuses_path,
        "status_history": history_path,
    }


def upsert_runtime_session(
    database_path: str | Path,
    *,
    session_key: str,
    host: str,
    pid: int,
    started_at: str,
    last_seen_at: str,
) -> None:
    with connect(database_path) as connection:
        initialize_database(database_path)
        connection.execute(
            """
            INSERT INTO runtime_sessions (session_key, host, pid, started_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_key) DO UPDATE SET
                host = excluded.host,
                pid = excluded.pid,
                started_at = excluded.started_at,
                last_seen_at = excluded.last_seen_at
            """,
            (session_key, host, pid, started_at, last_seen_at),
        )


def read_active_runtime_session(database_path: str | Path, session_key: str) -> dict[str, Any] | None:
    with connect(database_path) as connection:
        initialize_database(database_path)
        row = connection.execute(
            """
            SELECT session_key, host, pid, started_at, last_seen_at
            FROM runtime_sessions
            WHERE session_key <> ?
            ORDER BY last_seen_at DESC
            LIMIT 1
            """,
            (session_key,),
        ).fetchone()
    return dict(row) if row else None


def set_saved_status(
    database_path: str | Path,
    *,
    url: str,
    status: str,
    note: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_url = str(url or "").strip()
    if not clean_url:
        raise ValueError("url is required")
    normalized_status = str(status or "").strip()
    meta = meta or {}
    now = datetime.now().isoformat(timespec="seconds")

    with connect(database_path) as connection:
        initialize_database(database_path)
        saved = connection.execute("SELECT * FROM saved_statuses WHERE url = ?", (clean_url,)).fetchone()
        current = connection.execute("SELECT * FROM opportunities_current WHERE url = ?", (clean_url,)).fetchone()

        previous_status = str(saved["status"]) if saved else (str(current["status"]) if current else "")
        resolved_note = "" if note is None else str(note)
        if note is None:
            resolved_note = str(saved["note"]) if saved else (str(current["note"]) if current else "")

        resolved_type = str(meta.get("type", "") or "") or (str(saved["type"]) if saved else (str(current["type"]) if current else ""))
        resolved_title = str(meta.get("title", "") or "") or (str(saved["title"]) if saved else (str(current["title"]) if current else ""))
        resolved_institution = str(meta.get("institution", "") or "") or (
            str(saved["institution"]) if saved else (str(current["institution"]) if current else "")
        )
        resolved_source = str(meta.get("source_site", "") or "") or (
            str(saved["source_site"]) if saved else (str(current["source_site"]) if current else "")
        )
        last_seen_at = str(saved["last_seen_at"]) if saved and saved["last_seen_at"] else (str(current["last_seen_at"]) if current and current["last_seen_at"] else None)

        connection.execute(
            """
            INSERT INTO saved_statuses (
                url, status, note, type, title, institution, source_site, last_touched_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                status = excluded.status,
                note = excluded.note,
                type = CASE WHEN excluded.type <> '' THEN excluded.type ELSE saved_statuses.type END,
                title = CASE WHEN excluded.title <> '' THEN excluded.title ELSE saved_statuses.title END,
                institution = CASE WHEN excluded.institution <> '' THEN excluded.institution ELSE saved_statuses.institution END,
                source_site = CASE WHEN excluded.source_site <> '' THEN excluded.source_site ELSE saved_statuses.source_site END,
                last_touched_at = excluded.last_touched_at,
                last_seen_at = COALESCE(excluded.last_seen_at, saved_statuses.last_seen_at)
            """,
            (
                clean_url,
                normalized_status,
                resolved_note,
                resolved_type,
                resolved_title,
                resolved_institution,
                resolved_source,
                now,
                last_seen_at,
            ),
        )
        connection.execute(
            "UPDATE opportunities_current SET status = ?, note = ? WHERE url = ?",
            (normalized_status, resolved_note, clean_url),
        )
        connection.execute(
            "UPDATE opportunities_archive SET status = ?, note = ? WHERE url = ?",
            (normalized_status, resolved_note, clean_url),
        )
        connection.execute(
            """
            INSERT INTO status_history (
                timestamp, url, previous_status, new_status, type, title, institution
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (now, clean_url, previous_status, normalized_status, resolved_type, resolved_title, resolved_institution),
        )

    return {
        "url": clean_url,
        "previous_status": previous_status,
        "status": normalized_status,
        "note": resolved_note,
        "type": resolved_type,
        "title": resolved_title,
        "institution": resolved_institution,
    }


def set_manual_override(
    database_path: str | Path,
    *,
    url: str,
    field: str,
    value: str,
) -> dict[str, Any]:
    clean_url = str(url or "").strip()
    if not clean_url:
        raise ValueError("url is required")
    normalized_field = str(field or "").strip()
    field_map = {
        "note": ("note_override", "note_is_set"),
        "title": ("title_override", "title_is_set"),
        "institution": ("institution_override", "institution_is_set"),
        "posted_date": ("posted_date_override", "posted_date_is_set"),
        "application_deadline": ("application_deadline_override", "application_deadline_is_set"),
    }
    if normalized_field not in field_map:
        raise ValueError("unsupported override field")
    value_column, flag_column = field_map[normalized_field]
    cleaned_value = str(value or "")
    now = datetime.now().isoformat(timespec="seconds")
    with connect(database_path) as connection:
        initialize_database(database_path)
        connection.execute(
            f"""
            INSERT INTO manual_overrides (
                url, {value_column}, {flag_column}, updated_at
            ) VALUES (?, ?, 1, ?)
            ON CONFLICT(url) DO UPDATE SET
                {value_column} = excluded.{value_column},
                {flag_column} = 1,
                updated_at = excluded.updated_at
            """,
            (clean_url, cleaned_value, now),
        )
    return {
        "url": clean_url,
        "field": normalized_field,
        "value": cleaned_value,
        "updated_at": now,
    }


def reset_manual_override(
    database_path: str | Path,
    *,
    url: str,
    field: str,
) -> dict[str, Any]:
    clean_url = str(url or "").strip()
    if not clean_url:
        raise ValueError("url is required")
    normalized_field = str(field or "").strip()
    field_map = {
        "note": ("note_override", "note_is_set"),
        "title": ("title_override", "title_is_set"),
        "institution": ("institution_override", "institution_is_set"),
        "posted_date": ("posted_date_override", "posted_date_is_set"),
        "application_deadline": ("application_deadline_override", "application_deadline_is_set"),
    }
    if normalized_field not in field_map:
        raise ValueError("unsupported override field")
    value_column, flag_column = field_map[normalized_field]
    now = datetime.now().isoformat(timespec="seconds")
    with connect(database_path) as connection:
        initialize_database(database_path)
        connection.execute(
            f"""
            UPDATE manual_overrides
            SET {value_column} = '', {flag_column} = 0, updated_at = ?
            WHERE url = ?
            """,
            (now, clean_url),
        )
        connection.execute(
            """
            DELETE FROM manual_overrides
            WHERE url = ?
              AND note_is_set = 0
              AND title_is_set = 0
              AND institution_is_set = 0
              AND posted_date_is_set = 0
              AND application_deadline_is_set = 0
            """,
            (clean_url,),
        )
    return {
        "url": clean_url,
        "field": normalized_field,
        "reset": True,
        "updated_at": now,
    }


def undo_last_status_change(database_path: str | Path) -> dict[str, Any]:
    with connect(database_path) as connection:
        initialize_database(database_path)
        row = connection.execute(
            """
            SELECT id, url, previous_status, new_status
            FROM status_history
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return {"undone": False, "message": "No status actions available."}

        payload = dict(row)
        url = str(payload.get("url", "") or "")
        restored_status = str(payload.get("previous_status", "") or "")
        connection.execute(
            "UPDATE saved_statuses SET status = ?, last_touched_at = ? WHERE url = ?",
            (restored_status, datetime.now().isoformat(timespec="seconds"), url),
        )
        connection.execute(
            "UPDATE opportunities_current SET status = ? WHERE url = ?",
            (restored_status, url),
        )
        connection.execute(
            "UPDATE opportunities_archive SET status = ? WHERE url = ?",
            (restored_status, url),
        )
        connection.execute("DELETE FROM status_history WHERE id = ?", (payload["id"],))

    return {
        "undone": True,
        "message": "Last status action undone.",
        "url": url,
        "previous_status": str(payload.get("new_status", "") or ""),
        "restored_status": restored_status,
        "updated": 1,
    }


def restore_saved_statuses(database_path: str | Path) -> int:
    with connect(database_path) as connection:
        initialize_database(database_path)
        rows = connection.execute(
            """
            SELECT url, type, title, institution, new_status
            FROM status_history
            ORDER BY id ASC
            """
        ).fetchall()
        current_saved = {
            str(row["url"]): dict(row)
            for row in connection.execute("SELECT * FROM saved_statuses").fetchall()
        }
        restored = 0
        latest_by_url: dict[str, dict[str, str]] = {}
        for row in rows:
            url = str(row["url"] or "").strip()
            status = str(row["new_status"] or "").strip()
            if not url or not status:
                continue
            latest_by_url[url] = {
                "type": str(row["type"] or ""),
                "title": str(row["title"] or ""),
                "institution": str(row["institution"] or ""),
                "status": status,
            }
        now = datetime.now().isoformat(timespec="seconds")
        for url, payload in latest_by_url.items():
            existing = current_saved.get(url, {})
            if str(existing.get("status", "") or "").strip():
                continue
            connection.execute(
                """
                INSERT INTO saved_statuses (
                    url, status, note, type, title, institution, source_site, last_touched_at, last_seen_at
                ) VALUES (?, ?, '', ?, ?, ?, '', ?, NULL)
                ON CONFLICT(url) DO UPDATE SET
                    status = excluded.status,
                    type = CASE WHEN excluded.type <> '' THEN excluded.type ELSE saved_statuses.type END,
                    title = CASE WHEN excluded.title <> '' THEN excluded.title ELSE saved_statuses.title END,
                    institution = CASE WHEN excluded.institution <> '' THEN excluded.institution ELSE saved_statuses.institution END,
                    last_touched_at = excluded.last_touched_at
                """,
                (url, payload["status"], payload["type"], payload["title"], payload["institution"], now),
            )
            connection.execute(
                "UPDATE opportunities_current SET status = ? WHERE url = ?",
                (payload["status"], url),
            )
            connection.execute(
                "UPDATE opportunities_archive SET status = ? WHERE url = ?",
                (payload["status"], url),
            )
            restored += 1
    return restored


def _apply_manual_overrides(
    items: list[dict[str, Any]],
    overrides: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for item in items:
        row = dict(item)
        override = overrides.get(str(row.get("url", "") or ""))
        row["manual_override_fields"] = ""
        row["has_manual_overrides"] = False
        row["original_title"] = str(row.get("title", "") or "")
        row["original_institution"] = str(row.get("institution", "") or "")
        row["original_posted_date"] = str(row.get("posted_date", "") or "")
        row["original_application_deadline"] = str(row.get("application_deadline", "") or "")
        row["original_note"] = str(row.get("note", "") or "")
        if not override:
            merged.append(row)
            continue

        active_fields: list[str] = []
        if _coerce_int(override.get("note_is_set")):
            row["note"] = str(override.get("note_override", "") or "")
            active_fields.append("note")
        if _coerce_int(override.get("title_is_set")):
            row["title"] = str(override.get("title_override", "") or "")
            active_fields.append("title")
        if _coerce_int(override.get("institution_is_set")):
            row["institution"] = str(override.get("institution_override", "") or "")
            active_fields.append("institution")
        if _coerce_int(override.get("posted_date_is_set")):
            row["posted_date"] = str(override.get("posted_date_override", "") or "")
            active_fields.append("posted_date")
        if _coerce_int(override.get("application_deadline_is_set")):
            row["application_deadline"] = str(override.get("application_deadline_override", "") or "")
            active_fields.append("application_deadline")

        row["manual_override_fields"] = ",".join(active_fields)
        row["has_manual_overrides"] = bool(active_fields)
        row["manual_overrides_updated_at"] = str(override.get("updated_at", "") or "")
        merged.append(row)
    return merged
