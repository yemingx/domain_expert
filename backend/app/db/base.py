"""Database layer using built-in sqlite3 (no SQLAlchemy needed)."""

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager

from app.core.config import settings

logger = logging.getLogger(__name__)
_local = threading.local()


def _resolve_db_path() -> str:
    database_url = settings.database_url
    if database_url.startswith("sqlite:///"):
        return database_url.replace("sqlite:///", "", 1)

    fallback_path = "./data/domain_expert.db"
    logger.warning(
        "DATABASE_URL=%s is not supported by the sqlite backend; falling back to %s",
        database_url,
        fallback_path,
    )
    return fallback_path


DB_PATH = _resolve_db_path()

# Ensure parent directory exists
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS wiki_kbs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY,
    title TEXT,
    authors TEXT,
    year INTEGER,
    filename TEXT NOT NULL,
    filepath TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    chunks_count INTEGER DEFAULT 0,
    abstract TEXT,
    metadata_json TEXT,
    markdown_status TEXT DEFAULT 'none',
    wiki_pages_count INTEGER DEFAULT 0,
    wiki_kb_id TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (wiki_kb_id) REFERENCES wiki_kbs(id)
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    title TEXT,
    wiki_kb_id TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    citations TEXT,
    agent_type TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
);
"""


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str):
    existing_columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column in existing_columns:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def get_connection() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    _ensure_column(conn, "papers", "markdown_status", "markdown_status TEXT DEFAULT 'none'")
    _ensure_column(conn, "papers", "wiki_pages_count", "wiki_pages_count INTEGER DEFAULT 0")
    _ensure_column(conn, "papers", "wiki_kb_id", "wiki_kb_id TEXT")
    _ensure_column(conn, "papers", "updated_at", "updated_at TEXT")
    _ensure_column(conn, "chat_sessions", "wiki_kb_id", "wiki_kb_id TEXT")
    conn.commit()


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
