from __future__ import annotations

import argparse
import logging
import logging.handlers
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

import uvicorn

from academic_discovery.config import load_config
from academic_discovery.webapp import create_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the academic dashboard as a deployable FastAPI app")
    parser.add_argument("--output-dir", default="output", help="Directory containing dashboard assets and exports")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--open-browser", action="store_true", help="Open the dashboard in the default browser")
    parser.add_argument("--refresh-on-start", action="store_true", help="Refresh opportunities in the background after server start")
    parser.add_argument("--config", default="config.json", help="Path to config for runtime and background refresh")
    parser.add_argument("--log-level", default=None, help="Log level for the API server")
    return parser.parse_args()


def _setup_logging(output_dir: Path, log_level: str) -> None:
    logs_dir = output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "dashboard_api.log"
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    if not any(isinstance(handler, logging.handlers.RotatingFileHandler) and getattr(handler, "baseFilename", "") == str(log_path) for handler in root.handlers):
        handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=1_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    host = args.host or str(config.get("host", "127.0.0.1"))
    port = args.port or int(config.get("port", 8000))
    log_level = args.log_level or str(config.get("log_level", "info"))
    refresh_on_start = bool(args.refresh_on_start or config.get("refresh_on_start", False))
    _setup_logging(output_dir, log_level)
    cache_buster = datetime.now().strftime("%Y%m%d%H%M%S")
    dashboard_url = f"http://{host}:{port}/dashboard.html?v={cache_buster}"
    print(f"Serving dashboard at {dashboard_url}")
    if args.open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(dashboard_url)).start()
    app = create_app(
        output_dir=output_dir,
        config_path=config_path,
        refresh_on_start=refresh_on_start,
    )
    uvicorn.run(app, host=host, port=port, log_level=log_level)


if __name__ == "__main__":
    main()
