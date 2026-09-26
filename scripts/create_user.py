#!/usr/bin/env python3
"""
Create one student account (teacher-run, local only).

Usage:
    python scripts/create_user.py <username> <password> [display name]

Writes a row to the Users worksheet (same spreadsheet as grades) with a
PBKDF2 password hash — never plaintext. Run once per student, then give
each student their own username + password privately.

To disable later: set active=FALSE in the Users sheet (or delete the row).
No API key beyond the existing Sheets service account is needed.
"""

from __future__ import annotations

import hashlib
import secrets as py_secrets
import sys
import tomllib
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).parent.parent
SECRETS_PATH = APP_DIR / ".streamlit" / "secrets.toml"

USERS_WORKSHEET = "Users"
USERS_HEADER = ["username", "display_name", "password_hash", "active", "created_at", "video_access"]
_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = py_secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${dk.hex()}"


def main(argv: list[str]) -> None:
    if len(argv) < 3:
        print(__doc__.strip())
        sys.exit(2)
    username, password = argv[1].strip(), argv[2]
    display = argv[3].strip() if len(argv) > 3 else username
    if not username or not password:
        print("Username and password must both be non-empty.")
        sys.exit(2)

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("Missing deps. Run:  pip install -r requirements.txt", file=sys.stderr)
        sys.exit(1)

    secrets = tomllib.loads(SECRETS_PATH.read_text(encoding="utf-8"))
    creds = Credentials.from_service_account_info(
        dict(secrets["gcp_service_account"]),
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    spreadsheet = gspread.authorize(creds).open(secrets["sheet"]["name"])
    try:
        ws = spreadsheet.worksheet(USERS_WORKSHEET)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=USERS_WORKSHEET, rows=500, cols=len(USERS_HEADER))
        ws.append_row(USERS_HEADER)

    existing = {_norm(v) for v in ws.col_values(1)[1:]}
    if username.lower() in existing:
        print(f"User '{username}' already exists — nothing added.")
        sys.exit(0)

    ws.append_row([
        username, display, hash_password(password), "TRUE",
        datetime.now().isoformat(timespec="seconds"),
        "",
    ])
    print(f"Added '{username}' ({display}). Share the password privately.")


def _norm(v) -> str:
    return str(v or "").strip().lower()


if __name__ == "__main__":
    main(sys.argv)
