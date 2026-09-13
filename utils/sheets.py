"""
Small helper around gspread for reading/writing quiz results to a Google Sheet.

Setup required (see README.md for the full walkthrough):
1. Create a Google Cloud service account with the Sheets API + Drive API enabled.
2. Share your Google Sheet with the service account's email address as an Editor.
3. Put the service account JSON key and the sheet name into Streamlit secrets:

   [gcp_service_account]
   type = "service_account"
   project_id = "..."
   private_key_id = "..."
   private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
   client_email = "...@...iam.gserviceaccount.com"
   client_id = "..."
   token_uri = "https://oauth2.googleapis.com/token"

   [sheet]
   name = "ClassGrades"
   worksheet = "Results"
"""

from datetime import datetime

import pandas as pd
import streamlit as st

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    gspread = None
    Credentials = None

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADER = ["timestamp", "student_name", "topic", "score", "total", "open_ended_notes"]


@st.cache_resource(show_spinner=False)
def _get_client():
    """Authenticate once per app run and cache the client."""
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def _get_worksheet():
    client = _get_client()
    sheet_name = st.secrets["sheet"]["name"]
    worksheet_name = st.secrets["sheet"].get("worksheet", "Results")
    spreadsheet = client.open(sheet_name)
    try:
        ws = spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=len(HEADER))
        ws.append_row(HEADER)
        return ws

    # The worksheet already existed (e.g. created manually, or created before
    # this check existed) — make sure row 1 is actually the expected header,
    # inserting it above any existing data if it's missing or wrong.
    first_row = ws.row_values(1)
    if first_row != HEADER:
        ws.insert_row(HEADER, index=1)

    return ws


def sheets_configured() -> bool:
    """True if secrets look present, so pages can degrade gracefully without them."""
    return "gcp_service_account" in st.secrets and "sheet" in st.secrets


def record_result(
    student_name: str, topic: str, score: int, total: int, open_ended_notes: str = ""
) -> None:
    """Append one quiz attempt as a new row in the sheet.

    `open_ended_notes` holds any free-text answers (essay/analysis questions)
    that aren't auto-graded, so the teacher can review them in the sheet.
    """
    ws = _get_worksheet()
    ws.append_row([
        datetime.now().isoformat(timespec="seconds"),
        student_name,
        topic,
        score,
        total,
        open_ended_notes,
    ])


def load_results() -> pd.DataFrame:
    """Read all recorded results back as a DataFrame, newest first."""
    ws = _get_worksheet()
    records = ws.get_all_records()
    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values("timestamp", ascending=False).reset_index(drop=True)
    return df


def count_attempts(student_name: str, topic: str) -> int:
    """How many times this name has already submitted this topic.

    There's no login system — this only matches on the name the student
    typed (trimmed, case-insensitive) plus the exact topic title, so it's a
    soft limit a student could get around by typing their name slightly
    differently. It's meant to discourage casual retakes, not prevent a
    determined one.
    """
    df = load_results()
    if df.empty:
        return 0
    name_norm = student_name.strip().lower()
    matches = df[
        (df["student_name"].str.strip().str.lower() == name_norm) & (df["topic"] == topic)
    ]
    return len(matches)
