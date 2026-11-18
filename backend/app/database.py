"""SQLite, conexiones cortas por operación: seguro entre API y worker."""
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS videos (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def put(self, table: str, item: dict) -> dict:
        assert table in {"videos", "jobs"}
        with self.connect() as conn:
            conn.execute(f"INSERT OR REPLACE INTO {table} (id,payload) VALUES (?,?)", (item["id"], json.dumps(item)))
        return item

    def get(self, table: str, identifier: str) -> dict | None:
        assert table in {"videos", "jobs"}
        with self.connect() as conn:
            row = conn.execute(f"SELECT payload FROM {table} WHERE id=?", (identifier,)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, table: str) -> list[dict]:
        assert table in {"videos", "jobs"}
        with self.connect() as conn:
            rows = conn.execute(f"SELECT payload FROM {table} ORDER BY rowid DESC").fetchall()
        return [json.loads(row[0]) for row in rows]
