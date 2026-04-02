# Gmail API Mailer Plugin

Local Codex plugin scaffold for sending mail through the Gmail API instead of SMTP passwords.

## Intended Use

- Authenticate with Google OAuth
- Send summary emails for the academic discovery workflow
- Avoid storing mailbox passwords in project config

## Included Files

- `.codex-plugin/plugin.json`: plugin manifest
- `requirements.txt`: Gmail API dependencies
- `scripts/send_gmail_summary.py`: Gmail API sender entrypoint
- `skills/gmail-mailer/SKILL.md`: workflow notes for setup and sending

## Setup

1. Create a Google Cloud project and enable the Gmail API.
2. Create OAuth credentials for a desktop application.
3. Save the downloaded client secret JSON locally.
4. Install dependencies:

```bash
pip install -r plugins/gmail-api-mailer/requirements.txt
```

5. Run the sender script once to complete OAuth consent.

## Usage

The academic discovery pipeline can invoke this script automatically when `config.json` uses:

- `email.provider = "gmail_api"`
- `email.gmail_api.client_secret_path`
- `email.gmail_api.token_path`
- `email.gmail_api.from_email`
- `email.gmail_api.to_email`
