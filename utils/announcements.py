"""
Announcements shown on the home page: manual news posts from
announcements/announcements.json, plus auto-generated "new resource" posts
for anything in resources/manifest.json with a recent `date_added`.

Auto posts are computed statelessly from each resource's `date_added`
(YYYY-MM-DD, optional) rather than by diffing against a "seen resources"
tracker file. Streamlit Community Cloud's disk resets on restarts and
sleep/wake cycles, so a stateful tracker would silently forget what it had
already announced and start re-announcing old resources. Instead, a
resource simply counts as "new" for NEW_RESOURCE_WINDOW_DAYS days after its
date_added, then quietly ages out — no cleanup step needed.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

APP_DIR = Path(__file__).parent.parent
ANNOUNCEMENTS_PATH = APP_DIR / "announcements" / "announcements.json"
MANIFEST_PATH = APP_DIR / "resources" / "manifest.json"

NEW_RESOURCE_WINDOW_DAYS = 14


def _load_json(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_date(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def get_announcements(limit: Optional[int] = None) -> list[dict]:
    """Manual announcements + auto "new resource" posts, newest first.

    Each item: {"date": datetime|None, "date_str": str, "title": str,
    "body": str, "kind": str}. `kind` drives the badge color/label in
    utils.ui.badge() — "news" for manual posts (or whatever `type` was set
    to), "resource" for auto-generated new-resource posts.
    """
    items = []

    for entry in _load_json(ANNOUNCEMENTS_PATH):
        date = _parse_date(entry.get("date"))
        items.append(
            {
                "date": date or datetime.min,
                "date_str": entry.get("date", ""),
                "title": entry.get("title", "Announcement"),
                "body": entry.get("body", ""),
                "kind": entry.get("type", "news"),
            }
        )

    cutoff = datetime.now() - timedelta(days=NEW_RESOURCE_WINDOW_DAYS)
    for r in _load_json(MANIFEST_PATH):
        date = _parse_date(r.get("date_added"))
        if date and date >= cutoff:
            items.append(
                {
                    "date": date,
                    "date_str": r.get("date_added", ""),
                    "title": f"New resource: {r['title']}",
                    "body": f"{r.get('type', 'Resource')} added under {r.get('topic', 'the library')}.",
                    "kind": "resource",
                }
            )

    items.sort(key=lambda x: x["date"], reverse=True)
    return items[:limit] if limit else items
