from __future__ import annotations

import json
import os
import smtplib
import subprocess
import tempfile
from email.message import EmailMessage
from pathlib import Path
from typing import Any


def send_summary_email(config: dict[str, Any], subject: str, body: str) -> bool:
    email_config = _resolve_email_config(config)
    if not email_config.get("enabled"):
        return False

    provider = email_config.get("provider", "smtp")
    if provider == "gmail_api":
        return _send_via_gmail_plugin(config, email_config, subject, body)
    if provider == "smtp":
        return _send_via_smtp(email_config, subject, body)
    raise ValueError(f"Unsupported email provider: {provider}")


def _send_via_smtp(email_config: dict[str, Any], subject: str, body: str) -> bool:
    smtp_config = email_config.get("smtp", email_config)

    host = smtp_config["host"]
    port = int(smtp_config.get("port", 587))
    username = smtp_config["username"]
    password = _resolve_password(smtp_config)
    from_email = smtp_config.get("from_email", username)
    to_email = smtp_config.get("to_email", from_email)
    use_tls = bool(smtp_config.get("use_tls", True))

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = to_email
    message.set_content(body)

    with smtplib.SMTP(host, port, timeout=30) as server:
        if use_tls:
            server.starttls()
        server.login(username, password)
        server.send_message(message)
    return True


def _send_via_gmail_plugin(config: dict[str, Any], email_config: dict[str, Any], subject: str, body: str) -> bool:
    gmail_config = email_config.get("gmail_api", {})
    script_path = Path(gmail_config.get("plugin_script", "plugins/gmail-api-mailer/scripts/send_gmail_summary.py"))
    if not script_path.is_absolute():
        script_path = Path(config["config_path"]).resolve().parent / script_path

    python_executable = gmail_config.get("python_executable", sys_executable())
    client_secret_path = _required_path(config, gmail_config, "client_secret_path")
    token_path = _required_path(config, gmail_config, "token_path")
    from_email = gmail_config["from_email"]
    to_email = gmail_config["to_email"]

    output_dir = Path(config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".txt", dir=output_dir) as handle:
        handle.write(body)
        body_path = Path(handle.name)

    command = [
        python_executable,
        str(script_path),
        "--client-secret-path",
        str(client_secret_path),
        "--token-path",
        str(token_path),
        "--from-email",
        from_email,
        "--to-email",
        to_email,
        "--subject",
        subject,
        "--body-file",
        str(body_path),
    ]

    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        return result.returncode == 0
    finally:
        try:
            body_path.unlink(missing_ok=True)
        except OSError:
            pass


def _resolve_email_config(config: dict[str, Any]) -> dict[str, Any]:
    email_config = config.get("email")
    if email_config:
        return email_config
    smtp_config = config.get("smtp", {})
    if smtp_config:
        return {"enabled": smtp_config.get("enabled", False), "provider": "smtp", "smtp": smtp_config}
    return {"enabled": False, "provider": "smtp", "smtp": {}}


def _required_path(config: dict[str, Any], settings: dict[str, Any], key: str) -> Path:
    value = settings.get(key)
    if not value:
        raise ValueError(f"Gmail API setting '{key}' is required.")
    path = Path(str(value))
    if not path.is_absolute():
        path = Path(config["config_path"]).resolve().parent / path
    return path


def _resolve_password(smtp_config: dict[str, Any]) -> str:
    if smtp_config.get("password"):
        return str(smtp_config["password"])
    env_name = smtp_config.get("password_env")
    if env_name:
        value = os.getenv(str(env_name))
        if value:
            return value
    raise ValueError("SMTP password is not configured. Set smtp.password or smtp.password_env.")


def sys_executable() -> str:
    payload = json.loads(json.dumps({"python": os.getenv("PYTHON_EXECUTABLE", "")}))
    return payload["python"] or os.sys.executable
