"""Database models — helper functions for CRUD operations using sqlite3."""

import json
import uuid
from datetime import datetime


def generate_id() -> str:
    return str(uuid.uuid4())


# --- Paper operations ---

def create_paper(conn, *, paper_id: str, filename: str, filepath: str, status: str = "pending") -> dict:
    conn.execute(
        "INSERT INTO papers (id, filename, filepath, status) VALUES (?, ?, ?, ?)",
        (paper_id, filename, filepath, status),
    )
    return {"id": paper_id, "filename": filename, "filepath": filepath, "status": status}


def get_paper(conn, paper_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    if row is None:
        return None
    return _paper_row_to_dict(row)


def list_papers(conn) -> list[dict]:
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
    authors_raw = row["authors"]
    try:
        authors = json.loads(authors_raw) if authors_raw else []
    except (json.JSONDecodeError, TypeError):
        authors = []
    return {
        "id": row["id"],
        "title": row["title"],
        "authors": authors,
        "year": row["year"],
        "filename": row["filename"],
        "filepath": row["filepath"],
        "status": row["status"],
        "chunks_count": row["chunks_count"],
        "abstract": row["abstract"],
        "created_at": row["created_at"],
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
