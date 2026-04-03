from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from academic_discovery.config import load_config, normalize_config, save_config
from academic_discovery.db import (
    default_database_path,
    export_sync_database,
    export_runtime_state,
    import_sync_database,
    reset_manual_override,
    read_active_runtime_session,
    read_combined_opportunities,
    read_latest_config_snapshot,
    read_latest_pipeline_run,
    read_saved_statuses,
    read_status_history_summary,
    restore_saved_statuses,
    set_manual_override,
    set_saved_status,
    undo_last_status_change,
    upsert_runtime_session,
)

SESSION_WARNING_WINDOW = timedelta(minutes=15)


def resolve_database_path(output_dir: str | Path, config_path: str | Path | None = None) -> Path:
    if config_path:
        candidate = Path(config_path)
        if candidate.exists():
            try:
                config = load_config(candidate)
                configured = str(config.get("database_path", "") or "").strip()
                if configured:
                    resolved = Path(configured)
                    if not resolved.is_absolute():
                        resolved = (candidate.parent / resolved).resolve()
                    return resolved
            except Exception:
                pass
    return default_database_path(output_dir)


def read_runtime_opportunities(output_dir: str | Path, config_path: str | Path | None = None) -> list[dict[str, Any]]:
    return read_combined_opportunities(resolve_database_path(output_dir, config_path))


def find_opportunity_meta(output_dir: str | Path, url: str, config_path: str | Path | None = None) -> dict[str, str]:
    for item in read_combined_opportunities(resolve_database_path(output_dir, config_path)):
        if str(item.get("url", "") or "") == url:
            return {
                "type": str(item.get("type", "") or ""),
                "title": str(item.get("title", "") or ""),
                "institution": str(item.get("institution", "") or ""),
                "source_site": str(item.get("source_site", "") or ""),
            }
    return {}


def update_status(output_dir: str | Path, url: str, status: str | None = None, config_path: str | Path | None = None) -> dict[str, Any]:
    database_path = resolve_database_path(output_dir, config_path)
    result = set_saved_status(
        database_path,
        url=url,
        status=status or "",
        meta=find_opportunity_meta(output_dir, url, config_path),
    )
    export_runtime_state(output_dir, database_path)
    sync_path = _resolve_sync_database_path(config_path)
    export_sync_database(database_path, sync_path)
    return result


def update_opportunity_override(
    output_dir: str | Path,
    *,
    url: str,
    field: str,
    value: str,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    database_path = resolve_database_path(output_dir, config_path)
    result = set_manual_override(database_path, url=url, field=field, value=value)
    export_runtime_state(output_dir, database_path)
    sync_path = _resolve_sync_database_path(config_path)
    export_sync_database(database_path, sync_path)
    return result


def reset_opportunity_override(
    output_dir: str | Path,
    *,
    url: str,
    field: str,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    database_path = resolve_database_path(output_dir, config_path)
    result = reset_manual_override(database_path, url=url, field=field)
    export_runtime_state(output_dir, database_path)
    sync_path = _resolve_sync_database_path(config_path)
    export_sync_database(database_path, sync_path)
    return result


def undo_status(output_dir: str | Path, config_path: str | Path | None = None) -> dict[str, Any]:
    database_path = resolve_database_path(output_dir, config_path)
    result = undo_last_status_change(database_path)
    export_runtime_state(output_dir, database_path)
    sync_path = _resolve_sync_database_path(config_path)
    export_sync_database(database_path, sync_path)
    return result


def restore_statuses(output_dir: str | Path, config_path: str | Path | None = None) -> int:
    database_path = resolve_database_path(output_dir, config_path)
    restored = restore_saved_statuses(database_path)
    export_runtime_state(output_dir, database_path)
    sync_path = _resolve_sync_database_path(config_path)
    export_sync_database(database_path, sync_path)
    return restored


def read_runtime_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return normalize_config(json.load(handle))


def save_runtime_config(path: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_config(config)
    save_config(path, normalized)
    return normalized


def read_system_state(output_dir: str | Path, config_path: str | Path | None = None) -> dict[str, Any]:
    database_path = resolve_database_path(output_dir, config_path)
    latest_run = read_latest_pipeline_run(database_path)
    history = read_status_history_summary(database_path)
    diagnostics = latest_run.get("diagnostics", {}) if latest_run else {}
    parser_errors = [
        source for source in diagnostics.get("sources", [])
        if str(source.get("status", "") or "") in {"fetch_failed", "cache_fallback_after_error"}
    ]
    latest_parser_error = parser_errors[0] if parser_errors else None
    source_health = diagnostics.get("sources", [])
    return {
        "database_path": str(database_path),
        "database_available": Path(database_path).exists(),
        "data_source": "sqlite",
        "latest_pipeline_run": latest_run,
        "latest_config_snapshot": read_latest_config_snapshot(database_path),
        "status_history": history,
        "saved_statuses_count": history.get("saved_count", 0),
        "archive_count": history.get("archive_count", 0),
        "orphan_count": history.get("orphan_count", 0),
        "latest_failed_source": latest_parser_error,
        "latest_parser_error": latest_parser_error,
        "source_health": source_health,
        "current_opportunities_count": len(read_runtime_opportunities(output_dir, config_path)),
    }


def write_runtime_session(output_dir: str | Path, config_path: str | Path | None = None) -> dict[str, Any]:
    output_path = Path(output_dir)
    database_path = resolve_database_path(output_dir, config_path)
    import_sync_database(database_path, _resolve_sync_database_path(config_path))
    session_key = f"{socket.gethostname()}:{os.getpid()}"
    warning = read_session_status(output_path, config_path)
    now = datetime.now().isoformat(timespec="seconds")
    upsert_runtime_session(
        database_path,
        session_key=session_key,
        host=socket.gethostname(),
        pid=os.getpid(),
        started_at=now,
        last_seen_at=now,
    )
    return warning


def heartbeat_runtime_session(output_dir: str | Path, config_path: str | Path | None = None) -> None:
    database_path = resolve_database_path(output_dir, config_path)
    session_key = f"{socket.gethostname()}:{os.getpid()}"
    now = datetime.now().isoformat(timespec="seconds")
    upsert_runtime_session(
        database_path,
        session_key=session_key,
        host=socket.gethostname(),
        pid=os.getpid(),
        started_at=now,
        last_seen_at=now,
    )


def read_session_status(output_dir: str | Path, config_path: str | Path | None = None) -> dict[str, Any]:
    database_path = resolve_database_path(output_dir, config_path)
    session_key = f"{socket.gethostname()}:{os.getpid()}"
    other = read_active_runtime_session(database_path, session_key)
    if not other:
        return {"warning": False, "message": ""}
    last_seen_raw = str(other.get("last_seen_at", "") or "").strip()
    if not last_seen_raw:
        return {"warning": False, "message": ""}
    try:
        last_seen = datetime.fromisoformat(last_seen_raw)
    except ValueError:
        return {"warning": False, "message": ""}
    age = datetime.now() - last_seen
    if age > SESSION_WARNING_WINDOW:
        return {"warning": False, "message": ""}
    minutes = max(1, int(age.total_seconds() // 60))
    return {
        "warning": True,
        "message": f"Another machine appears active: {other.get('host', '')} updated this dashboard about {minutes} minute(s) ago.",
        "host": str(other.get("host", "") or ""),
        "last_seen": last_seen_raw,
    }


def _resolve_sync_database_path(config_path: str | Path | None) -> Path | None:
    if not config_path:
        return None
    candidate = Path(config_path)
    if not candidate.exists():
        return None
    try:
        config = load_config(candidate)
    except Exception:
        return None
    raw = str(config.get("sync_database_path", "") or "").strip()
    if not raw:
        return None
    return Path(raw)
