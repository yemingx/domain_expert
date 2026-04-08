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
    current_stage: str = ""  # searching, enriching, analyzing, converting

    # Results
    papers: list[dict] = field(default_factory=list)
    error_message: str = ""
    result_path: str = ""  # Local path to Markdown report

    # Warnings / partial failures (shown in frontend)
    warnings: list[str] = field(default_factory=list)

    # Metadata
    year_range: dict = field(default_factory=dict)
    unique_institutions: int = 0

    # Pre-built ZIP path (populated after job completes)
    zip_path: str = ""

    # Timestamps
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""

    # ===== Checkpoint / Resume Support =====
    # Stage-level checkpoints for resume capability
    stage_completed: dict = field(default_factory=lambda: {
        "searching": False,
        "enriching": False,
        "analyzing": False,
        "converting": False,
    })
    # Per-paper processing status: {pmid: {"translated": bool, "analyzed": bool, "attempts": int}}
    paper_status: dict = field(default_factory=dict)
    # Last successful stage for resume
    last_successful_stage: str = ""
    # Retry counter for the current stage
    stage_retry_count: int = 0


class LiteratureResearchService:
    """Service for running literature research locally."""

    def __init__(self):
        self.jobs: dict[str, ResearchJob] = {}
        self._running_tasks: dict[str, "asyncio.Task"] = {}
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
        """Execute a research job using the local research module with checkpoint/resume support."""
        job = self.jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        if job.status == "running":
            raise ValueError(f"Job {job_id} is already running")

        job.status = "running"
        job.started_at = job.started_at or datetime.now().isoformat()
        self._save_job(job)

        try:
            # Import and run research module
            import sys
            from pathlib import Path
            import os

            # Support ANTHROPIC_AUTH_TOKEN as fallback for ANTHROPIC_API_KEY
            if not os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("ANTHROPIC_AUTH_TOKEN"):
                os.environ["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_AUTH_TOKEN"]

            # Log API key status (without revealing the key)
            if settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"):
                logger.info("ANTHROPIC_API_KEY is configured")
            elif settings.anthropic_auth_token or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
                logger.info("ANTHROPIC_AUTH_TOKEN is configured (will be used as ANTHROPIC_API_KEY)")
            else:
                logger.warning("No Anthropic API key configured - LLM features will be unavailable")

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

            # Compute output directory paths (used by multiple stages)
            import re as _re
            scripts_path = lr_path / "scripts"
            if str(scripts_path) not in sys.path:
                sys.path.insert(0, str(scripts_path))

            today = datetime.now().strftime("%Y-%m-%d")
            topic_label = job.topic
            _dm = _re.search(r'"(\d{4})[/\-](\d{2})[/\-](\d{2})', job.query)
            start_date = f"{_dm.group(1)}-{_dm.group(2)}-{_dm.group(3)}" if _dm else "2015-01-01"
            date_range = f"{start_date} 至 {today}"
            result_dir = lr_path / "result" / f"{topic_label}调研_{start_date}至{today}"
            result_dir.mkdir(parents=True, exist_ok=True)

            # ═══════════════════════════════════════════════════════════════════
            # STAGE 1: PubMed Search (with checkpoint resume)
            # ═══════════════════════════════════════════════════════════════════
            if not job.stage_completed.get("searching"):
                job.current_stage = "searching"
                self._save_job(job)

                from literature_research.research import run_research

                logger.info(f"[Stage 1/4] PubMed search for job {job_id}")

                result = await asyncio.to_thread(
                    run_research,
                    job.topic,
                    job.query,
                    max_papers=job.max_papers,
                )

                # Check if we got any papers
                if result.get("total_papers", 0) == 0:
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

                # Initialize paper status tracking
                for p in job.papers:
                    pmid = p.get("pmid") or p.get("doi") or str(hash(p.get("title", "")))
                    job.paper_status[pmid] = {
                        "translated": False,
                        "analyzed": False,
                        "translate_attempts": 0,
                        "analysis_attempts": 0,
                    }

                # Mark stage complete
                job.stage_completed["searching"] = True
                job.last_successful_stage = "searching"
                self._save_job(job)
                logger.info(f"[Stage 1/4] PubMed search completed: {job.total_papers} papers")
            else:
                logger.info(f"[Stage 1/4] PubMed search skipped (already completed)")

            # ═══════════════════════════════════════════════════════════════════
            # STAGE 2: Semantic Scholar Enrichment (with checkpoint resume)
            # ═══════════════════════════════════════════════════════════════════
            if not job.stage_completed.get("enriching"):
                logger.info("[Stage 2/4] Semantic Scholar enrichment skipped (removed)")
                job.stage_completed["enriching"] = True
                job.last_successful_stage = "enriching"
                self._save_job(job)

            # ═══════════════════════════════════════════════════════════════════
            # STAGE 3: LLM Analysis (with per-paper checkpoint resume)
            # ═══════════════════════════════════════════════════════════════════
            if not job.stage_completed.get("analyzing"):
                job.current_stage = "analyzing"
                self._save_job(job)

                logger.info(f"[Stage 3/4] LLM analysis for job {job_id}")

                _FAILED_SENTINEL = "分析失败"

                def _run_llm_analysis():
                    import time as _t
                    try:
                        # Clear module cache to ensure fresh SDK initialization with env vars
                        for _mod in ("utils", "analyze_content"):
                            sys.modules.pop(_mod, None)

                        from utils import translate_text, _call_llm as _test_llm_call
                        from analyze_content import analyze_paper_content, validate_analysis_complete
                        # Test LLM reachability (works via claude CLI even if SDK is blocked)
                        _llm_ok = bool(_test_llm_call("You are helpful.", "Reply OK", max_tokens=5))
                        logger.info(f"LLM analysis modules loaded (reachable: {_llm_ok})")

                        if not _llm_ok:
                            msg = "LLM 不可用（claude CLI 无法连接），翻译和深度分析已跳过。"
                            logger.warning(msg)
                            job.warnings.append(msg)
                            return

                        _analysis_keys = ["technical_route", "advantages", "limitations",
                                          "technical_barriers", "feasibility", "generalization"]

                        # Process each paper with individual checkpointing
                        for idx, paper in enumerate(job.papers, 1):
                            pmid = paper.get("pmid") or paper.get("doi") or str(hash(paper.get("title", "")))
                            status = job.paper_status.get(pmid, {})

                            # Skip if already fully processed
                            if status.get("translated") and status.get("analyzed"):
                                logger.info(f"[{idx}/{job.total_papers}] Skipping (already processed): {paper.get('title','')[:60]}")
                                job.analyzed_papers = max(job.analyzed_papers, idx)
                                continue

                            logger.info(f"[{idx}/{job.total_papers}] Analyzing: {paper.get('title','')[:60]}")

                            try:
                                # Translation (with individual retry)
                                if not status.get("translated"):
                                    if paper.get("title") and not paper.get("title_cn"):
                                        paper["title_cn"] = translate_text(paper["title"], type="title")
                                    if paper.get("abstract") and not paper.get("abstract_cn"):
                                        paper["abstract_cn"] = translate_text(paper["abstract"], type="abstract")
                                    status["translated"] = True
                                    status["translate_attempts"] = status.get("translate_attempts", 0) + 1

                                # 6-dimension analysis (with individual retry)
                                if not status.get("analyzed"):
                                    analysis = analyze_paper_content(
                                        paper["title"], paper.get("abstract", ""), paper.get("journal", "")
                                    )
                                    if not validate_analysis_complete(analysis):
                                        _t.sleep(5)
                                        analysis = analyze_paper_content(
                                            paper["title"], paper.get("abstract", ""), paper.get("journal", "")
                                        )
                                    paper.update(analysis)
                                    status["analyzed"] = True
                                    status["analysis_attempts"] = status.get("analysis_attempts", 0) + 1

                                job.analyzed_papers = idx

                            except Exception as ae:
                                logger.warning(f"Paper {idx} analysis failed (non-fatal): {ae}")
                                status["translate_attempts"] = status.get("translate_attempts", 0) + 1
                                status["analysis_attempts"] = status.get("analysis_attempts", 0) + 1
                                # Continue to next paper, don't fail entire job

                            finally:
                                # Save progress after each paper
                                job.paper_status[pmid] = status
                                self._save_job(job)

                        # Post-analysis: retry failed papers
                        logger.info(f"[Review] Checking {len(job.papers)} papers for completeness...")
                        retry_needed = []
                        for p in job.papers:
                            pmid = p.get("pmid") or p.get("doi") or str(hash(p.get("title", "")))
                            status = job.paper_status.get(pmid, {})
                            missing = []
                            if not (p.get("abstract_cn") or "").strip() and not status.get("translated"):
                                missing.append("中文摘要")
                            if any((p.get(k) or "") in (_FAILED_SENTINEL, "", "摘要缺失，无法分析")
                                   for k in _analysis_keys):
                                missing.append("深度分析")
                            if missing:
                                retry_needed.append((p, missing, pmid))

                        if retry_needed:
                            logger.info(f"[Review] Found {len(retry_needed)} papers needing retry...")
                            for p, missing, pmid in retry_needed:
                                title_short = p.get("title", "")[:50]
                                logger.info(f"[Retry] {title_short} — missing: {missing}")
                                try:
                                    if "中文摘要" in missing and p.get("abstract"):
                                        p["abstract_cn"] = translate_text(p["abstract"], type="abstract")
                                    if "深度分析" in missing:
                                        analysis = analyze_paper_content(
                                            p["title"], p.get("abstract", ""), p.get("journal", "")
                                        )
                                        p.update(analysis)
                                    # Mark as complete on successful retry
                                    job.paper_status[pmid]["translated"] = True
                                    job.paper_status[pmid]["analyzed"] = True
                                except Exception as re_err:
                                    logger.warning(f"[Retry] Failed: {re_err}")
                                    job.paper_status[pmid]["failed"] = True

                            self._save_job(job)

                        # Final review: generate warnings
                        failed_analysis = [p.get("title", "")[:50] for p in job.papers
                                           if any((p.get(k) or "") in (_FAILED_SENTINEL, "摘要缺失，无法分析")
                                                  for k in _analysis_keys)]
                        failed_trans = [p.get("title", "")[:50] for p in job.papers
                                        if not (p.get("abstract_cn") or "").strip() and p.get("abstract")]

                        if failed_analysis:
                            msg = (f"深度分析失败 {len(failed_analysis)}/{len(job.papers)} 篇"
                                   f"（可能原因：LLM API 过载或网络抖动）")
                            logger.warning(f"[Review] {msg}")
                            job.warnings.append(msg)
                        if failed_trans:
                            msg = (f"中文翻译失败 {len(failed_trans)}/{len(job.papers)} 篇"
                                   f"（可能原因：LLM API 不可用）")
                            logger.warning(f"[Review] {msg}")
                            job.warnings.append(msg)

                        if not failed_analysis and not failed_trans:
                            logger.info(f"[Review] Passed: all {len(job.papers)} papers analyzed completely")

                        logger.info(f"LLM analysis completed for job {job_id}")

                    except Exception as analysis_err:
                        msg = f"LLM 分析流程异常中断: {analysis_err}"
                        logger.warning(f"LLM analysis failed (non-fatal): {analysis_err}")
                        job.warnings.append(msg)

                await asyncio.to_thread(_run_llm_analysis)

                # Mark stage complete
                job.stage_completed["analyzing"] = True
                job.last_successful_stage = "analyzing"
                self._save_job(job)
                logger.info(f"[Stage 3/4] LLM analysis completed")
            else:
                logger.info(f"[Stage 3/4] LLM analysis skipped (already completed)")

            # ═══════════════════════════════════════════════════════════════════
            # STAGE 4: Report Generation (with checkpoint resume)
            # ═══════════════════════════════════════════════════════════════════
            if not job.stage_completed.get("converting"):
                job.current_stage = "converting"
                self._save_job(job)

                logger.info(f"[Stage 4/4] Report generation for job {job_id}")

                from generate_report import generate_markdown_report, save_markdown

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

                # Auto-conversion: Word / HTML / HTML-PPT / PDF-PPT
                # Skip HTML/PDF generation when total papers > 100 to avoid
                # excessive resource usage; only Markdown report is produced.
                if md_path and md_path.exists() and job.total_papers <= 100:
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

                    # Pre-build ZIP
                    try:
                        await asyncio.to_thread(
                            self._prebuild_zip, job, md_path, result_dir
                        )
                        logger.info(f"Pre-built ZIP ready for job {job_id}")
                    except Exception as zip_err:
                        logger.warning(f"Pre-built ZIP failed (non-fatal): {zip_err}")
                elif md_path and md_path.exists() and job.total_papers > 100:
                    logger.info(
                        f"Skipping HTML/PDF conversion for job {job_id}: "
                        f"total_papers={job.total_papers} exceeds 100-paper limit"
                    )

                # Mark stage complete
                job.stage_completed["converting"] = True
                job.last_successful_stage = "converting"
                self._save_job(job)
                logger.info(f"[Stage 4/4] Report generation completed")
            else:
                logger.info(f"[Stage 4/4] Report generation skipped (already completed)")

            # ═══════════════════════════════════════════════════════════════════
            # FINAL: Mark job complete
            # ═══════════════════════════════════════════════════════════════════
            job.status = "completed"
            job.current_stage = "completed"
            job.completed_at = datetime.now().isoformat()
            self._save_job(job)
            logger.info(f"Research job {job_id} completed: {job.total_papers} papers")

            return job

        except Exception as e:
            logger.exception(f"Research job {job_id} failed")
            job.status = "failed"
            job.error_message = f"{str(e)}. Note: Network or API instability may have caused this failure. You can retry the job to resume from the last successful stage ({job.last_successful_stage or 'none'})."
            job.stage_retry_count += 1
            self._save_job(job)
            return job

    def _prebuild_zip(self, job: "ResearchJob", md_path: Path, result_dir: Path) -> None:
        """Build a zip archive of all report files and save it to disk.

        The zip is stored as ``<result_dir>/<topic>_<job_id[:8]>_reports.zip``.
        ``job.zip_path`` is updated and the job is persisted so the download
        endpoint can serve the file directly without re-building it.
        """
        import io
        import zipfile

        # ── Raw paper-list Markdown (same content as the download endpoint) ──
        yr = job.year_range or {}
        md_lines = [
            f"# 文献调研报告：{job.topic}",
            "",
            f"**查询**：`{job.query}`",
            f"**最大文献数**：{job.max_papers}",
            f"**实际获取**：{job.total_papers}",
            f"**年份范围**：{yr.get('min', 'N/A')} – {yr.get('max', 'N/A')}",
            f"**创建时间**：{job.created_at}",
            f"**完成时间**：{job.completed_at}",
            "", "---", "", "## 文献列表", "",
        ]
        for i, p in enumerate(job.papers, 1):
            md_lines.append(f"### {i}. {p.get('title', '无标题')}")
            md_lines.append("")
            display = p.get("author_display") or p.get("first_author", "Unknown")
            md_lines.append(f"- **作者**: {display}")
            md_lines.append(
                f"- **期刊**: {p.get('journal', '')} (IF: {p.get('journal_if', 'N/A')})"
            )
            md_lines.append(f"- **年份**: {p.get('year', '')}")
            if p.get("pmid"):
                md_lines.append(f"- **PMID**: {p['pmid']}")
            if p.get("doi"):
                md_lines.append(f"- **DOI**: {p['doi']}")
            abstract = p.get("abstract", "")
            if abstract and abstract not in ("No abstract", ""):
                md_lines.append(f"- **摘要**: {abstract}")
            md_lines.append("")
        raw_md_bytes = "\n".join(md_lines).encode("utf-8")
        raw_md_name = f"{job.topic}_{job.job_id[:8]}_raw.md"

        # ── Collect all disk files from result_dir ───────────────────────────
        stem = md_path.stem
        target_map = {
            "report_md": md_path,
            "word":      result_dir / f"{stem}.docx",
            "html":      result_dir / f"{stem}_阅读版.html",
            "html_ppt":  result_dir / f"{stem}_ppt.html",
            "pdf_ppt":   result_dir / f"{stem}_ppt.pdf",
        }

        zip_name = f"{job.topic}_{job.job_id[:8]}_reports.zip"
        zip_path = result_dir / zip_name

        with zipfile.ZipFile(str(zip_path), "w", compression=zipfile.ZIP_STORED) as zf:
            zf.writestr(raw_md_name, raw_md_bytes)
            for fp in target_map.values():
                if fp.exists():
                    zf.write(str(fp), fp.name)

        job.zip_path = str(zip_path)
        self._save_job(job)
        logger.info(f"Pre-built ZIP saved: {zip_path} ({zip_path.stat().st_size // 1024} KB)")

    def get_job(self, job_id: str) -> Optional[ResearchJob]:
        """Get job by ID."""
        return self.jobs.get(job_id)

    async def retry_job(self, job_id: str) -> ResearchJob:
        """Retry a failed job, resuming from the last successful stage.

        This allows recovery from network instability or LLM API failures
        without losing progress on completed stages.
        """
        job = self.jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        if job.status == "running":
            raise ValueError(f"Job {job_id} is already running")

        if job.status == "completed":
            raise ValueError(f"Job {job_id} is already completed")

        # Reset status but keep checkpoint data
        job.status = "pending"
        job.error_message = ""
        job.current_stage = job.last_successful_stage or ""

        logger.info(f"Retrying job {job_id}: resuming from stage '{job.current_stage or 'beginning'}' "
                    f"(stages completed: {job.stage_completed})")

        self._save_job(job)

        # Run the job - it will skip completed stages automatically
        return await self.run_job(job_id)

    def reset_job(self, job_id: str) -> ResearchJob:
        """Reset a job to initial state, clearing all progress.

        Use this when you want to start fresh rather than resume.
        """
        job = self.jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        if job.status == "running":
            raise ValueError(f"Cannot reset running job {job_id}")

        # Clear all checkpoint data
        job.status = "pending"
        job.error_message = ""
        job.current_stage = ""
        job.last_successful_stage = ""
        job.stage_completed = {
            "searching": False,
            "enriching": False,
            "analyzing": False,
            "converting": False,
        }
        job.paper_status = {}
        job.papers = []
        job.total_papers = 0
        job.processed_papers = 0
        job.analyzed_papers = 0
        job.stage_retry_count = 0
        job.warnings = []

        logger.info(f"Reset job {job_id} to initial state")
        self._save_job(job)
        return job

    def delete_job(self, job_id: str, force: bool = False) -> bool:
        """Delete a job, its metadata file, and its result folder on disk.

        If *force* is True, a running job will be cancelled first.

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
            if not force:
                raise ValueError(f"Cannot delete running job {job_id}")
            # Cancel the asyncio task if tracked
            task = self._running_tasks.pop(job_id, None)
            if task and not task.done():
                task.cancel()
                logger.info(f"Cancelled running task for job {job_id}")
            job.status = "failed"
            job.error_message = "Forcefully stopped by user"
            self._save_job(job)
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
