from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from .feeds import FeedResult, Item


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS feeds (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS seen (id TEXT PRIMARY KEY, first_seen TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS summaries (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, summary TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)

    def feeds(self) -> dict[str, FeedResult]:
        out = {}
        for ident, payload in self.db.execute("SELECT id,payload FROM feeds"):
            try:
                raw = json.loads(payload)
                raw["items"] = [Item(**v) for v in raw["items"]]
                out[ident] = FeedResult(**raw)
            except (ValueError, TypeError, KeyError):
                continue
        read = {v[0] for v in self.db.execute("SELECT id FROM seen WHERE is_read=1")}
        for feed in out.values():
            for item in feed.items:
                item.read = item.id in read
        return out

    def merge(self, result: FeedResult) -> tuple[FeedResult, list[Item]]:
        previous = self.feeds().get(result.source_id)
        if result.error:
            if previous:
                previous.error = result.error
                # Keep last successful timestamp and date: stale content stays visibly stale.
                result = previous
            self._save(result)
            return result, []
        known = {v[0]: bool(v[1]) for v in self.db.execute("SELECT id,is_read FROM seen")}
        fresh = [i for i in result.items if i.id not in known] if previous and previous.fetched_at and not (previous.error and not previous.items) else []
        stamp = datetime.now().astimezone().isoformat()
        with self.db:
            for item in result.items:
                item.read = known.get(item.id, False)
                self.db.execute("INSERT OR IGNORE INTO seen(id,first_seen) VALUES (?,?)", (item.id, stamp))
                cached = self.db.execute("SELECT fingerprint,summary FROM summaries WHERE id=?", (item.id,)).fetchone()
                if cached and cached[0] == fingerprint(item):
                    item.ai_summary = cached[1]
            cutoff = (datetime.now().astimezone() - timedelta(days=90)).isoformat()
            self.db.execute("DELETE FROM seen WHERE first_seen<?", (cutoff,))
            self.db.execute("DELETE FROM summaries WHERE id NOT IN (SELECT id FROM seen)")
        self._save(result)
        return result, fresh

    def _save(self, result: FeedResult):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO feeds VALUES (?,?)", (result.source_id, json.dumps(asdict(result), ensure_ascii=False)))

    def mark_read(self, ident: str):
        with self.db:
            self.db.execute("UPDATE seen SET is_read=1 WHERE id=?", (ident,))

    def save_summary(self, item: Item, text: str):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO summaries VALUES (?,?,?)", (item.id, fingerprint(item), text))

    def get(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value: str):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, value))

    def close(self):
        self.db.close()


def fingerprint(item: Item) -> str:
    import hashlib
    return hashlib.sha256((item.title + item.summary).encode()).hexdigest()
