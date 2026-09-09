import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", "/data/urls.db" if os.path.isdir("/data") else "./urls.db"))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def get_conn():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS links (
                code TEXT PRIMARY KEY,
                long_url TEXT NOT NULL,
                created_at TEXT NOT NULL,
                click_count INTEGER NOT NULL DEFAULT 0,
                last_clicked_at TEXT
            );
            CREATE TABLE IF NOT EXISTS clicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL REFERENCES links(code) ON DELETE CASCADE,
                clicked_at TEXT NOT NULL,
                referer TEXT,
                user_agent TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_clicks_code ON clicks(code);
            """
        )
