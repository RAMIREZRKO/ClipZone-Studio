"""SQLite, conexiones cortas por operación: seguro entre API y worker."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

TABLES = {"videos", "jobs", "analyses", "removals", "caption_tracks", "templates", "assets", "autoclips", "streamers",
          "settings"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, kind, value, traceback):
        try:
            return super().__exit__(kind, value, traceback)
        finally:
            self.close()


class Database:
    def __init__(self, path: Path):
        self.path = path
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS videos (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS analyses (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS removals (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS caption_tracks (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS templates (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS live_captures (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS autoclips (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS streamers (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=30, factory=ClosingConnection)

    def put(self, table: str, item: dict) -> dict:
        assert table in TABLES
        with self.connect() as conn:
            conn.execute(f"INSERT OR REPLACE INTO {table} (id,payload) VALUES (?,?)", (item["id"], json.dumps(item)))
        return item

    def get(self, table: str, identifier: str) -> dict | None:
        assert table in TABLES
        with self.connect() as conn:
            row = conn.execute(f"SELECT payload FROM {table} WHERE id=?", (identifier,)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, table: str, limit: int = -1) -> list[dict]:
        assert table in TABLES
        with self.connect() as conn:
            rows = conn.execute(f"SELECT payload FROM {table} ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def delete(self, table: str, identifier: str) -> None:
        assert table in TABLES
        with self.connect() as conn:
            conn.execute(f"DELETE FROM {table} WHERE id=?", (identifier,))

    def put_live_video(self, video: dict, capture: dict, candidate: dict | None = None) -> None:
        with self.connect() as conn:
            conn.execute("INSERT INTO videos (id,payload) VALUES (?,?)", (video["id"], json.dumps(video)))
            conn.execute("INSERT INTO live_captures (id,payload) VALUES (?,?)", (capture["id"], json.dumps(capture)))
            if candidate is not None:
                conn.execute("UPDATE autoclips SET payload=? WHERE id=?", (json.dumps(candidate), candidate["id"]))

    def live_captures(self) -> list[tuple[dict, dict | None]]:
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT live_captures.payload, videos.payload FROM live_captures
                LEFT JOIN videos ON videos.id = live_captures.id ORDER BY live_captures.rowid DESC
            """).fetchall()
        return [(json.loads(capture), json.loads(video) if video else None) for capture, video in rows]
