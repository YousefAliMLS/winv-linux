"""Emoji dataset loading, search and "recently used" tracking."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from . import config

log = logging.getLogger(__name__)

RECENT_LIMIT = 40

# (group name in emoji-test.txt, tab icon)
CATEGORIES: list[tuple[str, str]] = [
    ("Recent", "🕘"),
    ("Smileys & Emotion", "😀"),
    ("People & Body", "👋"),
    ("Animals & Nature", "🐻"),
    ("Food & Drink", "🍔"),
    ("Activities", "⚽"),
    ("Travel & Places", "🚗"),
    ("Objects", "💡"),
    ("Symbols", "❤️"),
    ("Flags", "🏁"),
]


@dataclass(frozen=True)
class Emoji:
    char: str
    name: str
    group: str
    keywords: str

    @property
    def haystack(self) -> str:
        return f"{self.name} {self.keywords}".lower()


def load_emoji() -> list[Emoji]:
    path = config.PACKAGE_DATA / "emoji.json"
    try:
        raw = json.loads(path.read_text("utf-8"))
        return [Emoji(*row) for row in raw]
    except (OSError, ValueError, TypeError) as exc:
        log.error("Could not load emoji data from %s: %s", path, exc)
        return []


def matches(emoji: Emoji, query: str) -> bool:
    """Every whitespace-separated term must prefix-match a word in the name/keywords."""
    if not query:
        return True
    words = emoji.haystack.replace(":", " ").split()
    return all(any(w.startswith(term) for w in words) for term in query.lower().split())


def load_recent() -> list[str]:
    try:
        data = json.loads(config.RECENT_EMOJI_FILE.read_text("utf-8"))
        return [e for e in data if isinstance(e, str)][:RECENT_LIMIT]
    except (OSError, ValueError):
        return []


def push_recent(char: str) -> list[str]:
    recent = [char] + [e for e in load_recent() if e != char]
    recent = recent[:RECENT_LIMIT]
    try:
        config.ensure_dirs()
        config.RECENT_EMOJI_FILE.write_text(json.dumps(recent, ensure_ascii=False), "utf-8")
    except OSError as exc:
        log.warning("Could not save recent emoji: %s", exc)
    return recent
