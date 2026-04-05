"""
Script to process existing PDFs in the domain_pdf folder.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.services.pdf_processor import PDFProcessor
from app.services.vector_store import VectorStoreService


async def process_existing_pdfs():
    """Process all PDFs in the domain_pdf folder."""
    pdf_dir = Path(__file__).parent.parent / "domain_pdf"

    if not pdf_dir.exists():
        print(f"PDF directory not found: {pdf_dir}")
        return

    pdf_files = list(pdf_dir.glob("*.pdf"))
    print(f"Found {len(pdf_files)} PDF files")

    processor = PDFProcessor()
    vector_store = VectorStoreService()

    for i, pdf_file in enumerate(pdf_files, 1):
        print(f"\n[{i}/{len(pdf_files)}] Processing: {pdf_file.name}")

        try:
            # Process PDF
            metadata, chunks, full_text = processor.process_pdf(str(pdf_file))

            print(f"  - Title: {metadata.title or 'N/A'}")
            print(f"  - Year: {metadata.year or 'N/A'}")
            print(f"  - Authors: {', '.join(metadata.authors[:3]) if metadata.authors else 'N/A'}")
            print(f"  - Chunks: {len(chunks)}")

            # Create paper ID from filename
            paper_id = f"paper_{i:03d}"

            # Convert chunks to dict format
            chunk_dicts = []
            for j, chunk in enumerate(chunks):
                chunk_dicts.append({
                    "content": chunk.content,
                    "level": chunk.level,
                    "section_type": chunk.section_type,
                    "subsection_title": chunk.subsection_title,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "index": j
                })

            # Add to vector store
            embedding_ids = vector_store.add_chunks(
                chunks=chunk_dicts,
                paper_id=paper_id,
                paper_metadata=metadata.__dict__
            )

            print(f"  - Embeddings created: {len(embedding_ids)}")

        except Exception as e:
            print(f"  - Error: {e}")
            continue

    print("\nProcessing complete!")
    print(f"Vector store stats: {vector_store.get_collection_stats()}")


if __name__ == "__main__":
    asyncio.run(process_existing_pdfs())
