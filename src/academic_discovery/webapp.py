from __future__ import annotations

import json
import subprocess
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from academic_discovery.runtime_service import (
    heartbeat_runtime_session,
    read_runtime_config,
    read_runtime_opportunities,
    read_session_status,
    read_system_state,
    restore_statuses,
    save_runtime_config,
    undo_status,
    update_status,
    write_runtime_session,
)


class StatusPayload(BaseModel):
    url: str
    status: str


class ConfigPayload(BaseModel):
    keywords: list[str] | str | None = None
    exclude_terms: list[str] | str | None = None
    protected_terms: list[str] | str | None = None
    expanded_terms: list[str] | str | None = None


def create_app(
    *,
    output_dir: str | Path,
    config_path: str | Path,
    refresh_on_start: bool = False,
) -> FastAPI:
    output_path = Path(output_dir).resolve()
    config_file = Path(config_path).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    update_state: dict[str, Any] = {"running": False, "completed": False, "failed": False, "message": ""}
    refresh_lock = threading.Lock()
    heartbeat_stop = threading.Event()

    def normalize_terms(raw_value: Any) -> list[str]:
        if isinstance(raw_value, str):
            candidates = raw_value.replace(",", "\n").splitlines()
        elif isinstance(raw_value, list):
            candidates = []
            for item in raw_value:
                candidates.extend(str(item).replace(",", "\n").splitlines())
        else:
            return []
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            value = str(item).strip()
            key = value.lower()
            if not value or key in seen:
                continue
            seen.add(key)
            cleaned.append(value)
        return cleaned

    def run_background_refresh() -> None:
        if not refresh_lock.acquire(blocking=False):
            return
        update_state["running"] = True
        update_state["completed"] = False
        update_state["failed"] = False
        update_state["message"] = "Refreshing opportunities..."
        try:
            env = dict(__import__("os").environ)
            result = subprocess.run(
                [sys.executable, str((config_file.parent / "run_pipeline.py").resolve()), "--config", str(config_file)],
                capture_output=True,
                text=True,
                check=True,
                cwd=config_file.parent,
                env=env,
            )
            update_state["running"] = False
            update_state["completed"] = True
            update_state["failed"] = False
            update_state["message"] = result.stdout.strip() or "Refresh completed."
        except subprocess.CalledProcessError as exc:
            update_state["running"] = False
            update_state["completed"] = False
            update_state["failed"] = True
            update_state["message"] = (exc.stderr or exc.stdout or "Refresh failed.").strip()
        finally:
            refresh_lock.release()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        write_runtime_session(output_path, config_file)
        heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            args=(output_path, config_file, heartbeat_stop),
            daemon=True,
        )
        heartbeat_thread.start()
        if refresh_on_start:
            threading.Thread(target=run_background_refresh, daemon=True).start()
        try:
            yield
        finally:
            heartbeat_stop.set()

    app = FastAPI(title="Academic Discovery", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    assets_dir = output_path
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/dashboard.html")

    @app.get("/dashboard.html", include_in_schema=False)
    def dashboard_html() -> FileResponse:
        return FileResponse(output_path / "dashboard.html")

    @app.get("/dashboard.js", include_in_schema=False)
    def dashboard_js() -> FileResponse:
        return FileResponse(output_path / "dashboard.js", media_type="application/javascript")

    @app.get("/dashboard.css", include_in_schema=False)
    def dashboard_css() -> FileResponse:
        css_path = output_path / "dashboard.css"
        if not css_path.exists():
            raise HTTPException(status_code=404, detail="dashboard.css not found")
        return FileResponse(css_path, media_type="text/css")

    @app.get("/health")
    @app.get("/api/health")
    def health() -> JSONResponse:
        state = read_system_state(output_path, config_file)
        return JSONResponse(
            {
                "ok": True,
                "status": "ok" if state.get("database_available") else "degraded",
                "database_available": state.get("database_available"),
                "current_opportunities_count": state.get("current_opportunities_count", 0),
            }
        )

    @app.get("/api/opportunities")
    def api_opportunities() -> JSONResponse:
        return JSONResponse({"ok": True, "items": read_runtime_opportunities(output_path, config_file)})

    @app.get("/api/config")
    def api_config() -> JSONResponse:
        config = read_runtime_config(config_file)
        return JSONResponse(
            {
                "ok": True,
                "config": {
                    "keywords": config.get("keywords", []),
                    "exclude_terms": config.get("filters", {}).get("exclude_terms", []),
                    "protected_terms": config.get("filters", {}).get("protected_terms", []),
                    "expanded_terms": config.get("filters", {}).get("expanded_terms", []),
                },
            }
        )

    @app.get("/api/update-status")
    def api_update_status() -> JSONResponse:
        return JSONResponse({"ok": True, **update_state})

    @app.get("/api/session-status")
    def api_session_status() -> JSONResponse:
        return JSONResponse({"ok": True, **read_session_status(output_path, config_file)})

    @app.get("/api/system-state")
    def api_system_state() -> JSONResponse:
        return JSONResponse({"ok": True, **read_system_state(output_path, config_file)})

    @app.post("/api/status")
    def api_status(payload: StatusPayload) -> JSONResponse:
        normalized = "" if payload.status in {"", "none"} else payload.status.strip()
        if normalized not in {"", "interested", "applied", "ignored"}:
            raise HTTPException(status_code=400, detail="Invalid status")
        result = update_status(output_path, payload.url.strip(), normalized, config_file)
        return JSONResponse({"ok": True, "updated": 1 if result.get("url") else 0, "status": normalized})

    @app.post("/api/undo-status")
    def api_undo_status() -> JSONResponse:
        return JSONResponse({"ok": True, **undo_status(output_path, config_file)})

    @app.post("/api/restore-statuses")
    def api_restore_statuses() -> JSONResponse:
        return JSONResponse({"ok": True, "restored": restore_statuses(output_path, config_file)})

    @app.post("/api/config")
    def api_save_config(payload: ConfigPayload) -> JSONResponse:
        config = read_runtime_config(config_file)
        config["keywords"] = normalize_terms(payload.keywords)
        filters = config.get("filters")
        if not isinstance(filters, dict):
            filters = {}
            config["filters"] = filters
        filters["exclude_terms"] = normalize_terms(payload.exclude_terms)
        filters["protected_terms"] = normalize_terms(payload.protected_terms)
        filters["expanded_terms"] = normalize_terms(payload.expanded_terms)
        try:
            normalized = save_runtime_config(config_file, config)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "config": normalized})

    @app.post("/api/refresh")
    def api_refresh() -> JSONResponse:
        if update_state.get("running"):
            return JSONResponse({"ok": True, "started": False, "message": "Refresh already running."})
        threading.Thread(target=run_background_refresh, daemon=True).start()
        return JSONResponse({"ok": True, "started": True, "message": "Refresh started."})

    return app


def _heartbeat_loop(output_dir: Path, config_path: Path, stop_event: threading.Event) -> None:
    while not stop_event.wait(30):
        try:
            heartbeat_runtime_session(output_dir, config_path)
        except Exception:
            continue
