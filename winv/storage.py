"""SQLite-backed clipboard history shared by the watcher and the UI."""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    kind     TEXT    NOT NULL CHECK (kind IN ('text', 'image')),
    content  TEXT    NOT NULL,          -- the text itself, or the image file name
    hash     TEXT    NOT NULL UNIQUE,
    width    INTEGER NOT NULL DEFAULT 0,
    height   INTEGER NOT NULL DEFAULT 0,
    pinned   INTEGER NOT NULL DEFAULT 0,
    created  REAL    NOT NULL,
    used     REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS items_used ON items (pinned DESC, used DESC);
"""


@dataclass(frozen=True)
class Item:
    id: int
    kind: str
    content: str
    hash: str
    width: int
    height: int
    pinned: bool
    created: float
    used: float

    @property
    def image_path(self) -> Path:
        return config.IMAGE_DIR / self.content

    @property
    def thumb_path(self) -> Path:
        return config.THUMB_DIR / self.content


class Store:
    def __init__(self, path: Path | None = None) -> None:
        config.ensure_dirs()
        self.path = path or config.DB_FILE
        self.db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)

    # -- writes ---------------------------------------------------------------
    def add(self, kind: str, content: str, digest: str, width: int = 0, height: int = 0) -> bool:
        """Insert an entry, or bump it to the top if it already exists.

        Returns True when a brand-new entry was created.
        """
        now = time.time()
        cur = self.db.execute("UPDATE items SET used = ? WHERE hash = ?", (now, digest))
        if cur.rowcount:
            return False
        self.db.execute(
            "INSERT INTO items (kind, content, hash, width, height, created, used)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kind, content, digest, width, height, now, now),
        )
        return True

    def has_hash(self, digest: str) -> bool:
        return self.db.execute("SELECT 1 FROM items WHERE hash = ?", (digest,)).fetchone() is not None

    def touch(self, item_id: int) -> None:
        self.db.execute("UPDATE items SET used = ? WHERE id = ?", (time.time(), item_id))

    def set_pinned(self, item_id: int, pinned: bool) -> None:
        self.db.execute("UPDATE items SET pinned = ? WHERE id = ?", (int(pinned), item_id))

    def delete(self, item_id: int) -> None:
        row = self.db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if row:
            self._remove_files(self._row(row))
            self.db.execute("DELETE FROM items WHERE id = ?", (item_id,))

    def clear(self, keep_pinned: bool = True) -> None:
        where = "WHERE pinned = 0" if keep_pinned else ""
        for row in self.db.execute(f"SELECT * FROM items {where}").fetchall():
            self._remove_files(self._row(row))
        self.db.execute(f"DELETE FROM items {where}")

    def prune(self, max_items: int) -> None:
        """Drop the oldest unpinned entries beyond ``max_items``."""
        rows = self.db.execute(
            "SELECT * FROM items WHERE pinned = 0 ORDER BY used DESC LIMIT -1 OFFSET ?",
            (max(0, max_items),),
        ).fetchall()
        for row in rows:
            self._remove_files(self._row(row))
            self.db.execute("DELETE FROM items WHERE id = ?", (row["id"],))

    # -- reads ----------------------------------------------------------------
    def items(self) -> list[Item]:
        rows = self.db.execute("SELECT * FROM items ORDER BY pinned DESC, used DESC").fetchall()
        return [self._row(r) for r in rows]

    # -- helpers --------------------------------------------------------------
    @staticmethod
    def _row(row: sqlite3.Row) -> Item:
        return Item(
            id=row["id"], kind=row["kind"], content=row["content"], hash=row["hash"],
            width=row["width"], height=row["height"], pinned=bool(row["pinned"]),
            created=row["created"], used=row["used"],
        )

    @staticmethod
    def _remove_files(item: Item) -> None:
        if item.kind != "image":
            return
        for p in (item.image_path, item.thumb_path):
            try:
                p.unlink(missing_ok=True)
            except OSError as exc:
                log.warning("Could not delete %s: %s", p, exc)
