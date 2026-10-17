# SPDX-License-Identifier: GPL-3.0-or-later
"""Application catalog for the JERONIX Launcher: entries, categories,
search ranking and recently used applications. No GTK, so it is
unit-tested directly (tests/unit/test_apps.py)."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

RECENT_LIMIT = 12

# (id, label, icon). Ids other than all/favorites/recent are freedesktop
# main categories (https://specifications.freedesktop.org/menu-spec/).
CATEGORIES = (
    ("all", "All Applications", "view-app-grid-symbolic"),
    ("favorites", "Favorites", "starred-symbolic"),
    ("recent", "Recently Used", "document-open-recent-symbolic"),
    ("Utility", "Accessories", "applications-utilities-symbolic"),
    ("Office", "Office", "x-office-document-symbolic"),
    ("Network", "Internet", "network-workgroup-symbolic"),
    ("Graphics", "Graphics", "applications-graphics-symbolic"),
    ("AudioVideo", "Sound & Video", "applications-multimedia-symbolic"),
    ("Development", "Development", "applications-engineering-symbolic"),
    ("Education", "Education", "applications-science-symbolic"),
    ("Game", "Games", "applications-games-symbolic"),
    ("Settings", "Settings", "preferences-system-symbolic"),
    ("System", "System", "applications-system-symbolic"),
)


@dataclass(frozen=True)
class Entry:
    id: str
    name: str
    generic: str = ""
    description: str = ""
    keywords: tuple = ()
    categories: tuple = ()
    executable: str = ""
    info: object = field(default=None, compare=False, repr=False)

    @classmethod
    def from_app_info(cls, info):
        """From a Gio.AppInfo (Gio.DesktopAppInfo)."""
        get = lambda name: getattr(info, name)() if hasattr(info, name) else None  # noqa: E731
        categories = get("get_categories") or ""
        return cls(
            id=info.get_id() or "",
            name=info.get_display_name() or info.get_name() or "",
            generic=get("get_generic_name") or "",
            description=info.get_description() or "",
            keywords=tuple(get("get_keywords") or ()),
            categories=tuple(c for c in categories.split(";") if c),
            executable=os.path.basename(info.get_executable() or ""),
            info=info,
        )


def load_entries(app_infos):
    """Visible applications, sorted by name; duplicates (same id) dropped."""
    seen, entries = set(), []
    for info in app_infos:
        if not info.should_show():
            continue
        entry = Entry.from_app_info(info)
        if entry.id and entry.id not in seen:
            seen.add(entry.id)
            entries.append(entry)
    return sorted(entries, key=lambda e: e.name.casefold())


def _score_token(entry, token):
    name = entry.name.casefold()
    if name.startswith(token):
        return 100
    if any(word.startswith(token) for word in name.split()):
        return 80
    if token in name:
        return 60
    others = [entry.generic, entry.executable, *entry.keywords]
    if any(token in o.casefold() for o in others if o):
        return 40
    if token in entry.description.casefold():
        return 20
    return None


def score(entry, query):
    """Relevance of entry for query, or None. Every word must match."""
    tokens = query.casefold().split()
    if not tokens:
        return 0
    total = 0
    for token in tokens:
        s = _score_token(entry, token)
        if s is None:
            return None
        total += s
    return total


def search(entries, query, recent=()):
    """Matching entries, best first. Recently used apps win ties."""
    rank = {app_id: i for i, app_id in enumerate(recent)}
    scored = [(s, e) for e in entries if (s := score(e, query)) is not None]
    scored.sort(key=lambda se: (-se[0], rank.get(se[1].id, len(rank)), se[1].name.casefold()))
    return [e for _, e in scored]


def in_category(entries, category, favorites=(), recent=()):
    """Entries for a sidebar category; favorites and recent keep their order."""
    by_id = {e.id: e for e in entries}
    if category == "all":
        return list(entries)
    if category == "favorites":
        return [by_id[i] for i in favorites if i in by_id]
    if category == "recent":
        return [by_id[i] for i in recent if i in by_id]
    return [e for e in entries if category in e.categories]


def categories_with_entries(entries, favorites=(), recent=()):
    """Sidebar categories that have at least one entry (all is always kept)."""
    return [c for c in CATEGORIES
            if c[0] == "all" or in_category(entries, c[0], favorites, recent)]


class RecentStore:
    """Recently launched application ids, most recent first."""

    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [i for i in data if isinstance(i, str)][:RECENT_LIMIT] if isinstance(data, list) else []

    def add(self, app_id):
        ids = [app_id] + [i for i in self.load() if i != app_id]
        ids = ids[:RECENT_LIMIT]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(ids), encoding="utf-8")
        tmp.replace(self.path)
        return ids
