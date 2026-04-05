"""PDF processor with hierarchical chunking."""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


@dataclass
class PaperMetadata:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int = 0
    abstract: str = ""
    num_pages: int = 0
    filename: str = ""


@dataclass
class TextChunk:
    content: str = ""
    level: str = "atomic"  # document, section, subsection, atomic
    section_type: str = ""
    subsection_title: str = ""
    page_start: int = 0
    page_end: int = 0


class PDFProcessor:
    ATOMIC_CHUNK_SIZE = 800
    ATOMIC_OVERLAP = 100

    def process_pdf(self, pdf_path: str) -> tuple[PaperMetadata, list[TextChunk], str]:
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        doc = fitz.open(str(path))
        metadata = self._extract_metadata(doc, path.name)
        sections = self._extract_sections(doc)
        full_text = "\n".join(s["text"] for s in sections)
        chunks = self._create_hierarchical_chunks(sections)

        doc.close()
        return metadata, chunks, full_text

    def _extract_metadata(self, doc: fitz.Document, filename: str) -> PaperMetadata:
        meta = PaperMetadata(filename=filename, num_pages=len(doc))

        # Try to get title from PDF metadata
        pdf_meta = doc.metadata
        if pdf_meta.get("title"):
            meta.title = pdf_meta["title"]
        if pdf_meta.get("author"):
            meta.authors = [a.strip() for a in pdf_meta["author"].split(",")]

        # Try extracting title from first page (usually largest font)
        if not meta.title and len(doc) > 0:
            page = doc[0]
            blocks = page.get_text("dict")["blocks"]
            max_size = 0
            title_text = ""
            for block in blocks:
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        if span["size"] > max_size and len(span["text"].strip()) > 5:
                            max_size = span["size"]
                            title_text = span["text"].strip()
            if title_text:
                meta.title = title_text

        # Try to extract year from text
        first_page_text = doc[0].get_text() if len(doc) > 0 else ""
        year_match = re.search(r'(20[0-2]\d)', first_page_text)
        if year_match:
            meta.year = int(year_match.group(1))

        # Extract abstract
        full_first_pages = ""
        for i in range(min(2, len(doc))):
            full_first_pages += doc[i].get_text()
        abstract_match = re.search(
            r'(?:abstract|summary)[:\s]*\n?(.*?)(?:\n\s*(?:introduction|keywords|1\s|1\.)\s)',
            full_first_pages,
            re.IGNORECASE | re.DOTALL,
        )
        if abstract_match:
            meta.abstract = abstract_match.group(1).strip()[:2000]

        if not meta.title:
            meta.title = filename.replace(".pdf", "").replace("_", " ")

        return meta

    def _extract_sections(self, doc: fitz.Document) -> list[dict]:
        sections = []
        current_section = {"title": "Introduction", "text": "", "page_start": 0, "page_end": 0}

        section_pattern = re.compile(
            r'^(?:\d+\.?\s+)?(?:abstract|introduction|methods?|results?|discussion|conclusion|'
            r'references|acknowledgment|supplementary|materials?\s+and\s+methods?|'
            r'background|related\s+work|experimental|figures?|tables?)',
            re.IGNORECASE,
        )

        for page_num in range(len(doc)):
            page = doc[page_num]
            blocks = page.get_text("dict")["blocks"]

            for block in blocks:
                if "lines" not in block:
                    continue

                block_text = ""
                is_heading = False

                for line in block["lines"]:
                    line_text = ""
                    max_font_size = 0
                    for span in line["spans"]:
                        line_text += span["text"]
                        max_font_size = max(max_font_size, span["size"])
                        if span.get("flags", 0) & 2**4:  # Bold flag
                            is_heading = True

                    if max_font_size > 12 and len(line_text.strip()) < 100:
                        is_heading = True

                    block_text += line_text + "\n"

                block_text = block_text.strip()
                if not block_text:
                    continue

                if is_heading and section_pattern.match(block_text):
                    if current_section["text"].strip():
                        sections.append(current_section)
                    current_section = {
                        "title": block_text.split("\n")[0].strip(),
                        "text": block_text,
                        "page_start": page_num,
                        "page_end": page_num,
                    }
                else:
                    current_section["text"] += "\n" + block_text
                    current_section["page_end"] = page_num

        if current_section["text"].strip():
            sections.append(current_section)

        return sections

    def _create_hierarchical_chunks(self, sections: list[dict]) -> list[TextChunk]:
        chunks = []

        # Document-level chunk (all text summary)
        all_text = "\n\n".join(s["text"][:500] for s in sections)
        if all_text:
            chunks.append(TextChunk(
                content=all_text[:3000],
                level="document",
                section_type="full_document",
                page_start=sections[0]["page_start"] if sections else 0,
                page_end=sections[-1]["page_end"] if sections else 0,
            ))

        for section in sections:
            # Section-level chunk
            if len(section["text"]) > 100:
                chunks.append(TextChunk(
                    content=section["text"][:2000],
                    level="section",
                    section_type=section["title"],
                    page_start=section["page_start"],
                    page_end=section["page_end"],
                ))

            # Atomic-level chunks
            text = section["text"]
            start = 0
            while start < len(text):
                end = start + self.ATOMIC_CHUNK_SIZE
                chunk_text = text[start:end]

                if len(chunk_text.strip()) > 50:
                    chunks.append(TextChunk(
                        content=chunk_text.strip(),
                        level="atomic",
                        section_type=section["title"],
                        page_start=section["page_start"],
                        page_end=section["page_end"],
                    ))

                start = end - self.ATOMIC_OVERLAP

        return chunks
