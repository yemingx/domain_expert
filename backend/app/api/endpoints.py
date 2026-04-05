"""API endpoints for the Domain Expert system."""

import asyncio
import csv
import io
import json
import logging
import os
import uuid
import zipfile

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import anthropic as _anthropic

from app.core.config import settings
from app.db.base import get_db
from app.db import models as db
from app.services.llm_service import get_llm_service
from app.services.vector_store import get_vector_store
from agents.coordinator import AgentCoordinator
from agents.base import AgentContext

from app.services.literature_research_service import (
    get_research_service,
    ResearchJob,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# --- Request/Response models ---

class QueryRequest(BaseModel):
    query: str
    paper_id: Optional[str] = None
    n_results: int = 10
    topic: Optional[str] = None        # Single topic filter
    topics: list[str] = []             # Multi-topic filter (OR logic)


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    paper_id: Optional[str] = None
    topic: Optional[str] = None        # Restrict to this expert KB
    topics: list[str] = []             # Restrict to these expert KBs (OR)


class CompareRequest(BaseModel):
    methods: list[str]
    aspects: list[str] = []


class DraftReviewRequest(BaseModel):
    topic: str
    user_perspective: str = ""
    section_type: str = "introduction"
    expert_topic: Optional[str] = None   # Which expert KB to use
    expert_topics: list[str] = []        # Multiple expert KBs


class CitationRequest(BaseModel):
    text: str
    n_results: int = 10
    expert_topic: Optional[str] = None
    expert_topics: list[str] = []


class EvaluateRequest(BaseModel):
    paper_id: str
    focus_areas: list[str] = []
    expert_topic: Optional[str] = None
    expert_topics: list[str] = []


# --- Research endpoints (NEW) ---

class ResearchRequest(BaseModel):
    topic: str  # Topic name (e.g., "NIPD", "CRISPR")
    query: str  # NCBI/PubMed query string (e.g., "NIPD[Title/Abstract] AND 2024[Date]")
    max_papers: int = 50  # Maximum number of papers to retrieve


class ResearchJobResponse(BaseModel):
    job_id: str
    status: str
    topic: str
    query: str
    max_papers: int = 50
    total_papers: int
    processed_papers: int
    analyzed_papers: int = 0
    current_stage: str
    created_at: str
    completed_at: Optional[str] = None
    error_message: str = ""
    result_path: str = ""  # Local path to Markdown report


@router.post("/research/run", response_model=ResearchJobResponse)
async def run_research(request: ResearchRequest):
    """Start a new literature research job.

    Example:
    {
        "topic": "NIPD",
        "query": "NIPD[Title/Abstract] AND monogenic[Title/Abstract] AND 2024[Date]"
    }
    """
    service = get_research_service()
    job = service.create_job(
        topic=request.topic,
        query=request.query,
        max_papers=request.max_papers,
    )
    # Run in background
    asyncio.create_task(service.run_job(job.job_id))
    return _job_to_response(job)


@router.get("/research/jobs", response_model=list[ResearchJobResponse])
async def list_research_jobs():
    """List all research jobs."""
    service = get_research_service()
    jobs = service.list_jobs()
    return [_job_to_response(j) for j in jobs]


@router.get("/research/jobs/{job_id}", response_model=ResearchJobResponse)
async def get_research_job(job_id: str):
    """Get a specific research job."""
    service = get_research_service()
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_response(job)


@router.delete("/research/jobs/{job_id}")
async def delete_research_job(job_id: str):
    """Delete a research job and its data file."""
    service = get_research_service()
    try:
        deleted = service.delete_job(job_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, "deleted": True}


@router.post("/research/import/{job_id}")
async def import_research_to_kb(job_id: str):
    """Import research results to knowledge base (tagged by topic)."""
    service = get_research_service()
    vs = get_vector_store()
    try:
        chunk_count = service.import_to_knowledge_base(job_id, vs)
        return {"job_id": job_id, "chunks_added": chunk_count}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/knowledge/topics")
async def list_expert_topics():
    """List all available expert knowledge base topics."""
    vs = get_vector_store()
    topics = vs.list_topics()
    return {"topics": topics}


@router.delete("/knowledge/topics/{topic}")
async def delete_topic_kb(topic: str):
    """Delete all chunks for a given topic from the knowledge base."""
    vs = get_vector_store()
    deleted = vs.delete_by_topic(topic)
    return {"topic": topic, "deleted_chunks": deleted}


@router.get("/research/download/{job_id}")
async def download_research_report(job_id: str):
    """Download a completed research job as a .zip archive."""
    service = get_research_service()
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job not completed yet")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. CSV of papers
        csv_buf = io.StringIO()
        writer = csv.writer(csv_buf)
        writer.writerow([
            "PMID", "DOI", "Title", "Authors", "Journal",
            "Impact Factor", "Year", "Abstract",
        ])
        for p in job.papers:
            authors_str = "; ".join(
                a.get("name", "") for a in p.get("authors_meta", p.get("authors", []))
            )
            writer.writerow([
                p.get("pmid", ""), p.get("doi", ""),
                p.get("title", ""), authors_str,
                p.get("journal", ""), p.get("journal_if", ""),
                p.get("year", ""), p.get("abstract", ""),
            ])
        zf.writestr("papers.csv", csv_buf.getvalue())

        # 2. Markdown summary report
        yr = job.year_range or {}
        md_lines = [
            f"# Literature Research Report: {job.topic}",
            "",
            f"**Query**: `{job.query}`",
            f"**Max Papers Requested**: {job.max_papers}",
            f"**Total Papers Found**: {job.total_papers}",
            f"**Year Range**: {yr.get('min', 'N/A')} - {yr.get('max', 'N/A')}",
            f"**Unique Institutions**: {job.unique_institutions}",
            f"**Created**: {job.created_at}",
            f"**Completed**: {job.completed_at}",
            "", "---", "", "## Paper List", "",
        ]
        for i, p in enumerate(job.papers, 1):
            md_lines.append(f"### {i}. {p.get('title', 'No title')}")
            md_lines.append("")
            display = p.get("author_display") or p.get("first_author", "Unknown")
            md_lines.append(f"- **Authors**: {display}")
            md_lines.append(
                f"- **Journal**: {p.get('journal', '')} "
                f"(IF: {p.get('journal_if', 'N/A')})"
            )
            md_lines.append(f"- **Year**: {p.get('year', '')}")
            if p.get("pmid"):
                md_lines.append(f"- **PMID**: {p['pmid']}")
            if p.get("doi"):
                md_lines.append(f"- **DOI**: {p['doi']}")
            abstract = p.get("abstract", "")
            if abstract and abstract != "No abstract":
                md_lines.append(f"- **Abstract**: {abstract}")
            md_lines.append("")
        zf.writestr("report.md", "\n".join(md_lines))

        # 3. Raw JSON data
        raw = {
            "job_id": job.job_id,
            "topic": job.topic,
            "query": job.query,
            "max_papers": job.max_papers,
            "total_papers": job.total_papers,
            "year_range": job.year_range,
            "unique_institutions": job.unique_institutions,
            "created_at": job.created_at,
            "completed_at": job.completed_at,
            "papers": job.papers,
        }
        zf.writestr("raw_data.json", json.dumps(raw, ensure_ascii=False, indent=2))

    buf.seek(0)
    filename = f"research_{job.topic}_{job.job_id[:8]}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class ConvertRequest(BaseModel):
    formats: list[str] = ["word", "html", "html_ppt", "pdf_ppt"]


@router.post("/research/convert/{job_id}")
async def convert_research_report(job_id: str, request: ConvertRequest = None):
    """Convert a completed research job's Markdown report to Word/HTML/PDF formats.

    POST /api/v1/research/convert/{job_id}
    Body (optional JSON): {"formats": ["word", "html", "html_ppt", "pdf_ppt"]}

    Returns a .zip with all generated files.
    """
    import sys
    from pathlib import Path

    service = get_research_service()
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job not completed yet")

    result_path = getattr(job, "result_path", "")
    if not result_path or not Path(result_path).exists():
        raise HTTPException(status_code=404, detail="Markdown report not found; re-run the job to regenerate")

    formats = (request.formats if request else None) or ["word", "html", "html_ppt", "pdf_ppt"]

    scripts_dir = Path(__file__).parent.parent.parent / "literature_research" / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    try:
        from md_to_reports import convert_markdown_to_reports
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"md_to_reports module not found: {e}")

    md_path = Path(result_path)
    output_dir = md_path.parent

    try:
        results = convert_markdown_to_reports(
            md_path=md_path,
            output_dir=output_dir,
            formats=formats,
        )
    except Exception as e:
        logger.error("Format conversion failed for job %s: %s", job_id, e)
        raise HTTPException(status_code=500, detail=f"Conversion failed: {e}")

    # Package all generated files into a zip
    buf = io.BytesIO()
    files_added = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fmt, path in results.items():
            if path and Path(path).exists():
                zf.write(path, Path(path).name)
                files_added += 1

    if files_added == 0:
        raise HTTPException(status_code=500, detail="No output files were generated")

    buf.seek(0)
    filename = f"report_{job.topic}_{job_id[:8]}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/research/completed")
async def get_completed_research():
    """Get list of completed research jobs for timeline analysis selection."""
    service = get_research_service()
    jobs = service.get_completed_research()
    return [
        {
            "job_id": j.job_id,
            "topic": j.topic,
            "paper_count": len(j.papers),
            "completed_at": j.completed_at,
        }
        for j in jobs
    ]


def _job_to_response(job: ResearchJob) -> ResearchJobResponse:
    return ResearchJobResponse(
        job_id=job.job_id,
        status=job.status,
        topic=job.topic,
        query=job.query,
        max_papers=job.max_papers,
        total_papers=job.total_papers,
        processed_papers=job.processed_papers,
        analyzed_papers=getattr(job, "analyzed_papers", 0),
        current_stage=job.current_stage,
        created_at=job.created_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
        result_path=getattr(job, "result_path", ""),
    )


# --- Paper endpoints ---

@router.post("/papers/upload")
async def upload_paper(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    os.makedirs(settings.upload_dir, exist_ok=True)

    paper_id = str(uuid.uuid4())
    filepath = os.path.join(settings.upload_dir, f"{paper_id}.pdf")

    content = await file.read()
    if len(content) > settings.max_upload_size:
        raise HTTPException(status_code=413, detail="File too large")

    with open(filepath, "wb") as f:
        f.write(content)

    with get_db() as conn:
        db.create_paper(conn, paper_id=paper_id, filename=file.filename, filepath=filepath)

    # Process synchronously (Celery optional)
    _process_pdf_sync(paper_id, filepath)

    return {"paper_id": paper_id, "filename": file.filename, "status": "processing"}


def _process_pdf_sync(paper_id: str, filepath: str):
    """Synchronous PDF processing."""
    from app.services.pdf_processor import PDFProcessor

    with get_db() as conn:
        try:
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
                status="processing",
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
                paper_metadata={"title": metadata.title, "authors": metadata.authors, "year": metadata.year},
            )

            db.update_paper(conn, paper_id, chunks_count=len(embedding_ids), status="completed")
            logger.info(f"Paper {paper_id} processed: {len(embedding_ids)} chunks")

        except Exception as e:
            logger.error(f"Error processing paper {paper_id}: {e}")
            db.update_paper(conn, paper_id, status="failed")


@router.get("/papers")
async def list_papers_endpoint():
    with get_db() as conn:
        return db.list_papers(conn)


@router.get("/papers/{paper_id}")
async def get_paper(paper_id: str):
    with get_db() as conn:
        paper = db.get_paper(conn, paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")
        return paper


# --- Knowledge endpoints ---

@router.post("/knowledge/query")
async def query_knowledge(request: QueryRequest):
    try:
        llm = get_llm_service()
        vs = get_vector_store()
        coordinator = AgentCoordinator(llm, vs)

        context = AgentContext(query=request.query, paper_id=request.paper_id)

        # Build topic-aware where filter
        where_filter = {}
        if request.paper_id:
            where_filter["paper_id"] = request.paper_id
        if request.topic:
            where_filter["topic"] = request.topic
        elif request.topics:
            where_filter["topics"] = request.topics

        response = await coordinator.route_and_process(context, where_filter=where_filter or None)
    except (_anthropic.AuthenticationError, _anthropic.PermissionDeniedError) as e:
        raise HTTPException(status_code=401, detail=f"LLM authentication failed: {e}. Check ANTHROPIC_API_KEY in .env")
    except _anthropic.APIStatusError as e:
        raise HTTPException(status_code=502, detail=f"LLM API error: {e}")
    except Exception as e:
        logger.error(f"Query error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "content": response.content,
        "agent_type": response.agent_type,
        "citations": [
            {
                "paper_id": c.paper_id,
                "title": c.title,
                "authors": c.authors,
                "year": c.year,
                "page_start": c.page_start,
                "page_end": c.page_end,
                "excerpt": c.excerpt,
            }
            for c in response.citations
        ],
    }


@router.post("/knowledge/chat")
async def chat(request: ChatRequest):
    with get_db() as conn:
        # Get or create session
        if request.session_id:
            session = db.get_session(conn, request.session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            session_id = session["id"]
        else:
            session = db.create_session(conn)
            session_id = session["id"]

        # Save user message
        db.add_message(conn, session_id=session_id, role="user", content=request.message)

        # Get chat history
        history = db.get_messages(conn, session_id, limit=10)
        chat_history = [{"role": m["role"], "content": m["content"]} for m in history]

    # Build topic filter
    topic_where: dict = {}
    if request.topic:
        topic_where["topic"] = request.topic
    elif request.topics:
        topic_where["topics"] = request.topics

    # Process through agent coordinator
    try:
        llm = get_llm_service()
        vs = get_vector_store()
        coordinator = AgentCoordinator(llm, vs)

        context = AgentContext(
            query=request.message,
            chat_history=chat_history,
            paper_id=request.paper_id,
        )
        response = await coordinator.route_and_process(context, where_filter=topic_where or None)
    except (_anthropic.AuthenticationError, _anthropic.PermissionDeniedError) as e:
        raise HTTPException(status_code=401, detail=f"LLM authentication failed. Check ANTHROPIC_API_KEY in .env")
    except _anthropic.APIStatusError as e:
        raise HTTPException(status_code=502, detail=f"LLM API error: {e}")
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # Save assistant message
    citations_json = json.dumps([
        {"paper_id": c.paper_id, "title": c.title, "page_start": c.page_start, "excerpt": c.excerpt}
        for c in response.citations
    ])
    with get_db() as conn:
        db.add_message(
            conn, session_id=session_id, role="assistant",
            content=response.content, citations=citations_json, agent_type=response.agent_type,
        )

    return {
        "session_id": session_id,
        "content": response.content,
        "agent_type": response.agent_type,
        "citations": [
            {
                "paper_id": c.paper_id,
                "title": c.title,
                "authors": c.authors,
                "year": c.year,
                "page_start": c.page_start,
                "page_end": c.page_end,
                "excerpt": c.excerpt,
            }
            for c in response.citations
        ],
    }


@router.get("/knowledge/timeline")
async def get_timeline():
    vs = get_vector_store()
    chunks = vs.query(
        "domain timeline breakthroughs key developments methods history",
        n_results=30,
    )
    if not chunks:
        return {"timeline": [], "summary": "No papers in the knowledge base yet."}
    try:
        llm = get_llm_service()
        answer = llm.generate_with_context(
            query="Generate a chronological timeline of key breakthroughs and developments in single-cell 3D genomics. "
                  "Include years, key methods, and their significance.",
            context_chunks=chunks,
            system="""You are a domain historian for single-cell 3D genomics.
Generate a structured timeline in JSON format with this schema:
{"events": [{"year": 2013, "title": "Event title", "description": "Brief description", "methods": ["method1"], "papers": ["paper_id"]}]}
Only output valid JSON, no markdown.""",
        )
    except (_anthropic.AuthenticationError, _anthropic.PermissionDeniedError):
        raise HTTPException(status_code=401, detail="LLM authentication failed. Check ANTHROPIC_API_KEY in .env")
    except _anthropic.APIStatusError as e:
        raise HTTPException(status_code=502, detail=f"LLM API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    try:
        timeline_data = json.loads(answer)
    except json.JSONDecodeError:
        timeline_data = {"events": [], "raw_summary": answer}
    return {"timeline": timeline_data.get("events", []), "summary": answer}


@router.post("/knowledge/compare")
async def compare_methods(request: CompareRequest):
    vs = get_vector_store()
    query = f"Compare these methods: {', '.join(request.methods)}"
    if request.aspects:
        query += f". Focus on: {', '.join(request.aspects)}"
    chunks = vs.query(query, n_results=20)
    try:
        llm = get_llm_service()
        answer = llm.generate_with_context(
            query=query,
            context_chunks=chunks,
            system="""You are a methods expert in single-cell 3D genomics.
Compare the specified methods with a structured analysis:
1. Overview of each method
2. Head-to-head comparison table (resolution, throughput, cost, complexity)
3. Recommended use cases for each
4. Key advantages and limitations
Cite sources using [Source N] notation.""",
        )
    except (_anthropic.AuthenticationError, _anthropic.PermissionDeniedError):
        raise HTTPException(status_code=401, detail="LLM authentication failed. Check ANTHROPIC_API_KEY in .env")
    except _anthropic.APIStatusError as e:
        raise HTTPException(status_code=502, detail=f"LLM API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"comparison": answer, "methods": request.methods}


# --- Writing endpoints ---

@router.post("/writing/draft-review")
async def draft_review(request: DraftReviewRequest):
    try:
        llm = get_llm_service()
        vs = get_vector_store()
        from agents.writing_assistant import WritingAssistantAgent
        agent = WritingAssistantAgent(llm, vs)
        context = AgentContext(
            query=f"Draft a {request.section_type} section about: {request.topic}",
            user_perspective=request.user_perspective,
        )
        # Build topic where filter
        where_filter: dict = {}
        if request.expert_topic:
            where_filter["topic"] = request.expert_topic
        elif request.expert_topics:
            where_filter["topics"] = request.expert_topics
        response = await agent.process(context, where_filter=where_filter or None)
    except (_anthropic.AuthenticationError, _anthropic.PermissionDeniedError):
        raise HTTPException(status_code=401, detail="LLM authentication failed. Check ANTHROPIC_API_KEY in .env")
    except _anthropic.APIStatusError as e:
        raise HTTPException(status_code=502, detail=f"LLM API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "draft": response.content,
        "citations": [
            {"paper_id": c.paper_id, "title": c.title, "year": c.year, "excerpt": c.excerpt}
            for c in response.citations
        ],
    }


@router.post("/writing/suggest-citations")
async def suggest_citations(request: CitationRequest):
    try:
        llm = get_llm_service()
        vs = get_vector_store()
        from agents.writing_assistant import WritingAssistantAgent
        agent = WritingAssistantAgent(llm, vs)
        response = await agent.suggest_citations(request.text, request.n_results)
    except (_anthropic.AuthenticationError, _anthropic.PermissionDeniedError):
        raise HTTPException(status_code=401, detail="LLM authentication failed. Check ANTHROPIC_API_KEY in .env")
    except _anthropic.APIStatusError as e:
        raise HTTPException(status_code=502, detail=f"LLM API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "suggestions": response.content,
        "citations": [
            {"paper_id": c.paper_id, "title": c.title, "year": c.year, "excerpt": c.excerpt}
            for c in response.citations
        ],
    }


@router.post("/review/evaluate")
async def evaluate_paper(request: EvaluateRequest):
    try:
        llm = get_llm_service()
        vs = get_vector_store()
        from agents.reviewer import ReviewerAgent
        agent = ReviewerAgent(llm, vs)
        focus = f" Focus on: {', '.join(request.focus_areas)}" if request.focus_areas else ""
        context = AgentContext(
            query=f"Evaluate this paper comprehensively.{focus}",
            paper_id=request.paper_id,
        )
        response = await agent.process(context)
    except (_anthropic.AuthenticationError, _anthropic.PermissionDeniedError):
        raise HTTPException(status_code=401, detail="LLM authentication failed. Check ANTHROPIC_API_KEY in .env")
    except _anthropic.APIStatusError as e:
        raise HTTPException(status_code=502, detail=f"LLM API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "evaluation": response.content,
        "rubric_categories": response.metadata.get("rubric_categories", []),
        "citations": [
            {"paper_id": c.paper_id, "title": c.title, "page_start": c.page_start, "excerpt": c.excerpt}
            for c in response.citations
        ],
    }


# --- Stats endpoint ---

@router.get("/stats")
async def get_stats():
    with get_db() as conn:
        total = db.count_papers(conn)
        completed = db.count_papers(conn, status="completed")

    try:
        vs = get_vector_store()
        vs_stats = vs.get_collection_stats()
    except Exception:
        vs_stats = {"total_chunks": 0}

    return {
        "papers": {"total": total, "completed": completed},
        "vector_store": vs_stats,
    }


# --- Hypergraph Timeline Analysis (NEW) ---

class HypergraphTimelineRequest(BaseModel):
    job_id: str
    analysis_depth: str = "full"  # summary, full, detailed
    include_collaboration: bool = True
    include_influence: bool = True
    include_milestones: bool = True


@router.post("/knowledge/hypergraph-timeline")
async def get_hypergraph_timeline(request: HypergraphTimelineRequest):
    """Get hypergraph-based timeline analysis from research results.

    This endpoint constructs a hypergraph where:
    - Nodes: authors, papers, time periods, institutions, concepts
    - Hyperedges: represent multi-dimensional relationships
    - Extracts: collaboration networks, community influence, milestones, debates
    """
    service = get_research_service()
    job = service.get_job(request.job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Research job not found")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Research job not completed yet")

    try:
        llm = get_llm_service()

        # Build hypergraph data structure
        hypergraph = _build_hypergraph_from_papers(job.papers)

        # Generate analysis using LLM
        analysis_prompt = _build_hypergraph_analysis_prompt(
            hypergraph,
            request.analysis_depth,
            request.include_collaboration,
            request.include_influence,
            request.include_milestones,
        )

        analysis_result = llm.chat(
            messages=[{"role": "user", "content": analysis_prompt}],
            system="""You are a research network analyst specializing in hypergraph analysis.
Analyze the provided hypergraph data and extract insights about:
1. Collaboration networks (who works with whom)
2. Community influence (key opinion leaders)
3. Research evolution over time (milestones, paradigm shifts)
4. Academic debates and consensus areas

Respond in JSON format with the following structure:
{
  "summary": "Brief overview of the research landscape",
  "key_figures": [{"name": "", "role": "", "influence_score": 0, "institution": ""}],
  "collaboration_clusters": [{"id": "", "members": [], "institution": "", "paper_count": 0}],
  "milestones": [{"year": 0, "event": "", "significance": "", "key_papers": []}],
  "debates": [{"topic": "", "sides": [], "status": "ongoing|resolved"}],
  "consensus_areas": ["topic1", "topic2"],
  "temporal_patterns": "Description of how research evolved over time"
}""",
            max_tokens=8000,
            temperature=0.3,
        )

        # Parse LLM response
        try:
            analysis_json = json.loads(analysis_result)
        except json.JSONDecodeError:
            analysis_json = {"raw_analysis": analysis_result}

        return {
            "job_id": request.job_id,
            "topic": job.topic,
            "hypergraph": hypergraph,
            "analysis": analysis_json,
            "statistics": {
                "total_papers": len(job.papers),
                "total_authors": len(hypergraph["nodes"]["authors"]),
                "total_institutions": len(hypergraph["nodes"]["institutions"]),
                "time_range": (lambda yrs: {
                    "start": min(yrs) if yrs else None,
                    "end": max(yrs) if yrs else None,
                })([p.get("year") for p in job.papers if p.get("year")]),
            },
        }

    except Exception as e:
        logger.error(f"Hypergraph timeline error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _build_hypergraph_from_papers(papers: list[dict]) -> dict:
    """Build hypergraph data structure from papers (dict format).

    Nodes: authors, papers, time periods, institutions, concepts
    Hyperedges: co-authorship, citation, temporal proximity, institutional affiliation
    """
    nodes = {
        "authors": {},
        "papers": {},
        "institutions": {},
        "time_periods": {},
        "concepts": {},
    }
    hyperedges = []

    # Build author and paper nodes
    for paper in papers:
        # Paper node
        paper_id = paper.get("pmid") or paper.get("doi") or paper.get("title", "")[:50]
        nodes["papers"][paper_id] = {
            "id": paper_id,
            "title": paper.get("title", ""),
            "year": paper.get("year", 0),
            "month": paper.get("month", 0),
            "journal": paper.get("journal", ""),
            "citation_count": paper.get("citation_count", 0),
        }

        # Time period node (by year)
        year = paper.get("year")
        if year:
            period_key = f"year_{year}"
            if period_key not in nodes["time_periods"]:
                nodes["time_periods"][period_key] = {
                    "id": period_key,
                    "year": year,
                    "papers": [],
                }
            nodes["time_periods"][period_key]["papers"].append(paper_id)

        # Author nodes and co-authorship hyperedges
        author_ids = []
        for author in paper.get("authors_meta", paper.get("authors", [])):
            author_id = author.get("name", "").lower().replace(" ", "_")
            if not author_id:
                continue

            if author_id not in nodes["authors"]:
                nodes["authors"][author_id] = {
                    "id": author_id,
                    "name": author.get("name", ""),
                    "affiliation": author.get("affiliation", ""),
                    "is_first_author_count": 0,
                    "is_corresponding_author_count": 0,
                    "papers": [],
                    "coauthors": set(),
                }

            nodes["authors"][author_id]["papers"].append(paper_id)
            if author.get("is_first_author"):
                nodes["authors"][author_id]["is_first_author_count"] += 1
            if author.get("is_corresponding_author"):
                nodes["authors"][author_id]["is_corresponding_author_count"] += 1

            author_ids.append(author_id)

            # Institution node
            affiliation = author.get("affiliation", "")
            if affiliation:
                inst_id = affiliation.lower().replace(" ", "_")[:50]
                if inst_id not in nodes["institutions"]:
                    nodes["institutions"][inst_id] = {
                        "id": inst_id,
                        "name": affiliation,
                        "authors": set(),
                        "papers": set(),
                    }
                nodes["institutions"][inst_id]["authors"].add(author_id)
                nodes["institutions"][inst_id]["papers"].add(paper_id)

        # Co-authorship hyperedge
        if len(author_ids) > 1:
            hyperedges.append({
                "type": "coauthorship",
                "nodes": author_ids,
                "paper": paper_id,
                "weight": len(author_ids),
            })

            # Update coauthor relationships
            for i, a1 in enumerate(author_ids):
                for a2 in author_ids[i+1:]:
                    nodes["authors"][a1]["coauthors"].add(a2)
                    nodes["authors"][a2]["coauthors"].add(a1)

        # Author-paper hyperedge (authorship)
        for author_id in author_ids:
            hyperedges.append({
                "type": "authorship",
                "nodes": [author_id, paper_id],
                "weight": 1,
            })

        # Temporal hyperedge (paper-time period)
        if year:
            hyperedges.append({
                "type": "temporal",
                "nodes": [paper_id, period_key],
                "weight": 1,
            })

    # Convert sets to lists for JSON serialization
    for author in nodes["authors"].values():
        author["coauthors"] = list(author["coauthors"])
    for inst in nodes["institutions"].values():
        inst["authors"] = list(inst["authors"])
        inst["papers"] = list(inst["papers"])

    return {
        "nodes": {k: list(v.values()) if isinstance(v, dict) else v for k, v in nodes.items()},
        "hyperedges": hyperedges,
    }


def _build_hypergraph_analysis_prompt(
    hypergraph: dict,
    depth: str,
    include_collaboration: bool,
    include_influence: bool,
    include_milestones: bool,
) -> str:
    """Build analysis prompt for LLM based on hypergraph data."""

    stats = {
        "total_authors": len(hypergraph["nodes"]["authors"]),
        "total_papers": len(hypergraph["nodes"]["papers"]),
        "total_institutions": len(hypergraph["nodes"]["institutions"]),
        "total_hyperedges": len(hypergraph["hyperedges"]),
    }

    # Get top collaborators
    authors_by_coauthor_count = sorted(
        hypergraph["nodes"]["authors"],
        key=lambda a: len(a.get("coauthors", [])),
        reverse=True,
    )[:10]

    # Get papers by year for timeline
    papers_by_year = {}
    for paper in hypergraph["nodes"]["papers"]:
        year = paper.get("year", 0)
        if year:
            papers_by_year[year] = papers_by_year.get(year, 0) + 1

    prompt = f"""Analyze this research hypergraph data:

## Statistics
- Total Authors: {stats['total_authors']}
- Total Papers: {stats['total_papers']}
- Total Institutions: {stats['total_institutions']}
- Total Relationships: {stats['total_hyperedges']}

## Top Collaborators (by number of coauthors)
"""
    for author in authors_by_coauthor_count:
        prompt += f"- {author['name']}: {len(author.get('coauthors', []))} coauthors, {len(author.get('papers', []))} papers"
        if author.get('is_first_author_count', 0) > 0:
            prompt += f", first author on {author['is_first_author_count']} papers"
        if author.get('is_corresponding_author_count', 0) > 0:
            prompt += f", corresponding author on {author['is_corresponding_author_count']} papers"
        prompt += "\n"

    prompt += f"\n## Papers by Year\n"
    for year in sorted(papers_by_year.keys()):
        prompt += f"- {year}: {papers_by_year[year]} papers\n"

    prompt += f"\n## Analysis Depth: {depth}\n"
    prompt += f"Include Collaboration Networks: {include_collaboration}\n"
    prompt += f"Include Influence Analysis: {include_influence}\n"
    prompt += f"Include Milestones: {include_milestones}\n"

    prompt += """
Please provide a comprehensive analysis of this research landscape, identifying:
1. Key opinion leaders and their influence
2. Research collaboration clusters/communities
3. Important milestones and breakthroughs over time
4. Areas of academic debate or competing approaches
5. Areas of strong consensus
6. Evolution patterns in the field

Return your analysis in the specified JSON format.
"""

    return prompt
