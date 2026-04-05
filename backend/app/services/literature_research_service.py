"""Literature research service - local deployment version.

Simplified API: only requires topic and NCBI query string.
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# Research results storage
RESEARCH_DIR = Path("./data/research")
RESEARCH_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class ResearchJob:
    """Research job status."""
    job_id: str = ""
    status: str = "pending"  # pending, running, completed, failed
    topic: str = ""  # Topic name
    query: str = ""  # NCBI query
    max_papers: int = 50  # Maximum papers to retrieve

    # Progress tracking
    total_papers: int = 0
    processed_papers: int = 0
    analyzed_papers: int = 0
    current_stage: str = ""  # searching, analyzing, converting

    # Results
    papers: list[dict] = field(default_factory=list)
    error_message: str = ""
    result_path: str = ""  # Local path to Markdown report

    # Metadata
    year_range: dict = field(default_factory=dict)
    unique_institutions: int = 0

    # Timestamps
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""


class LiteratureResearchService:
    """Service for running literature research locally."""

    def __init__(self):
        self.jobs: dict[str, ResearchJob] = {}
        self._load_existing_jobs()

    def _load_existing_jobs(self):
        """Load existing research jobs from disk.

        Completed jobs whose result folder has been deleted externally are
        treated as stale: their JSON metadata is removed and they are not loaded.
        """
        stale_files: list[Path] = []
        for job_file in RESEARCH_DIR.glob("*.json"):
            try:
                with open(job_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                job = ResearchJob(**{k: v for k, v in data.items() if k in ResearchJob.__dataclass_fields__})
                # Stale-check: completed job with a known result path whose folder is gone
                if job.result_path and job.status == "completed":
                    result_dir = Path(job.result_path).parent
                    if not result_dir.exists():
                        logger.warning(f"Removing stale job {job.job_id}: result folder deleted ({result_dir})")
                        stale_files.append(job_file)
                        continue
                self.jobs[job.job_id] = job
                # Migrate: persist default for any new fields missing on disk
                if 'max_papers' not in data:
                    self._save_job(job)
            except Exception as e:
                logger.warning(f"Failed to load job {job_file}: {e}")
        # Delete stale JSON files after all file handles are closed
        for f in stale_files:
            f.unlink(missing_ok=True)

    def _save_job(self, job: ResearchJob):
        """Save job to disk."""
        job_file = RESEARCH_DIR / f"{job.job_id}.json"
        with open(job_file, 'w', encoding='utf-8') as f:
            json.dump(job.__dict__, f, ensure_ascii=False, indent=2)

    def create_job(self, topic: str, query: str, max_papers: int = 50) -> ResearchJob:
        """Create a new research job.

        Args:
            topic: Topic name (e.g., "NIPD", "CRISPR")
            query: NCBI/PubMed query string (e.g., "NIPD[Title/Abstract] AND 2024[Date]")
            max_papers: Maximum number of papers to retrieve
        """
        job = ResearchJob(
            job_id=str(uuid.uuid4()),
            status="pending",
            topic=topic,
            query=query,
            max_papers=max_papers,
            created_at=datetime.now().isoformat(),
        )
        self.jobs[job.job_id] = job
        self._save_job(job)
        return job

    async def run_job(self, job_id: str) -> ResearchJob:
        """Execute a research job using the local research module."""
        job = self.jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        if job.status == "running":
            raise ValueError(f"Job {job_id} is already running")

        job.status = "running"
        job.started_at = datetime.now().isoformat()
        job.current_stage = "searching"
        self._save_job(job)

        try:
            # Import and run research module
            import sys
            from pathlib import Path
            import os

            # Force stdout/stderr to UTF-8 so emoji in 3rd-party scripts don't crash
            try:
                sys.stdout.reconfigure(encoding='utf-8', errors='replace')
                sys.stderr.reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                pass

            # backend/ directory (3 levels up from this file: services → app → backend)
            backend_path = Path(__file__).parent.parent.parent
            lr_path = backend_path / "literature_research"
            if str(backend_path) not in sys.path:
                sys.path.insert(0, str(backend_path))

            # Set proxy environment variables from config
            if settings.http_proxy:
                os.environ["HTTP_PROXY"] = settings.http_proxy
            if settings.https_proxy:
                os.environ["HTTPS_PROXY"] = settings.https_proxy

            from literature_research.research import run_research

            logger.info(f"Running research: topic={job.topic}, query={job.query}")

            # Run research — offload blocking HTTP calls to thread pool
            result = await asyncio.to_thread(
                run_research,
                job.topic,
                job.query,
                max_papers=job.max_papers,
            )

            # Check if we got any papers
            if result.get("total_papers", 0) == 0:
                # Check if there was an implicit error (no papers found)
                job.status = "failed"
                job.error_message = "No papers found. Possible causes: (1) Network timeout - check internet connection to PubMed, (2) Query returned no results, (3) API rate limit reached."
                job.completed_at = datetime.now().isoformat()
                self._save_job(job)
                logger.warning(f"Research job {job_id} completed with 0 papers")
                return job

            # Update job with results
            job.papers = result.get("papers", [])
            job.total_papers = result.get("total_papers", 0)
            job.processed_papers = job.total_papers
            job.year_range = result.get("year_range", {})
            job.unique_institutions = result.get("unique_institutions", 0)
            job.current_stage = "analyzing"
            # Keep status=running until analysis+report done
            self._save_job(job)
            logger.info(f"Research job {job_id} fetched: {job.total_papers} papers, starting analysis")

            # ── 计算输出目录（贯穿后续所有步骤）─────────────────────────────
            import re as _re
            scripts_path = lr_path / "scripts"
            if str(scripts_path) not in sys.path:
                sys.path.insert(0, str(scripts_path))
            from generate_report import generate_markdown_report, save_markdown

            today = datetime.now().strftime("%Y-%m-%d")
            topic_label = job.topic
            _dm = _re.search(r'"(\d{4})[/\-](\d{2})[/\-](\d{2})', job.query)
            start_date = f"{_dm.group(1)}-{_dm.group(2)}-{_dm.group(3)}" if _dm else "2015-01-01"
            date_range = f"{start_date} 至 {today}"
            result_dir = lr_path / "result" / f"{topic_label}调研_{start_date}至{today}"
            result_dir.mkdir(parents=True, exist_ok=True)

            # ── 原始 NCBI Markdown（LLM 分析前的快照）────────────────────────
            try:
                raw_md_content = generate_markdown_report(
                    job.papers, topic_label, date_range, days=0, topic_keyword=job.topic
                )
                raw_md_path = result_dir / f"{topic_label}_原始NCBI_{start_date}至{today}.md"
                save_markdown(raw_md_content, str(raw_md_path))
                logger.info(f"Raw NCBI Markdown saved: {raw_md_path}")
            except Exception as raw_err:
                logger.warning(f"Raw Markdown generation failed (non-fatal): {raw_err}")

            # ── LLM 分析：翻译 + 6维度深度分析（Anthropic SDK，线程池中运行）────
            def _run_llm_analysis():
                try:
                    for _mod in ("utils", "analyze_content"):
                        sys.modules.pop(_mod, None)

                    from utils import translate_text
                    from analyze_content import analyze_paper_content, validate_analysis_complete
                    logger.info("LLM analysis modules loaded (SDK mode)")

                    for idx, paper in enumerate(job.papers, 1):
                        logger.info(f"[{idx}/{job.total_papers}] 分析: {paper.get('title','')[:60]}")
                        try:
                            if paper.get("title"):
                                paper["title_cn"] = translate_text(paper["title"], type="title")
                            if paper.get("abstract"):
                                paper["abstract_cn"] = translate_text(paper["abstract"], type="abstract")
                            analysis = analyze_paper_content(
                                paper["title"], paper.get("abstract", ""), paper.get("journal", "")
                            )
                            if not validate_analysis_complete(analysis):
                                import time; time.sleep(3)
                                analysis = analyze_paper_content(
                                    paper["title"], paper.get("abstract", ""), paper.get("journal", "")
                                )
                            paper.update(analysis)
                        except Exception as ae:
                            logger.warning(f"Paper {idx} analysis failed (non-fatal): {ae}")
                        finally:
                            job.analyzed_papers = idx
                            self._save_job(job)
                    logger.info(f"LLM analysis completed for job {job_id}")
                except Exception as analysis_err:
                    logger.warning(f"LLM analysis failed (non-fatal): {analysis_err}")

            await asyncio.to_thread(_run_llm_analysis)

            # ── 富化 Markdown（含翻译 + 6维度分析）──────────────────────────
            md_path = None
            try:
                md_content = generate_markdown_report(
                    job.papers, topic_label, date_range, days=0, topic_keyword=job.topic
                )
                md_path = result_dir / f"{topic_label}_文献调研报告_{start_date}至{today}.md"
                save_markdown(md_content, str(md_path))
                job.result_path = str(md_path)
                self._save_job(job)
                logger.info(f"Enriched Markdown saved: {md_path}")
            except Exception as report_err:
                logger.warning(f"Enriched Markdown generation failed (non-fatal): {report_err}")

            # ── 自动转换：Word / HTML阅读版 / HTML-PPT / PDF-PPT ─────────────
            # 使用 subprocess 运行，避免 Playwright sync API 与 asyncio event loop 冲突
            if md_path and md_path.exists():
                job.current_stage = "converting"
                self._save_job(job)
                try:
                    import subprocess
                    md_to_reports_script = scripts_path / "md_to_reports.py"
                    proc = await asyncio.to_thread(
                        subprocess.run,
                        [
                            sys.executable,
                            str(md_to_reports_script),
                            "--input", str(md_path),
                            "--output-dir", str(result_dir),
                            "--formats", "word", "html", "html_ppt", "pdf_ppt",
                        ],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=600,
                    )
                    if proc.stdout:
                        logger.info(f"Conversion output:\n{proc.stdout.strip()}")
                    if proc.stderr:
                        logger.warning(f"Conversion stderr:\n{proc.stderr.strip()[:500]}")
                    logger.info(f"Auto-conversion completed (exit {proc.returncode}) for job {job_id}")
                except Exception as conv_err:
                    logger.warning(f"Auto-conversion failed (non-fatal): {conv_err}")

            # ── 最终标记完成 ─────────────────────────────────────────────────
            job.status = "completed"
            job.current_stage = "completed"
            job.completed_at = datetime.now().isoformat()
            self._save_job(job)
            logger.info(f"Research job {job_id} completed: {job.total_papers} papers")

            return job

        except Exception as e:
            logger.exception(f"Research job {job_id} failed")
            job.status = "failed"
            job.error_message = f"{str(e)}. Note: PubMed API may not be accessible from your network."
            job.completed_at = datetime.now().isoformat()
            self._save_job(job)
            return job

    def get_job(self, job_id: str) -> Optional[ResearchJob]:
        """Get job by ID."""
        return self.jobs.get(job_id)

    def delete_job(self, job_id: str) -> bool:
        """Delete a job, its metadata file, and its result folder on disk.

        On Windows, generated PDF files may still be locked by the Puppeteer/Node.js
        subprocess for a brief period after generation completes.  We use an onerror
        handler that strips read-only attributes and retries the removal, and we
        attempt a second pass after a short delay so that the OS has time to release
        file handles.
        """
        job = self.jobs.get(job_id)
        if not job:
            return False
        if job.status == "running":
            raise ValueError(f"Cannot delete running job {job_id}")
        # Delete result folder if present
        if job.result_path:
            result_dir = Path(job.result_path).parent
            if result_dir.exists() and result_dir.is_dir():
                import os
                import shutil
                import stat
                import time as _time

                def _on_rm_error(func, path, exc_info):
                    """onerror handler: make file writable and retry."""
                    try:
                        os.chmod(path, stat.S_IWRITE)
                        func(path)
                    except Exception:
                        pass  # will be retried below

                shutil.rmtree(result_dir, onerror=_on_rm_error)

                # Second-pass retry for files that were still locked (e.g. PDFs on Windows)
                if result_dir.exists():
                    _time.sleep(2)
                    shutil.rmtree(result_dir, onerror=_on_rm_error)

                if result_dir.exists():
                    logger.warning(
                        f"Could not fully remove result folder (some files may still be locked): {result_dir}"
                    )
                else:
                    logger.info(f"Deleted result folder: {result_dir}")

        del self.jobs[job_id]
        job_file = RESEARCH_DIR / f"{job_id}.json"
        if job_file.exists():
            job_file.unlink()
        return True

    def list_jobs(self) -> list[ResearchJob]:
        """List all jobs, sorted by creation time (newest first).

        Also purges any completed jobs whose result folder was deleted externally,
        so that a frontend poll/refresh reflects the actual disk state.
        """
        stale = [
            job_id for job_id, job in self.jobs.items()
            if job.result_path and job.status == "completed"
            and not Path(job.result_path).parent.exists()
        ]
        for job_id in stale:
            logger.info(f"Purging stale job {job_id}: result folder no longer exists")
            del self.jobs[job_id]
            job_file = RESEARCH_DIR / f"{job_id}.json"
            if job_file.exists():
                job_file.unlink()

        jobs = list(self.jobs.values())
        jobs.sort(key=lambda j: j.created_at or "", reverse=True)
        return jobs

    def get_completed_research(self) -> list[ResearchJob]:
        """Get list of completed research jobs."""
        return [j for j in self.jobs.values() if j.status == "completed"]

    def import_to_knowledge_base(self, job_id: str, vector_store) -> int:
        """Import research papers to the knowledge base (tagged by topic).

        Returns number of chunks added.
        """
        job = self.jobs.get(job_id)
        if not job or job.status != "completed":
            raise ValueError(f"Job {job_id} not found or not completed")

        total_chunks = 0

        for paper in job.papers:
            # Create chunks from paper
            chunks = self._paper_to_chunks(paper)
            if chunks:
                paper_metadata = {
                    "title": paper.get("title", ""),
                    "authors": [a.get("name", "") for a in paper.get("authors_meta", paper.get("authors", []))],
                    "year": paper.get("year", 0),
                    "journal": paper.get("journal", ""),
                    "doi": paper.get("doi", ""),
                    "pmid": paper.get("pmid", ""),
                    "topic": job.topic,
                }

                paper_id = paper.get("pmid") or paper.get("doi") or str(uuid.uuid4())
                chunk_ids = vector_store.add_chunks(
                    chunks=chunks,
                    paper_id=paper_id,
                    paper_metadata=paper_metadata,
                    topic=job.topic,   # Tag with research topic
                )
                total_chunks += len(chunk_ids)

        return total_chunks

    def _paper_to_chunks(self, paper: dict) -> list[dict]:
        """Convert paper to chunks for vector store."""
        chunks = []

        # Title chunk
        title = paper.get("title", "")
        if title:
            chunks.append({
                "content": f"Title: {title}",
                "level": "document",
                "section_type": "title",
                "page_start": 1,
                "page_end": 1,
            })

        # Abstract chunk
        abstract = paper.get("abstract", "")
        if abstract:
            chunks.append({
                "content": f"Abstract:\n{abstract}",
                "level": "section",
                "section_type": "abstract",
                "page_start": 1,
                "page_end": 1,
            })

        # Author metadata chunk
        authors = paper.get("authors", [])
        first_author = paper.get("first_author", "")
        corresponding = paper.get("corresponding_authors", [])

        author_info = f"""Author Information:
First Author: {first_author}
Corresponding Authors: {', '.join(corresponding)}
All Authors: {', '.join(a.get('name', '') for a in authors)}
Affiliations: {', '.join(paper.get('affiliations', []))}
"""
        chunks.append({
            "content": author_info,
            "level": "atomic",
            "section_type": "metadata",
            "page_start": 1,
            "page_end": 1,
        })

        return chunks


# Singleton
_research_service: Optional[LiteratureResearchService] = None


def get_research_service() -> LiteratureResearchService:
    """Get singleton research service."""
    global _research_service
    if _research_service is None:
        _research_service = LiteratureResearchService()
    return _research_service
