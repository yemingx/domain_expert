"""Database models — helper functions for CRUD operations using sqlite3."""

from __future__ import annotations

import json
import uuid
from datetime import datetime


def generate_id() -> str:
    return str(uuid.uuid4())


# --- Wiki KB operations ---

def create_wiki_kb(conn, *, name: str, description: str = "") -> dict:
    kb_id = generate_id()
    conn.execute(
        "INSERT INTO wiki_kbs (id, name, description) VALUES (?, ?, ?)",
        (kb_id, name, description),
    )
    return {"id": kb_id, "name": name, "description": description}


def list_wiki_kbs(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM wiki_kbs ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_wiki_kb(conn, kb_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM wiki_kbs WHERE id = ?", (kb_id,)).fetchone()
    return dict(row) if row else None


def delete_wiki_kb(conn, kb_id: str):
    conn.execute("DELETE FROM wiki_kbs WHERE id = ?", (kb_id,))


# --- Paper operations ---

def create_paper(conn, *, paper_id: str, filename: str, filepath: str, wiki_kb_id: str | None = None, status: str = "pending") -> dict:
    conn.execute(
        "INSERT INTO papers (id, filename, filepath, status, wiki_kb_id) VALUES (?, ?, ?, ?, ?)",
        (paper_id, filename, filepath, status, wiki_kb_id),
    )
    return {"id": paper_id, "filename": filename, "filepath": filepath, "status": status, "wiki_kb_id": wiki_kb_id}


def get_paper(conn, paper_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    if row is None:
        return None
    return _paper_row_to_dict(row)


def list_papers(conn, wiki_kb_id: str | None = None) -> list[dict]:
    if wiki_kb_id:
        rows = conn.execute("SELECT * FROM papers WHERE wiki_kb_id = ? ORDER BY created_at DESC", (wiki_kb_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM papers ORDER BY created_at DESC").fetchall()
    return [_paper_row_to_dict(r) for r in rows]


def update_paper(conn, paper_id: str, **kwargs):
    sets = []
    vals = []
    for k, v in kwargs.items():
        sets.append(f"{k} = ?")
        vals.append(v)
    sets.append("updated_at = ?")
    vals.append(datetime.utcnow().isoformat())
    vals.append(paper_id)
    conn.execute(f"UPDATE papers SET {', '.join(sets)} WHERE id = ?", vals)


def count_papers(conn, status: str | None = None) -> int:
    if status:
        row = conn.execute("SELECT COUNT(*) FROM papers WHERE status = ?", (status,)).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) FROM papers").fetchone()
    return row[0]


def _paper_row_to_dict(row) -> dict:
    row_data = dict(row)
    authors_raw = row_data.get("authors")
    try:
        authors = json.loads(authors_raw) if authors_raw else []
    except (json.JSONDecodeError, TypeError):
        authors = []
    return {
        "id": row_data["id"],
        "title": row_data.get("title"),
        "authors": authors,
        "year": row_data.get("year"),
        "filename": row_data["filename"],
        "filepath": row_data["filepath"],
        "status": row_data.get("status", "pending"),
        "chunks_count": row_data.get("chunks_count", 0),
        "abstract": row_data.get("abstract"),
        "markdown_status": row_data.get("markdown_status", "none") or "none",
        "wiki_pages_count": row_data.get("wiki_pages_count", 0) or 0,
        "wiki_kb_id": row_data.get("wiki_kb_id"),
        "created_at": row_data.get("created_at"),
        "updated_at": row_data.get("updated_at"),
    }


# --- Chat session operations ---

def create_session(conn, session_id: str | None = None, title: str | None = None) -> dict:
    sid = session_id or generate_id()
    conn.execute("INSERT INTO chat_sessions (id, title) VALUES (?, ?)", (sid, title))
    return {"id": sid, "title": title}


def get_session(conn, session_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        return None
    return dict(row)


# --- Chat message operations ---

def add_message(conn, *, session_id: str, role: str, content: str, citations: str | None = None, agent_type: str | None = None) -> dict:
    msg_id = generate_id()
    conn.execute(
        "INSERT INTO chat_messages (id, session_id, role, content, citations, agent_type) VALUES (?, ?, ?, ?, ?, ?)",
        (msg_id, session_id, role, content, citations, agent_type),
    )
    return {"id": msg_id, "role": role, "content": content}


def get_messages(conn, session_id: str, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]
