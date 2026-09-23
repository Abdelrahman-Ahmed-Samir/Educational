"""
Username + password gate for the whole app (teacher-managed accounts).

Teacher workflow:
  1. Run locally:  python scripts/create_user.py <username> <password> "Display Name"
     This writes a hashed row to the Users worksheet (same spreadsheet as
     grades). Do this once per student (<20).
  2. To disable someone: set active=FALSE in the Users sheet (or delete row).
  3. No Google OAuth, no join code, nothing to share that can leak.

Sheet schema (worksheet "Users", auto-created):
  username | display_name | password_hash | active | created_at

Passwords are PBKDF2-HMAC-SHA256 hashes (stdlib only, no new dependency).
If a row still holds a plaintext password (typed by hand), login still
works once and the value is auto-upgraded to a hash on success — but
prefer the script so plaintext never sits in the sheet.

Every page calls require_login() first; anonymous users see only the
login form (st.stop()). The Grades page keeps its extra teacher_password
check on top of this.
"""

from __future__ import annotations

import hashlib
import secrets as py_secrets
from datetime import datetime

import streamlit as st

USERS_WORKSHEET = "Users"
USERS_HEADER = ["username", "display_name", "password_hash", "active", "created_at"]

_ITERATIONS = 200_000


# ---------- password hashing (stdlib) ----------

def hash_password(password: str) -> str:
    salt = py_secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${dk.hex()}"


def _looks_like_hash(value: str) -> bool:
    parts = str(value or "").split("$")
    return len(parts) == 4 and parts[0] == "pbkdf2_sha256" and parts[1].isdigit()


def verify_password(password: str, stored: str) -> bool:
    stored = str(stored or "")
    if _looks_like_hash(stored):
        try:
            _, iters, salt_hex, hash_hex = stored.split("$")
            dk = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"),
                bytes.fromhex(salt_hex), int(iters),
            )
            return py_secrets.compare_digest(dk.hex(), hash_hex)
        except Exception:
            return False
    # Legacy plaintext cell (hand-typed): constant-time compare so login
    # works once; caller auto-upgrades it to a hash on success.
    return py_secrets.compare_digest(str(password), stored)


# ---------- Users sheet ----------

def _norm(name: str) -> str:
    return str(name or "").strip().lower()


@st.cache_data(ttl=60, show_spinner=False)
def _load_users() -> list[dict]:
    """Cached 60s so every rerun doesn't hit Sheets, but new/disabled
    accounts take effect within a minute."""
    from utils.sheets import _get_client

    client = _get_client()
    spreadsheet = client.open(st.secrets["sheet"]["name"])
    try:
        ws = spreadsheet.worksheet(USERS_WORKSHEET)
    except Exception:
        return []
    try:
        records = ws.get_all_records()
    except Exception:
        return []
    return records if isinstance(records, list) else []


def _find_user(username: str) -> dict | None:
    want = _norm(username)
    for row in _load_users():
        if _norm(row.get("username")) == want:
            return row
    return None


def _set_active(username: str, active: bool) -> None:
    from utils.sheets import _get_client

    client = _get_client()
    ws = client.open(st.secrets["sheet"]["name"]).worksheet(USERS_WORKSHEET)
    cell = ws.find(username.strip(), in_column=1)
    if cell:
        ws.update_cell(cell.row, 4, "TRUE" if active else "FALSE")


def _upgrade_to_hash(username: str, password: str) -> None:
    """Replace a plaintext cell with a hash after a successful login."""
    from utils.sheets import _get_client

    try:
        client = _get_client()
        ws = client.open(st.secrets["sheet"]["name"]).worksheet(USERS_WORKSHEET)
        cell = ws.find(username.strip(), in_column=1)
        if cell:
            ws.update_cell(cell.row, 3, hash_password(password))
            _load_users.clear()
    except Exception:
        pass


def user_count() -> int:
    try:
        return len(_load_users())
    except Exception:
        return 0


# ---------- teacher user management (used by Grades admin panel) ----------

def _get_users_ws():
    """Users worksheet, created on first use."""
    from utils.sheets import _get_client

    client = _get_client()
    spreadsheet = client.open(st.secrets["sheet"]["name"])
    try:
        return spreadsheet.worksheet(USERS_WORKSHEET)
    except Exception:
        ws = spreadsheet.add_worksheet(
            title=USERS_WORKSHEET, rows=500, cols=len(USERS_HEADER)
        )
        ws.append_row(USERS_HEADER)
        return ws


def _user_row(ws, username: int | str) -> int | None:
    """1-based row number of username in column 1, or None. Scans values
    instead of ws.find() so dots/dashes in usernames can't break regex."""
    want = _norm(username)
    try:
        col = ws.col_values(1)
    except Exception:
        return None
    for i, v in enumerate(col[1:], start=2):
        if _norm(v) == want:
            return i
    return None


def list_users() -> list[dict]:
    try:
        return list(_load_users())
    except Exception:
        return []


def create_user(username: str, password: str, display_name: str = "") -> None:
    username = str(username or "").strip()
    if not username or not password:
        raise ValueError("Username and password are required.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    ws = _get_users_ws()
    if _user_row(ws, username) is not None:
        raise ValueError(f"User '{username}' already exists.")
    ws.append_row([
        username,
        (display_name or username).strip(),
        hash_password(password),
        "TRUE",
        datetime.now().isoformat(timespec="seconds"),
    ])
    _load_users.clear()


def set_user_active(username: str, active: bool) -> None:
    ws = _get_users_ws()
    row = _user_row(ws, username)
    if row is None:
        raise ValueError(f"User '{username}' not found.")
    ws.update_cell(row, 4, "TRUE" if active else "FALSE")
    _load_users.clear()


def reset_user_password(username: str) -> str:
    """Set a random 8-char temp password, return it (shown once to teacher)."""
    import string

    alphabet = string.ascii_lowercase + string.digits
    temp = "".join(py_secrets.choice(alphabet) for _ in range(8))
    ws = _get_users_ws()
    row = _user_row(ws, username)
    if row is None:
        raise ValueError(f"User '{username}' not found.")
    ws.update_cell(row, 3, hash_password(temp))
    _load_users.clear()
    return temp


def change_password(username: str, current_password: str, new_password: str) -> bool:
    """Student self-service. Returns True on success, False on wrong
    current password. Raises on weak new password."""
    if len(new_password or "") < 6:
        raise ValueError("New password must be at least 6 characters.")
    row = _find_user(username)
    if not row or not verify_password(current_password or "", row.get("password_hash", "")):
        return False
    ws = _get_users_ws()
    r = _user_row(ws, username)
    if r is None:
        return False
    ws.update_cell(r, 3, hash_password(new_password))
    _load_users.clear()
    return True


# ---------- public API used by pages ----------

def get_current_user() -> dict | None:
    u = st.session_state.get("user")
    if u and u.get("username"):
        return u
    return None


def logout() -> None:
    st.session_state.pop("user", None)


def require_login() -> dict:
    """Gate for every page. Returns {'username','display_name'} or renders
    the login form and stops the page."""
    user = get_current_user()
    if user:
        with st.sidebar:
            st.caption(f"Signed in as {user.get('display_name') or user['username']}")
            if st.button("Sign out"):
                logout()
                st.rerun()
        return user

    st.subheader("🔒 Class login")
    st.write("Enter the username and password your teacher gave you.")
    with st.form("class_login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        go = st.form_submit_button("Sign in", type="primary")

    if go:
        row = _find_user(username)
        active = str((row or {}).get("active", "")).strip().upper()
        if row and active not in ("FALSE", "0", "NO", "") and verify_password(password, row.get("password_hash", "")):
            if not _looks_like_hash(row.get("password_hash", "")):
                _upgrade_to_hash(row["username"], password)
            st.session_state["user"] = {
                "username": str(row["username"]).strip(),
                "display_name": str(row.get("display_name") or row["username"]).strip(),
            }
            st.rerun()
        else:
            st.error("Wrong username or password — or the account is disabled.")
    st.stop()
