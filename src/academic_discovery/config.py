from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_FILTERS = {
    "include_types": ["job", "fellowship"],
    "minimum_score": 0.03,
    "protected_terms": [],
    "expanded_terms": [],
    "broad_terms": [],
    "exclude_terms": [],
}

DEFAULT_RUNTIME = {
    "database_path": "data/academic_discovery.db",
    "sync_database_path": "data/academic_discovery.sync.db",
    "host": "127.0.0.1",
    "port": 8000,
    "base_url": "",
    "log_level": "info",
    "refresh_on_start": False,
}


class ConfigValidationError(ValueError):
    pass


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    _load_local_env(config_path.resolve().parent / ".env")
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    config = normalize_config(config)
    for key in ["cv_pdf", "output_dir", "database_path", "sync_database_path"]:
        raw = str(config.get(key, "") or "").strip()
        if raw and not Path(raw).is_absolute():
            config[key] = str((config_path.resolve().parent / raw).resolve())
    config["config_path"] = str(config_path.resolve())
    return config


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(config)
    if not normalized.get("cv_pdf"):
        raise ConfigValidationError("cv_pdf is required")
    if not normalized.get("output_dir"):
        raise ConfigValidationError("output_dir is required")
    normalized["keywords"] = _normalize_term_list(normalized.get("keywords"))
    filters = normalized.get("filters")
    if not isinstance(filters, dict):
        filters = {}
    merged_filters = {**DEFAULT_FILTERS, **filters}
    for key in ["include_types", "protected_terms", "expanded_terms", "broad_terms", "exclude_terms"]:
        merged_filters[key] = _normalize_term_list(merged_filters.get(key))
    if not merged_filters["include_types"]:
        merged_filters["include_types"] = list(DEFAULT_FILTERS["include_types"])
    try:
        merged_filters["minimum_score"] = float(merged_filters.get("minimum_score", DEFAULT_FILTERS["minimum_score"]))
    except Exception:
        merged_filters["minimum_score"] = float(DEFAULT_FILTERS["minimum_score"])
    normalized["filters"] = merged_filters
    normalized["database_path"] = _normalize_database_path(normalized.get("database_path") or DEFAULT_RUNTIME["database_path"])
    normalized["sync_database_path"] = _normalize_database_path(normalized.get("sync_database_path") or DEFAULT_RUNTIME["sync_database_path"])
    normalized["host"] = str(normalized.get("host") or DEFAULT_RUNTIME["host"]).strip() or DEFAULT_RUNTIME["host"]
    try:
        normalized["port"] = int(normalized.get("port", DEFAULT_RUNTIME["port"]))
    except Exception:
        normalized["port"] = int(DEFAULT_RUNTIME["port"])
    normalized["base_url"] = str(normalized.get("base_url") or DEFAULT_RUNTIME["base_url"]).strip()
    normalized["log_level"] = _normalize_log_level(normalized.get("log_level"))
    normalized["refresh_on_start"] = bool(normalized.get("refresh_on_start", DEFAULT_RUNTIME["refresh_on_start"]))
    return normalized


def backup_config(path: str | Path) -> Path:
    config_path = Path(path)
    backup_dir = config_path.parent / "config_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{config_path.stem}-{timestamp}{config_path.suffix}"
    backup_path.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup_path


def save_config(path: str | Path, config: dict[str, Any]) -> None:
    config_path = Path(path)
    normalized = normalize_config(config)
    if config_path.exists():
        backup_config(config_path)
    fd, temp_path = tempfile.mkstemp(prefix=f"{config_path.stem}-", suffix=config_path.suffix, dir=str(config_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(normalized, indent=2, ensure_ascii=False) + "\n")
        Path(temp_path).replace(config_path)
    finally:
        if Path(temp_path).exists():
            Path(temp_path).unlink(missing_ok=True)


def _load_local_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _normalize_term_list(value: Any) -> list[str]:
    if isinstance(value, list):
        candidates = value
    elif isinstance(value, str):
        candidates = value.replace(",", "\n").splitlines()
    else:
        return []
    output: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        text = str(item).strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _normalize_database_path(value: Any) -> str:
    text = str(value or DEFAULT_RUNTIME["database_path"]).strip()
    return text or DEFAULT_RUNTIME["database_path"]


def _normalize_log_level(value: Any) -> str:
    text = str(value or DEFAULT_RUNTIME["log_level"]).strip().lower()
    if text not in {"critical", "error", "warning", "info", "debug"}:
        return DEFAULT_RUNTIME["log_level"]
    return text
