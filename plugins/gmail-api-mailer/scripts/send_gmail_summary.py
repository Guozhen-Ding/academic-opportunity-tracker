from __future__ import annotations

import argparse
import base64
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a text email through Gmail API")
    parser.add_argument("--client-secret-path", required=True)
    parser.add_argument("--token-path", required=True)
    parser.add_argument("--from-email", required=True)
    parser.add_argument("--to-email", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body-file", required=True)
    return parser.parse_args()


def load_credentials(client_secret_path: Path, token_path: Path) -> Credentials:
    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if credentials and credentials.valid:
        return credentials
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        token_path.write_text(credentials.to_json(), encoding="utf-8")
        return credentials

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
    credentials = flow.run_local_server(port=0)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def create_message(from_email: str, to_email: str, subject: str, body: str) -> dict[str, str]:
    message = MIMEText(body)
    message["to"] = to_email
    message["from"] = from_email
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return {"raw": raw}


def send_message(client_secret_path: Path, token_path: Path, from_email: str, to_email: str, subject: str, body: str) -> None:
    credentials = load_credentials(client_secret_path, token_path)
    service = build("gmail", "v1", credentials=credentials)
    message = create_message(from_email, to_email, subject, body)
    service.users().messages().send(userId="me", body=message).execute()


def main() -> None:
    args = parse_args()
    body = Path(args.body_file).read_text(encoding="utf-8")
    send_message(
        client_secret_path=Path(args.client_secret_path),
        token_path=Path(args.token_path),
        from_email=args.from_email,
        to_email=args.to_email,
        subject=args.subject,
        body=body,
    )


if __name__ == "__main__":
    main()
