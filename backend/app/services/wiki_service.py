"""LLM Wiki service — Karpathy-style personal knowledge base.

Three-layer architecture:
  Layer 1: raw/      — MinerU-converted markdown files (read-only source of truth)
  Layer 2: wiki/     — LLM-maintained structured knowledge entries
  Layer 3: schema/   — Configuration & rules for wiki organization
"""

import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class WikiPage:
    """A single wiki knowledge entry."""
    slug: str
    title: str
    content: str
    page_type: str = "entity"  # entity | concept | comparison | synthesis | index
    source_paper_ids: list[str] = field(default_factory=list)
    cross_refs: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def to_markdown(self) -> str:
        lines = [
            f"> title: {self.title}",
            f"> type: {self.page_type}",
            f"> created: {self.created_at}",
            f"> updated: {self.updated_at}",
        ]
        if self.source_paper_ids:
            lines.append(f"> sources: {', '.join(self.source_paper_ids)}")
        if self.cross_refs:
            ref_links = ", ".join(f"[[{ref}]]" for ref in self.cross_refs)
            lines.append(f"> see_also: {ref_links}")

        lines.extend([
            "",
            f"# {self.title}",
            "",
            self.content,
            "",
        ])

        return "\n".join(lines)

    @classmethod
    def from_markdown(cls, raw: str, slug: str) -> "WikiPage":
        page = cls(slug=slug, title=slug.replace("-", " ").title(), content=raw)
        frontmatter, body = _split_frontmatter(raw)
        page.content = body.strip()

        for line in frontmatter.split("\n"):
            line = line.strip().lstrip("> ")
            if line.startswith("title:"):
                page.title = line.split(":", 1)[1].strip()
            elif line.startswith("type:"):
                page.page_type = line.split(":", 1)[1].strip()
            elif line.startswith("sources:"):
                page.source_paper_ids = [part.strip() for part in line.split(":", 1)[1].split(",") if part.strip()]
            elif line.startswith("created:"):
                page.created_at = line.split(":", 1)[1].strip()
            elif line.startswith("updated:"):
                page.updated_at = line.split(":", 1)[1].strip()
            elif line.startswith("see_also:"):
                refs = line.split(":", 1)[1].strip()
                page.cross_refs = [part.strip("[] ") for part in refs.split(",") if part.strip("[] ")]

        return page


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]


def _split_frontmatter(raw: str) -> tuple[str, str]:
    """Split raw markdown into (frontmatter_lines, body)."""
    lines = raw.split("\n")
    fm_lines = []
    body_start = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(">"):
            fm_lines.append(stripped)
            body_start = i + 1
            continue
        break

    body = "\n".join(lines[body_start:]) if body_start else raw
    return "\n".join(fm_lines), body


class WikiService:
    """Manages the LLM Wiki knowledge base."""

    def __init__(self, kb_id: str = ""):
        self.kb_id = kb_id
        base = Path(settings.wiki_dir)
        self.wiki_dir = base / kb_id if kb_id else base
        self.raw_dir = self.wiki_dir / "raw"
        self.pages_dir = self.wiki_dir / "wiki"
        self.schema_dir = self.wiki_dir / "schema"

        self._page_cache: dict[str, WikiPage] = {}
        self._raw_source_cache: dict[str, str] = {}
        self._pages_list_cache: Optional[list[dict]] = None
        self._raw_sources_list_cache: Optional[list[dict]] = None
        self._all_pages_content_cache: Optional[list[dict]] = None

        self._ensure_dirs()
        self._ensure_schema()

    def _ensure_dirs(self):
        for directory in [self.raw_dir, self.pages_dir, self.schema_dir]:
            directory.mkdir(parents=True, exist_ok=True)

    def _ensure_schema(self):
        schema_path = self.schema_dir / "AGENTS.md"
        if schema_path.exists():
            return
        schema_path.write_text("""# LLM Wiki Schema

## Directory Structure
- `raw/` — Original markdown files (read-only). Each file is a converted paper/document.
- `wiki/` — Structured knowledge entries maintained by the LLM.
- `schema/` — This configuration file.

## Wiki Page Types
- **entity** — A concrete thing (person, paper, method, gene, dataset)
- **concept** — An abstract idea, theory, or framework
- **comparison** — Side-by-side comparison of ≥2 methods/approaches
- **synthesis** — Integration of multiple sources into a coherent narrative
- **index** — A hub page linking to related pages

## Writing Rules
1. Every page MUST have frontmatter: title, type, sources, created, updated
2. Use `[[page-slug]]` syntax for cross-references
3. When adding a new source, update ALL affected pages
4. Mark contradictions explicitly with `> ⚠️ CONTRADICTION:` blocks
5. Cite sources inline with `[src: paper_id]` notation
6. Keep pages focused — split if a page exceeds ~5000 chars
7. Use `> ⚠️ TODO:` to mark gaps for future research

## Ingestion Pipeline
1. Read new markdown from `raw/`
2. Extract: title, authors, key concepts, methods, findings
3. Create/update: entity pages for each key concept
4. Create/update: concept pages if this paper introduces new ideas
5. If this paper's methods overlap with existing pages → create comparison or update synthesis
6. Add cross-references between all affected pages
7. Run health-check: verify no broken links, flag contradictions
""", encoding="utf-8")

    def _invalidate_page_caches(self, slug: Optional[str] = None):
        if slug is not None:
            self._page_cache.pop(slug, None)
        else:
            self._page_cache.clear()
        self._pages_list_cache = None
        self._all_pages_content_cache = None

    def _invalidate_raw_caches(self, paper_id: Optional[str] = None):
        if paper_id is not None:
            self._raw_source_cache.pop(paper_id, None)
        else:
            self._raw_source_cache.clear()
        self._raw_sources_list_cache = None

    def add_raw_source(self, paper_id: str, markdown: str, metadata: dict) -> str:
        """Store a raw markdown source. Returns the file path."""
        raw_path = self.raw_dir / f"{paper_id}.md"
        header = (
            f"<!-- paper_id: {paper_id} -->\n"
            f"<!-- title: {metadata.get('title', '')} -->\n"
            f"<!-- authors: {metadata.get('authors', '')} -->\n"
            f"<!-- year: {metadata.get('year', '')} -->\n"
            f"<!-- ingested: {datetime.now(timezone.utc).isoformat()} -->\n\n"
        )
        raw_path.write_text(header + markdown, encoding="utf-8")
        self._invalidate_raw_caches(paper_id)
        logger.info("Raw source added: %s", raw_path)
        return str(raw_path)

    def add_raw_source_from_file(self, paper_id: str, source_path: Union[str, Path], metadata: dict) -> str:
        """Store a raw markdown source from an existing file without loading it all into memory."""
        raw_path = self.raw_dir / f"{paper_id}.md"
        header = (
            f"<!-- paper_id: {paper_id} -->\n"
            f"<!-- title: {metadata.get('title', '')} -->\n"
            f"<!-- authors: {metadata.get('authors', '')} -->\n"
            f"<!-- year: {metadata.get('year', '')} -->\n"
            f"<!-- ingested: {datetime.now(timezone.utc).isoformat()} -->\n\n"
        )

        with open(source_path, "r", encoding="utf-8", errors="replace") as src:
            with open(raw_path, "w", encoding="utf-8") as dst:
                dst.write(header)
                shutil.copyfileobj(src, dst, length=1024 * 1024)

        self._invalidate_raw_caches(paper_id)
        logger.info("Raw source copied from file: %s", raw_path)
        return str(raw_path)

    def get_raw_source(self, paper_id: str) -> str:
        """Read a raw markdown source."""
        if paper_id in self._raw_source_cache:
            return self._raw_source_cache[paper_id]

        raw_path = self.raw_dir / f"{paper_id}.md"
        if not raw_path.exists():
            self._raw_source_cache.pop(paper_id, None)
            return ""

        raw = raw_path.read_text(encoding="utf-8")
        self._raw_source_cache[paper_id] = raw
        return raw

    def list_raw_sources(self) -> list[dict]:
        """List all raw markdown sources with metadata."""
        if self._raw_sources_list_cache is not None:
            return list(self._raw_sources_list_cache)

        sources = []
        for file_path in sorted(self.raw_dir.glob("*.md")):
            paper_id = file_path.stem
            content = self.get_raw_source(paper_id)
            meta = {}
            for key in ["title", "authors", "year", "ingested"]:
                match = re.search(rf"<!-- {key}: (.+?) -->", content)
                if match:
                    meta[key] = match.group(1)
            sources.append({"paper_id": paper_id, "path": str(file_path), **meta})

        self._raw_sources_list_cache = sources
        return list(sources)

    def get_page(self, slug: str) -> Optional[WikiPage]:
        if slug in self._page_cache:
            return self._page_cache[slug]

        page_path = self.pages_dir / f"{slug}.md"
        if not page_path.exists():
            self._page_cache.pop(slug, None)
            return None

        page = WikiPage.from_markdown(page_path.read_text(encoding="utf-8"), slug)
        self._page_cache[slug] = page
        return page

    def save_page(self, page: WikiPage):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not page.created_at:
            page.created_at = now
        page.updated_at = now

        page_path = self.pages_dir / f"{page.slug}.md"
        page_path.write_text(page.to_markdown(), encoding="utf-8")
        self._page_cache[page.slug] = page
        self._pages_list_cache = None
        self._all_pages_content_cache = None
        logger.info("Wiki page saved: %s", page.slug)

    def list_pages(self) -> list[dict]:
        if self._pages_list_cache is not None:
            return list(self._pages_list_cache)

        pages = []
        for file_path in sorted(self.pages_dir.glob("*.md")):
            page = self.get_page(file_path.stem)
            if not page:
                continue
            pages.append({
                "slug": page.slug,
                "title": page.title,
                "page_type": page.page_type,
                "source_paper_ids": page.source_paper_ids,
                "updated_at": page.updated_at,
            })

        self._pages_list_cache = pages
        return list(pages)

    def delete_page(self, slug: str):
        page_path = self.pages_dir / f"{slug}.md"
        if page_path.exists():
            page_path.unlink()
            self._invalidate_page_caches(slug)
            logger.info("Wiki page deleted: %s", slug)

    def get_all_pages_content(self) -> list[dict]:
        """Return all wiki pages with full content for LLM context."""
        if self._all_pages_content_cache is not None:
            return list(self._all_pages_content_cache)

        pages = []
        for file_path in sorted(self.pages_dir.glob("*.md")):
            page = self.get_page(file_path.stem)
            if not page:
                continue
            pages.append({
                "slug": page.slug,
                "title": page.title,
                "content": page.content,
                "page_type": page.page_type,
                "source_paper_ids": page.source_paper_ids,
                "cross_refs": page.cross_refs,
            })

        self._all_pages_content_cache = pages
        return list(pages)

    def find_source_chunk(self, paper_id: str, query_text: str, context_window: int = 500) -> list[dict]:
        """Search within a raw source for relevant chunks matching the query.

        Returns list of {paper_id, excerpt, line_start, line_end} dicts.
        """
        raw = self.get_raw_source(paper_id)
        if not raw:
            return []

        clean = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL)
        lines = clean.split("\n")

        query_tokens = set(re.findall(r"[a-zA-Z0-9]{3,}", query_text.lower()))
        if not query_tokens:
            return []

        results = []
        scored_windows = []

        for i, line in enumerate(lines):
            line_lower = line.lower()
            score = sum(1 for token in query_tokens if token in line_lower)
            if score > 0:
                start = max(0, i - 3)
                end = min(len(lines), i + 4)
                excerpt = "\n".join(lines[start:end])
                scored_windows.append((score, start + 1, end, excerpt))

        scored_windows.sort(key=lambda item: -item[0])

        seen = set()
        for score, start, end, excerpt in scored_windows[:5]:
            key = f"{start}-{end}"
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "paper_id": paper_id,
                "excerpt": excerpt[:context_window],
                "line_start": start,
                "line_end": end,
            })

        return results


_wiki_services: dict[str, WikiService] = {}


def get_wiki_service(kb_id: str = "") -> WikiService:
    if kb_id not in _wiki_services:
        _wiki_services[kb_id] = WikiService(kb_id)
    return _wiki_services[kb_id]
