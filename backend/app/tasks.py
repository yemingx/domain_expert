"""Celery app and async tasks (optional — backend works without Celery)."""

import logging

from celery import Celery

from app.core.config import settings

logger = logging.getLogger(__name__)

celery_app = Celery(
    "domain_expert",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)


@celery_app.task(name="process_pdf_task", bind=True)
def process_pdf_task(self, paper_id: str, filepath: str):
    import json
    from app.services.pdf_processor import PDFProcessor
    from app.services.vector_store import get_vector_store
    from app.db.base import get_db
    from app.db import models as db

    with get_db() as conn:
        try:
            paper = db.get_paper(conn, paper_id)
            if not paper:
                logger.error(f"Paper {paper_id} not found")
                return {"status": "error", "message": "Paper not found"}

            db.update_paper(conn, paper_id, status="processing")

            processor = PDFProcessor()
            metadata, chunks, full_text = processor.process_pdf(filepath)

            authors_json = json.dumps(metadata.authors) if metadata.authors else None
            db.update_paper(
                conn, paper_id,
                title=metadata.title,
                authors=authors_json,
                year=metadata.year,
                abstract=metadata.abstract,
            )

            vector_store = get_vector_store()
            chunk_dicts = [
                {
                    "content": c.content,
                    "level": c.level,
                    "section_type": c.section_type,
                    "subsection_title": c.subsection_title,
                    "page_start": c.page_start,
                    "page_end": c.page_end,
                    "index": i,
                }
                for i, c in enumerate(chunks)
            ]

            embedding_ids = vector_store.add_chunks(
                chunks=chunk_dicts,
                paper_id=paper_id,
                paper_metadata={
                    "title": metadata.title,
                    "authors": metadata.authors,
                    "year": metadata.year,
                },
            )

            db.update_paper(conn, paper_id, chunks_count=len(embedding_ids), status="completed")
            logger.info(f"Paper {paper_id} processed: {len(embedding_ids)} chunks")
            return {"status": "completed", "chunks": len(embedding_ids)}

        except Exception as e:
            logger.error(f"Error processing paper {paper_id}: {e}")
            db.update_paper(conn, paper_id, status="failed")
            return {"status": "error", "message": str(e)}
