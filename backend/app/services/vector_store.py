"""Vector store using SQLite FTS5 — no external dependencies, instant startup."""

import logging
import re
import sqlite3
from typing import Iterable, Optional, Union

from app.core.config import settings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "domain_papers"
WRITE_BATCH_SIZE = 128

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_chunks (
    chunk_id    TEXT PRIMARY KEY,
    content     TEXT NOT NULL,
    paper_id    TEXT NOT NULL,
    title       TEXT DEFAULT '',
    authors     TEXT DEFAULT '',
    year        INTEGER DEFAULT 0,
    level       TEXT DEFAULT 'atomic',
    section_type TEXT DEFAULT '',
    page_start  INTEGER DEFAULT 0,
    page_end    INTEGER DEFAULT 0,
    topic       TEXT DEFAULT '',
    wiki_kb_id  TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_chunks_paper ON paper_chunks(paper_id);
CREATE INDEX IF NOT EXISTS idx_chunks_topic ON paper_chunks(topic);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    tokenize = 'porter unicode61'
);
"""

MIGRATION_ADD_TOPIC = """
ALTER TABLE paper_chunks ADD COLUMN topic TEXT DEFAULT '';
"""

MIGRATION_ADD_WIKI_KB = """
ALTER TABLE paper_chunks ADD COLUMN wiki_kb_id TEXT DEFAULT '';
"""


class VectorStoreService:
    """SQLite FTS5-backed vector store with BM25 ranking."""

    def __init__(self):
        # Use a dedicated DB file separate from the main app DB to avoid lock contention
        import os
        os.makedirs(settings.vector_db_path, exist_ok=True)
        self.db_path = os.path.join(settings.vector_db_path, "chunks.db")
        self._init_db()
        logger.info("VectorStore ready (SQLite FTS5 mode)")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-20000")
        conn.execute("PRAGMA mmap_size=268435456")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self):
        conn = self._connect()
        conn.executescript(SCHEMA)
        # Run migrations for columns that may not exist yet
        for migration in [MIGRATION_ADD_TOPIC, MIGRATION_ADD_WIKI_KB]:
            try:
                conn.execute(migration)
                conn.commit()
            except Exception:
                pass
        # Create indexes that depend on migrated columns (may fail if col missing, try after migration)
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_wiki_kb ON paper_chunks(wiki_kb_id)")
            conn.commit()
        except Exception:
            pass
        conn.close()

    # ------------------------------------------------------------------ #
    #  Write                                                               #
    # ------------------------------------------------------------------ #

    def add_chunks(
        self,
        chunks: Iterable[dict],
        paper_id: str,
        paper_metadata: dict,
        topic: str = "",
        wiki_kb_id: str = "",
    ) -> list[str]:
        return self._add_chunks(
            chunks=chunks,
            paper_id=paper_id,
            paper_metadata=paper_metadata,
            topic=topic,
            wiki_kb_id=wiki_kb_id,
            return_ids=True,
        )

    def add_chunks_count(
        self,
        chunks: Iterable[dict],
        paper_id: str,
        paper_metadata: dict,
        topic: str = "",
        wiki_kb_id: str = "",
    ) -> int:
        return self._add_chunks(
            chunks=chunks,
            paper_id=paper_id,
            paper_metadata=paper_metadata,
            topic=topic,
            wiki_kb_id=wiki_kb_id,
            return_ids=False,
        )

    def _add_chunks(
        self,
        chunks: Iterable[dict],
        paper_id: str,
        paper_metadata: dict,
        topic: str = "",
        wiki_kb_id: str = "",
        return_ids: bool = True,
    ) -> Union[list[str], int]:
        conn = self._connect()
        ids: list[str] = []
        total = 0
        try:
            conn.execute("BEGIN IMMEDIATE")
            pending_rows: list[tuple] = []

            for i, chunk in enumerate(chunks):
                cid = f"{paper_id}_chunk_{i:04d}"
                content = str(chunk.get("content", "") or "").strip()
                if not content:
                    continue
                kb_id = wiki_kb_id or paper_metadata.get("wiki_kb_id", "")
                pending_rows.append(
                    (
                        cid,
                        content,
                        paper_id,
                        str(paper_metadata.get("title", "")),
                        str(paper_metadata.get("authors", "")),
                        int(paper_metadata.get("year") or 0),
                        chunk.get("level", "atomic"),
                        chunk.get("section_type", ""),
                        int(chunk.get("page_start") or 0),
                        int(chunk.get("page_end") or 0),
                        str(topic or paper_metadata.get("topic", "")),
                        str(kb_id),
                    )
                )
                total += 1
                if return_ids:
                    ids.append(cid)

                if len(pending_rows) >= WRITE_BATCH_SIZE:
                    self._flush_chunk_batch(conn, pending_rows)
                    pending_rows.clear()

            if pending_rows:
                self._flush_chunk_batch(conn, pending_rows)

            conn.commit()
            logger.info("Added %d chunks for paper %s", total, paper_id)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return ids if return_ids else total

    def delete_paper(self, paper_id: str):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM chunks_fts WHERE rowid IN (SELECT rowid FROM paper_chunks WHERE paper_id = ?)",
                (paper_id,),
            )
            conn.execute("DELETE FROM paper_chunks WHERE paper_id = ?", (paper_id,))
            conn.commit()
            logger.info("Deleted chunks for paper %s", paper_id)
        finally:
            conn.close()

    def delete_by_topic(self, topic: str) -> int:
        """Delete all chunks scoped to a topic. Returns count deleted."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM chunks_fts WHERE rowid IN (SELECT rowid FROM paper_chunks WHERE topic = ?)",
                (topic,),
            )
            result = conn.execute(
                "DELETE FROM paper_chunks WHERE topic = ?", (topic,)
            )
            conn.commit()
            count = result.rowcount
            logger.info("Deleted %d chunks for topic '%s'", count, topic)
            return count
        finally:
            conn.close()

    def delete_by_wiki_kb(self, wiki_kb_id: str) -> int:
        """Delete all chunks scoped to a wiki KB. Returns count deleted."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM chunks_fts WHERE rowid IN (SELECT rowid FROM paper_chunks WHERE wiki_kb_id = ?)",
                (wiki_kb_id,),
            )
            result = conn.execute(
                "DELETE FROM paper_chunks WHERE wiki_kb_id = ?", (wiki_kb_id,)
            )
            conn.commit()
            count = result.rowcount
            logger.info("Deleted %d chunks for wiki KB '%s'", count, wiki_kb_id)
            return count
        finally:
            conn.close()

    def _flush_chunk_batch(self, conn: sqlite3.Connection, rows: list[tuple]) -> None:
        conn.executemany(
            """
            INSERT INTO paper_chunks
                (chunk_id, content, paper_id, title, authors, year,
                 level, section_type, page_start, page_end, topic, wiki_kb_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chunk_id) DO UPDATE SET
                content=excluded.content,
                title=excluded.title,
                authors=excluded.authors,
                year=excluded.year,
                level=excluded.level,
                section_type=excluded.section_type,
                page_start=excluded.page_start,
                page_end=excluded.page_end,
                topic=excluded.topic,
                wiki_kb_id=excluded.wiki_kb_id
            """,
            rows,
        )

        chunk_ids = [row[0] for row in rows]
        placeholders = ",".join("?" for _ in chunk_ids)
        rowid_rows = conn.execute(
            f"SELECT chunk_id, rowid FROM paper_chunks WHERE chunk_id IN ({placeholders})",
            chunk_ids,
        ).fetchall()
        content_by_id = {row[0]: row[1] for row in rows}
        fts_rows = [
            (row["rowid"], content_by_id[row["chunk_id"]])
            for row in rowid_rows
        ]
        conn.executemany(
            "INSERT OR REPLACE INTO chunks_fts(rowid, content) VALUES (?, ?)",
            fts_rows,
        )


    def query(
        self,
        query_text: str,
        n_results: int = 10,
        where_filter: Optional[dict] = None,
    ) -> list[dict]:
        paper_id_filter = (where_filter or {}).get("paper_id")
        topic_filter = (where_filter or {}).get("topic")
        topics_filter: list[str] = (where_filter or {}).get("topics", [])
        wiki_kb_filter = (where_filter or {}).get("wiki_kb_id")

        if not query_text.strip():
            return self._fetch_chunks(
                paper_id=paper_id_filter, topic=topic_filter,
                topics=topics_filter, limit=n_results,
                wiki_kb_id=wiki_kb_filter,
            )

        fts_q = self._build_fts_query(query_text)
        if not fts_q:
            return self._fetch_chunks(
                paper_id=paper_id_filter, topic=topic_filter,
                topics=topics_filter, limit=n_results,
                wiki_kb_id=wiki_kb_filter,
            )

        conn = self._connect()
        try:
            conditions = ["chunks_fts MATCH ?"]
            params: list = [fts_q]

            if paper_id_filter:
                conditions.append("pc.paper_id = ?")
                params.append(paper_id_filter)
            if topic_filter:
                conditions.append("pc.topic = ?")
                params.append(topic_filter)
            elif topics_filter:
                placeholders = ",".join("?" * len(topics_filter))
                conditions.append(f"pc.topic IN ({placeholders})")
                params.extend(topics_filter)
            if wiki_kb_filter:
                conditions.append("pc.wiki_kb_id = ?")
                params.append(wiki_kb_filter)

            where_clause = " AND ".join(conditions)
            sql = f"""
                SELECT pc.chunk_id, pc.content, pc.paper_id, pc.title,
                       pc.authors, pc.year, pc.level, pc.section_type,
                       pc.page_start, pc.page_end, pc.topic,
                       chunks_fts.rank AS score
                FROM chunks_fts
                JOIN paper_chunks pc ON chunks_fts.rowid = pc.rowid
                WHERE {where_clause}
                ORDER BY chunks_fts.rank
                LIMIT ?
            """
            params.append(n_results)
            rows = conn.execute(sql, params).fetchall()
        except Exception as exc:
            logger.warning("FTS query '%s' failed: %s", fts_q, exc)
            return self._fetch_chunks(
                paper_id=paper_id_filter, topic=topic_filter,
                topics=topics_filter, limit=n_results,
                wiki_kb_id=wiki_kb_filter,
            )
        finally:
            conn.close()

        return [self._row_to_dict(r) for r in rows]

    def list_topics(self) -> list[dict]:
        """List all topics with their paper and chunk counts."""
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT topic,
                       COUNT(DISTINCT paper_id) AS paper_count,
                       COUNT(*) AS chunk_count
                FROM paper_chunks
                WHERE topic != ''
                GROUP BY topic
                ORDER BY paper_count DESC
            """).fetchall()
            return [{"topic": r["topic"], "paper_count": r["paper_count"], "chunk_count": r["chunk_count"]} for r in rows]
        finally:
            conn.close()

    def query_by_paper(self, paper_id: str, n_results: int = 100) -> list[dict]:
        return self._fetch_chunks(paper_id=paper_id, limit=n_results)

    def get_collection_stats(self) -> dict:
        conn = self._connect()
        try:
            row = conn.execute("SELECT COUNT(*) FROM paper_chunks").fetchone()
            count = row[0] if row else 0
        finally:
            conn.close()
        return {"collection": COLLECTION_NAME, "total_chunks": count}

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _fetch_chunks(
        self,
        paper_id: Optional[str],
        limit: int,
        topic: Optional[str] = None,
        topics: Optional[list] = None,
        wiki_kb_id: Optional[str] = None,
    ) -> list[dict]:
        conn = self._connect()
        try:
            conditions = []
            params: list = []
            if paper_id:
                conditions.append("paper_id = ?")
                params.append(paper_id)
            if topic:
                conditions.append("topic = ?")
                params.append(topic)
            elif topics:
                placeholders = ",".join("?" * len(topics))
                conditions.append(f"topic IN ({placeholders})")
                params.extend(topics)
            if wiki_kb_id:
                conditions.append("wiki_kb_id = ?")
                params.append(wiki_kb_id)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            params.append(limit)
            rows = conn.execute(
                f"SELECT *, 0 AS score FROM paper_chunks {where} LIMIT ?", params
            ).fetchall()
        finally:
            conn.close()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _build_fts_query(text: str) -> str:
        """Convert natural-language text to an FTS5 query string."""
        # Keep alphanumeric tokens of length ≥ 2
        tokens = re.findall(r"[a-zA-Z0-9]{2,}", text)
        if not tokens:
            return ""
        # Use OR so partial matches still appear; limit tokens
        return " OR ".join(tokens[:20])

    @staticmethod
    def _row_to_dict(row) -> dict:
        d = dict(row)
        return {
            "content":      d.get("content", ""),
            "paper_id":     d.get("paper_id", ""),
            "title":        d.get("title", ""),
            "authors":      d.get("authors", ""),
            "year":         d.get("year", 0),
            "level":        d.get("level", ""),
            "section_type": d.get("section_type", ""),
            "page_start":   d.get("page_start", 0),
            "page_end":     d.get("page_end", 0),
            "topic":        d.get("topic", ""),
            "distance":     abs(d.get("score", 0) or 0),
        }


_vector_store: Optional[VectorStoreService] = None


def get_vector_store() -> VectorStoreService:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStoreService()
    return _vector_store
