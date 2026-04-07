# Product Requirements Document
## Domain Expert — AI-Native Scientific Literature Intelligence Platform

**Version:** 1.3  
**Date:** 2026-04-05  
**Status:** Active Development  

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Target Users](#3-target-users)
4. [Product Vision & Goals](#4-product-vision--goals)
5. [System Architecture](#5-system-architecture)
6. [Feature Modules](#6-feature-modules)
   - 6.1 Literature Research
   - 6.2 Hypergraph & Collaboration Network
   - 6.3 Timeline & Technology Landscape
   - 6.4 Knowledge Base
   - 6.5 AI Chat & Expert Consultation
   - 6.6 Writing Assistant
   - 6.7 Paper Review
   - 6.8 Multi-Topic Expert Knowledge Base
7. [API Specification](#7-api-specification)
8. [Non-Functional Requirements](#8-non-functional-requirements)
9. [Data Model](#9-data-model)
10. [Testing Requirements](#10-testing-requirements)
11. [Deployment](#11-deployment)
12. [Out of Scope](#12-out-of-scope)
13. [Open Questions & Risks](#13-open-questions--risks)

---

## 1. Executive Summary

**Domain Expert** is an AI-native web application that transforms how researchers engage with scientific literature. Given a research domain and a PubMed query, the system autonomously retrieves, filters, analyzes, and synthesizes literature into structured knowledge — surfacing consensus positions, ongoing controversies, influential researchers, and emerging frontiers.

The platform supports the full lifecycle of researcher workflows: from initial literature discovery and influence mapping, through deep knowledge retrieval with source traceability, to AI-assisted manuscript review and writing. Critically, it supports **human-in-the-loop** collaboration so researchers can inject their own insights into AI-generated outputs.

The system is deployable on a cloud server and accessible through a browser-based interface supporting both document upload/download and conversational interaction.

---

## 2. Problem Statement

Researchers in specialized domains face a compounding information burden:

| Pain Point | Impact |
|---|---|
| Exponential literature growth | Impossible to manually track all relevant papers |
| Hidden collaboration networks | Influence structures and team relationships are invisible |
| Fragmented knowledge across PDFs | Relevant details are buried; context is lost during retrieval |
| No structured view of technology evolution | Hard to identify leading methods, their trade-offs, or historical trajectory |
| Review and writing are isolated from the literature | No direct link from accumulated knowledge to manuscript drafting |
| Cross-disciplinary signal is missed | Breakthroughs in adjacent fields that predict domain shifts go unnoticed |

Existing tools (Zotero, Semantic Scholar, Elicit) address parts of this problem in isolation. None provide an integrated, domain-specific intelligence layer that combines structured network analysis, hierarchical knowledge retrieval, AI synthesis, and writing support.

---

## 3. Target Users

### Primary User
**Academic Researcher / PhD Student** in a specialized scientific domain (e.g., genomics, prenatal diagnostics, oncology). Reads 10–50 papers per week. Needs to track field evolution, identify key authors, write reviews, and stay current across sub-fields.

### Secondary User
**Principal Investigator / Lab Director** who needs high-level synthesis of a field for grant proposals, strategic decisions, or mentoring. Values summary quality and source credibility over raw paper count.

### Tertiary User
**Science Writer / Systematic Reviewer** who needs structured, citable synthesis with full provenance and the ability to export professional reports.

---

## 4. Product Vision & Goals

### Vision
A researcher should be able to define a domain in plain language, and within minutes have access to: a structured map of the field's key people, papers, debates, and frontiers — all searchable, traceable, and ready to inform writing.

### Goals

| # | Goal | Metric |
|---|---|---|
| G1 | Retrieve complete PubMed result sets without count loss | Retrieved count = PubMed reported count |
| G2 | Enable hierarchical knowledge retrieval with source traceability | Every AI response cites paper + page number |
| G3 | Surface collaboration networks and influence scores | Hypergraph renders within 5s for ≤500 papers |
| G4 | Support multi-domain expert knowledge bases, selectable at query time | Topic filter applied correctly across all chat/review/writing endpoints |
| G5 | Generate professional bilingual reports (Markdown, Word, HTML, PPT) | All report formats produced without error for any valid job |
| G6 | Human-in-the-loop writing and review | User edits round-trip into AI synthesis seamlessly |
| G7 | Full open-access PDF acquisition pipeline | ≥60% OA PDF retrieval rate for typical biomedical queries |

---

## 5. System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Browser (React + Vite)                │
│   Ant Design UI · TanStack Query · Cytoscape.js · D3    │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP / WebSocket
┌────────────────────────▼────────────────────────────────┐
│                FastAPI Application Server               │
│         Multi-Agent Coordinator · REST API v1           │
├──────────┬──────────────┬──────────────┬────────────────┤
│PostgreSQL│   SQLite /   │    Redis     │  Celery Worker │
│(metadata)│  ChromaDB    │ (cache/queue)│ (async PDF     │
│          │  (vectors)   │              │  processing)   │
└──────────┴──────────────┴──────────────┴────────────────┘
                         │
        ┌────────────────┼─────────────────┐
        ▼                ▼                 ▼
   PubMed eUtils    Unpaywall API    Anthropic / OpenAI
   Europe PMC       PMC / bioRxiv    LLM API
   Semantic Scholar Publisher OA
```

### Multi-Agent Architecture

All intelligent operations are handled by specialized agents coordinated through `AgentCoordinator`, which classifies each query and routes it to the appropriate agent:

| Agent | Responsibility |
|---|---|
| `KnowledgeRetrievalAgent` | Hierarchical RAG with citation tracking |
| `DocumentAnalysisAgent` | Deep paper understanding and annotation |
| `TimelineSynthesisAgent` | Domain evolution, method comparison |
| `WritingAssistantAgent` | Review drafting, citation suggestion |
| `ReviewerAgent` | Manuscript evaluation with scoring rubric |

All agents share `AgentContext` for state and accept an optional `where_filter` for topic-scoped retrieval.

### PDF Processing Pipeline

```
PDF Upload
    │
    ▼
PDFProcessor (PyMuPDF + pytesseract OCR)
    │
    ▼
Hierarchical Chunking
  Level 1: Document  (title, abstract, metadata)
  Level 2: Section   (Introduction, Methods, Results…)
  Level 3: Subsection
  Level 4: Atomic    (paragraph / figure / table)
    │
    ▼
Embeddings (sentence-transformers)
    │
    ▼
ChromaDB / SQLite vector store
  — stored with: paper_id, page_start, page_end, topic, section_type
```

---

## 6. Feature Modules

---

### 6.1 Literature Research

**Purpose:** Automated PubMed retrieval, quality filtering, LLM analysis, and multi-format report generation.

#### 6.1.1 PubMed Search

- Accept a raw PubMed/NCBI query string (any valid eSearch syntax) and a topic label
- Detect and preserve existing date filters (`[Date - Entry]`, `[EDat]`, `[Date]`) — do not add redundant wrappers
- Detect and preserve existing publication-type filters (`[Publication Type]`, `[pt]`) — do not add redundant wrappers
- When appending automatic filters, use `_safe_wrap_query()` to preserve top-level `NOT` operator semantics
- Request up to `max_papers` results from PubMed via `esearch` (`retmax = max_papers`)
- Do **not** apply local publication-type or keyword filters inside the XML parser; trust PubMed's query results entirely
- Log: PubMed reported count, IDs retrieved, per-batch fetch count, per-batch parse count, final paper count

#### 6.1.2 Quality Pre-filtering (Optional, User-Configurable)

The following filters are **opt-in only**, not applied by default:

- Minimum citation count threshold
- Minimum journal impact factor threshold
- Exclude retracted papers

#### 6.1.3 LLM Paper Analysis

For each paper, perform (via LLM API):

| Dimension | Description |
|---|---|
| Title translation | English → Chinese |
| Abstract translation | English → Chinese |
| Technical route | Core methodology / experimental approach |
| Advantages | Key strengths claimed or demonstrated |
| Limitations | Acknowledged or apparent weaknesses |
| Technical barriers | Unsolved challenges |
| Feasibility | Clinical / translational readiness |
| Generalizability | Applicability beyond the specific study context |

#### 6.1.4 Open-Access PDF Acquisition

For each paper with a DOI or PMID, attempt download via the following priority chain:

| Priority | Source | Method |
|---|---|---|
| 1 | Unpaywall API | Gold/green OA lookup by DOI |
| 2 | PubMed Central | PMID → PMCID → PMC PDF URL |
| 3 | Europe PMC | PMC PDF render endpoint |
| 4 | Semantic Scholar | Open Access PDF field |
| 5 | Publisher direct | DOI-prefix pattern matching (bioRxiv, Frontiers, PLOS, PeerJ, eLife, BMC, Nature OA, Springer OA) |

- Validate downloaded files: minimum 5,000 bytes, `%PDF` magic bytes
- Skip already-downloaded files (cache by output path)
- Write `pdf_path`, `pdf_status`, `pdf_source` fields back to paper record
- Rate-limit: configurable inter-request delay (default 1.5s)

#### 6.1.4b Semantic Scholar Enrichment

After PubMed fetch completes and before LLM analysis, each paper is enriched with data from the Semantic Scholar Academic Graph API. This runs as a new `enriching` stage in the job lifecycle.

**Data fetched per paper:**

| Field | Type | Description |
|---|---|---|
| `citation_count` | int | Total citation count on Semantic Scholar |
| `influential_citation_count` | int | Count of papers that highly-cited this paper (S2 metric) |
| `s2_paper_id` | str | Semantic Scholar internal paper ID |
| `s2_url` | str | `https://www.semanticscholar.org/paper/{id}` |
| `s2_authors` | list | Full author list from S2, including `authorId` for disambiguation |
| `references` | list | Papers this paper cites (out-links): title, year, DOI, PMID, URL, citation_count, journal, authors |
| `citations_in` | list | Papers that cite this paper (in-links): same structure as references |

**Two-phase strategy:**

- **Phase 1 (batch):** All papers queried in a single `POST /graph/v1/paper/batch` request (up to 500 per call), returning basic metrics (`citation_count`, `influential_citation_count`, `s2_authors`, etc.). Efficient for any corpus size.
- **Phase 2 (per-paper):** For each paper with a matched S2 ID, fetches `/paper/{id}/references` and `/paper/{id}/citations` (up to 50 each). Only runs when corpus size ≤ `SEMANTIC_SCHOLAR_NETWORK_LIMIT` (default 100) to avoid excessive latency.

**Rate limiting:** 1.1 req/s without API key; ~0.15 req/s (10/s) with `SEMANTIC_SCHOLAR_API_KEY`.

**Graceful degradation:** Enrichment failures are non-fatal — the job continues to LLM analysis with whatever fields were successfully populated. Papers that cannot be matched on S2 retain default values (`citation_count=0`, `references=[]`, etc.).

#### 6.1.5 Report Generation

Upon job completion, automatically generate all four report formats:

| Format | File | Description |
|---|---|---|
| Markdown | `{topic}_文献调研报告_{date}.md` | Structured text: per-paper analysis, consensus/controversies, timeline, references |
| Word (.docx) | `{topic}_report_{date}.docx` | A4, bilingual (EN/CN) side-by-side abstract table, 6-dimension analysis tables per paper |
| HTML Reading | `{topic}_report_{date}.html` | Responsive, blue-white gradient, stats bar, paper cards with 6-dim grid |
| HTML PPT | `{topic}_ppt_{date}.html` | 16:9 slides (1280×720px), dark blue-purple theme, self-contained single file |
| PDF PPT | `{topic}_ppt_{date}.pdf` | Screenshot-based PDF derived from HTML PPT; pixel-perfect 1:1 size and resolution match |

**HTML PPT slide structure:** cover slide (1) + per-paper slides ×2 (overview + analysis) + closing slide (1). Total = `1 + N×2 + 1` slides. No overview/summary slide is generated.

**HTML PPT layout:** Slides use `min-height: 720px` with `flex: 1 0 auto` on the body element — short slides render at exactly 720px while slides with long bilingual abstracts grow beyond 720px to display the full content. No CSS truncation is applied (`overflow: hidden`, `height: 100%`, and `-webkit-line-clamp` are all absent from the slide layout).

**PDF PPT generation (per-slide scroll strategy):** Each slide is individually scrolled into the Chromium viewport before screenshotting, then assembled into a PDF using Pillow. This avoids the Chromium GPU rasterizer's ~16384 CSS px height limit that causes blank pages for large PPTs (e.g. ≥16 papers at 720px each). For slides taller than 720px (long abstracts), the viewport is dynamically resized to fit the slide before the screenshot is taken. Final PDF is assembled at `device_scale_factor=2` / `resolution=192 DPI`; pages are 960×540pt (≡ 1280×720 CSS px at 72pt/in).

**Three-layer quality assurance:** Each report generation pass runs three automated checks:

| Layer | Location | What it checks |
|---|---|---|
| A — Data | `generate_html_ppt.py`, before HTML generation | Each paper has non-empty `abstract`, `abstract_cn`, and all 6 analysis dimensions; warnings logged per missing field |
| B — Render | `md_to_reports.py`, after HTML generation | Playwright loads the HTML PPT; checks every `.ab-text` and `.dim-ppt-body` element for non-empty visible text; warnings logged per empty element |
| C — PDF | `md_to_reports.py`, after PDF generation | PyMuPDF renders each page at 25% scale (grayscale) and computes pixel std_dev; pages with std_dev < 8 (near-uniform color = blank/failed render) are flagged as warnings |

All three layers are non-blocking: warnings are logged but do not abort the pipeline. The PDF is still produced even if Layer B or C raises issues.

All output files saved to: `literature_research/result/{topic}调研_{start_date}至{today}/`

The completed job's `result_path` field returns the Markdown file path in the API response.

#### 6.1.6 Job Lifecycle

```
pending → running → completed
                 ↘ failed
```

- Jobs persisted as JSON at `data/research/{job_id}.json`
- Running jobs cannot be deleted
- Delete operation removes the job JSON **and the entire result folder** (`literature_research/result/{topic}调研_…/`) atomically; Windows file-lock retry logic handles PDF files held open by Playwright
- **Bidirectional sync with filesystem:**
  - API delete → result folder deleted from disk immediately
  - Manual result folder deletion → job disappears from the job list on next poll (stale job detection in `list_jobs()`)
- Progress fields:
  - `current_stage`: `searching` | `enriching` | `analyzing` | `converting` | `completed`
  - `processed_papers`: papers retrieved from PubMed (set to `total_papers` once search completes)
  - `analyzed_papers`: papers that have completed LLM deep analysis (incremented per-paper during `analyzing` stage)
  - `total_papers`: final paper count from PubMed

**Analysis loop:** runs in `asyncio.to_thread` so the event loop remains responsive to polling requests during the LLM analysis phase. `analyzed_papers` is saved to disk after every individual paper, so polling reflects real-time per-paper progress.

#### 6.1.7 Frontend: Literature Research Panel

- Form: topic label, PubMed query textarea, max papers selector
- Job list table: status badge, paper count, creation time, action buttons (download ZIP, import to KB, delete)
- Download ZIP contains: `papers.csv` (with `authors_meta` field), `raw_data.json`, per-paper Markdown summaries
- Poll job status every 3 seconds while `running`
- Show `result_path` as a local file path when job is completed
- **Progress display (running jobs):**
  - During `searching` stage: progress bar shows `processed_papers / total_papers`
  - During `analyzing` stage: progress bar switches to `analyzed_papers / total_papers` with label "深度分析 X/N 篇"
  - Both the job list table and the Active Job card use the same stage-aware logic

---

### 6.2 Hypergraph & Collaboration Network

**Purpose:** Visualize the social and intellectual structure of a research domain as a hypergraph where nodes represent authors, papers, and institutions, and hyperedges represent co-authorship relationships.

#### Node Types

| Node | Size Encoding | Color |
|---|---|---|
| Author | Influence score | Blue gradient |
| Paper | Citation count | Orange gradient |
| Time period | Fixed | Grey |

#### Author Influence Score

```
influence = (paper_count × journal_IF)
          + (coauthor_count × 0.5)
          + (first_author_count × 2)
          + (corresponding_author_count × 2)
          + (total_citations × 0.1)    // sum of citation_count across all author's papers (from S2)
```

Node size is normalized relative to the maximum influence score in the current dataset. `total_citations` is populated from Semantic Scholar data when available; falls back to 0 if enrichment was skipped.

#### Citation Network Edges

When Semantic Scholar enrichment has been run, `_build_hypergraph_from_papers()` adds directed citation edges for within-corpus references:

```
citation_edges: [
  { "type": "citation", "source": paper_id, "target": cited_paper_id, "weight": 1 },
  ...
]
```

Only edges where **both** source and target exist within the corpus are included. Cross-corpus citations are recorded in `paper.references` / `paper.citations_in` but not as hypergraph edges.

`citation_stats` summary:
```
{
  "total_citations":       int,    // sum of all citation_count values
  "papers_with_citations": int,    // how many papers have citation_count > 0
  "max_citations":         int,    // highest single-paper citation count
  "in_corpus_links":       int,    // directed citation edges within the corpus
  "most_cited":            list    // top-10 papers by citation_count
}
```

#### Extracted Insights

- Collaboration clusters (connected components with ≥3 authors)
- Most influential authors (ranked by influence score)
- Cross-institution collaborations
- Temporal evolution: who entered/exited the field in each period
- Conflict indicators: authors who published competing technical approaches

#### Visualization Requirements

- Rendered with Cytoscape.js in the frontend
- Interactive: click node → show papers, co-authors, affiliations
- Filter by time period, minimum influence score, institution
- Export as PNG or SVG

---

### 6.3 Timeline & Technology Landscape

**Purpose:** Extract the chronological development of a research domain from literature metadata and LLM synthesis.

#### Timeline Construction

From the hypergraph paper nodes and their citation/date metadata, identify:

- Major breakthrough papers (high citations + early date)
- Technology generations and their date ranges
- Transitions: when one dominant approach was superseded by another

#### Technology Comparison

For any two or more methods/approaches mentioned across papers:

| Dimension | Content |
|---|---|
| Performance | Reported metrics and effect sizes |
| Applicability | Sample types, conditions, scale |
| Cost & complexity | Wet-lab / computational requirements |
| Adoption curve | Publication count over time |
| Open problems | Unresolved challenges for each approach |

#### Controversy Extraction

Identify papers that explicitly contradict or dispute findings from other papers in the corpus. Surface as labeled edges in the hypergraph and as a structured "Controversies" section in reports.

#### Frontend: Timeline Panel

- Horizontal scrollable timeline (D3.js)
- Milestone cards: paper title, year, brief impact statement
- Technology track lanes (one lane per major approach)
- Click milestone → open paper detail panel

---

### 6.4 Knowledge Base

**Purpose:** A hierarchically chunked, topic-tagged vector store enabling precise, traceable retrieval across the full text of ingested literature.

#### Ingestion Sources

1. **PDF Upload** — user uploads paper PDF; processed by OCR + hierarchical chunker
2. **Literature Research Import** — completed research job papers imported via `POST /research/import/{job_id}`; each chunk tagged with `topic = job.topic`

#### Chunk Schema

```
{
  chunk_id:     string,
  paper_id:     string,
  content:      string,
  level:        "document" | "section" | "subsection" | "atomic",
  section_type: "title" | "abstract" | "introduction" | "methods" |
                "results" | "discussion" | "conclusion" | "metadata",
  page_start:   int,
  page_end:     int,
  topic:        string,     // domain label, e.g. "NIPD", "CRISPR"
  embedding:    float[]
}
```

#### Query & Retrieval

- Semantic search via cosine similarity on embeddings
- BM25 lexical re-ranking (hybrid retrieval)
- Topic filter: `{"topic": "X"}` or `{"topics": ["X", "Y"]}` (OR logic)
- Every result includes `paper_id`, `page_start`, `page_end`, `section_type` for source traceability
- Citations rendered as inline superscripts in the frontend; click → open PDF at the cited page

#### Topic Management API

```
GET    /api/v1/knowledge/topics              List all topics with paper_count, chunk_count
DELETE /api/v1/knowledge/topics/{topic}      Delete all chunks for a topic
```

---

### 6.5 AI Chat & Expert Consultation

**Purpose:** Conversational interface to the knowledge base, with optional topic scoping and full source attribution.

#### Behavior

- Each turn performs a knowledge base retrieval (RAG) before generating a response
- Response includes inline citations (`[1]`, `[2]`…) with hover/click source panel
- Sources show: paper title, authors, year, journal, page range, excerpt
- Multi-turn context maintained within a session (last N turns passed to LLM)
- If no relevant knowledge found, the LLM responds from general knowledge and indicates this clearly

#### Topic Selection

- User can select one or more expert knowledge base topics before starting a chat
- No selection = query across all topics
- Multi-topic selection uses OR logic in the vector store `where_filter`

#### Frontend: Chat Interface

- Topic selector (multi-select chips) above the chat input
- Source panel slides in from the right when a citation is clicked
- Message export (copy markdown, download as PDF)

---

### 6.6 Writing Assistant

**Purpose:** AI-assisted manuscript drafting and citation insertion, grounded in the domain knowledge base and augmented by researcher-provided content (human-in-the-loop).

#### Draft Review Section

Given a section type (Introduction / Discussion / Conclusion) and optional user notes:

1. Retrieve the most relevant knowledge base chunks
2. Draft the section with inline citations
3. Present draft to user for editing
4. User edits are fed back into the next LLM pass
5. Repeat until user approves

The user's perspective and unpublished observations can be injected as "Author Notes" that the LLM incorporates without treating them as citable sources.

#### Citation Suggestion

Given a passage of user-written text:
- Identify claims that should be supported by citations
- Retrieve supporting papers from the knowledge base
- Return ranked citation suggestions with confidence scores and source excerpts

#### Topic Selection

Both `draft-review` and `suggest-citations` accept `expert_topic` (single) or `expert_topics` (list) to scope retrieval.

---

### 6.7 Paper Review

**Purpose:** Structured evaluation of a submitted manuscript with quantitative scoring and actionable revision suggestions.

#### Scoring Rubric

| Dimension | Weight | Description |
|---|---|---|
| Novelty | 20% | Originality of contribution relative to known literature |
| Methodology | 25% | Rigor, reproducibility, statistical validity |
| Clarity | 15% | Writing quality, figure/table quality, logical flow |
| Impact | 20% | Significance of claims; potential for citation / adoption |
| Completeness | 20% | Coverage of related work, limitations section, data availability |

Each dimension scored 1–10; weighted average = overall score.

#### Review Output

- Per-dimension scores with justification
- Specific revision suggestions, each linked to the section/page that needs revision
- Summary verdict: Accept / Minor Revision / Major Revision / Reject
- Optional: similar papers from the knowledge base that reviewers should consider

#### Topic Selection

`evaluate` endpoint accepts `expert_topic` / `expert_topics` to ground the review in a specific domain knowledge base.

---

### 6.8 Multi-Topic Expert Knowledge Base

**Purpose:** Allow users to build and query separate expert knowledge bases per research domain, enabling cross-domain or focused single-domain consultation.

#### Design

- Every chunk stored in the vector store carries a `topic` string tag
- Topics are created implicitly when a literature research job is imported
- Topics can be deleted independently without affecting other topics

#### Querying

All intelligent endpoints (chat, writing, review) accept:

```json
{
  "topic":  "NIPD",              // single topic filter
  "topics": ["NIPD", "CRISPR"]  // multi-topic OR filter
}
```

No topic specified → no filter (search all topics).

#### Discovery

`GET /api/v1/knowledge/topics` returns:
```json
[
  { "topic": "NIPD",   "paper_count": 264, "chunk_count": 1842 },
  { "topic": "CRISPR", "paper_count": 180, "chunk_count": 1290 }
]
```

---

## 7. API Specification

Base path: `/api/v1`

### Literature Research

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/research/run` | Create and start a research job |
| `GET` | `/research/jobs` | List all jobs |
| `GET` | `/research/jobs/{job_id}` | Get job status and result_path |
| `DELETE` | `/research/jobs/{job_id}` | Delete job JSON and result Markdown |
| `GET` | `/research/download/{job_id}` | Download ZIP (CSV + JSON + Markdown) |
| `POST` | `/research/import/{job_id}` | Import papers to knowledge base |
| `GET` | `/research/completed` | List completed jobs for module consumption |

### Knowledge Base

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/papers/upload` | Upload and process a PDF |
| `GET` | `/papers` | List all ingested papers |
| `GET` | `/papers/{paper_id}` | Get paper metadata |
| `POST` | `/knowledge/query` | Semantic search with optional topic filter |
| `GET` | `/knowledge/topics` | List all topic partitions |
| `DELETE` | `/knowledge/topics/{topic}` | Delete all chunks for a topic |

### Intelligence

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/knowledge/chat` | Multi-turn RAG chat |
| `GET` | `/knowledge/timeline` | Domain timeline synthesis |
| `POST` | `/knowledge/compare` | Compare methods/approaches |
| `POST` | `/knowledge/hypergraph-timeline` | Hypergraph + timeline from research job |
| `POST` | `/writing/draft-review` | Draft a manuscript section |
| `POST` | `/writing/suggest-citations` | Suggest citations for user text |
| `POST` | `/review/evaluate` | Evaluate a paper manuscript |
| `GET` | `/stats` | System statistics |

### Key Request Fields (topic filtering)

```
POST /knowledge/query        → topic, topics
POST /knowledge/chat         → topic, topics
POST /writing/draft-review   → expert_topic, expert_topics
POST /writing/suggest-citations → expert_topic, expert_topics
POST /review/evaluate        → expert_topic, expert_topics
```

---

## 8. Non-Functional Requirements

### Performance

| Requirement | Target |
|---|---|
| PubMed search + ID retrieval | < 10s for 300 papers |
| PDF analysis per paper (LLM) | < 60s |
| Knowledge base query (RAG) | < 3s p95 |
| Hypergraph render (≤500 nodes) | < 5s |
| Chat response (first token) | < 2s |

### Reliability

- All external HTTP calls (PubMed, PDF download, LLM) have explicit timeouts and retry logic
- Batch fetch failures log the exact count of lost papers; job does not silently under-count
- Vector store migration runs idempotently on startup (safe to restart at any time)
- Running jobs cannot be deleted to prevent data corruption

### Security

- LLM API keys stored in environment variables only; never logged or returned in API responses
- File uploads restricted to PDF MIME type and max 50MB
- All user input sanitized before inclusion in LLM prompts (prompt injection prevention)
- CORS configured for the specific frontend origin only in production

### Observability

- Structured logging with level INFO for normal operation, WARNING for soft failures (e.g., PDF not available), ERROR for hard failures
- Per-batch paper count logged at fetch and parse stages
- LLM token usage logged per request

### Internationalization

- All LLM-generated content (titles, abstracts, analysis) available in both English and Chinese
- Report filenames and directory names support Unicode (UTF-8)

---

## 9. Data Model

### ResearchJob

```
job_id:              UUID
status:              "pending" | "running" | "completed" | "failed"
topic:               string          // domain label (e.g. "NIPD")
query:               string          // raw PubMed query string
max_papers:          int             // retmax cap
total_papers:        int             // final parsed paper count
processed_papers:    int             // papers retrieved (= total_papers after search stage)
analyzed_papers:     int             // papers completed LLM analysis (increments per-paper)
current_stage:       string          // searching | analyzing | converting | completed
papers:              Paper[]
error_message:       string
result_path:         string          // absolute path to Markdown report
year_range:          {min, max}
unique_institutions: int
created_at:          ISO8601
started_at:          ISO8601
completed_at:        ISO8601
```

### Paper

```
pmid:                   string
doi:                    string
title:                  string
title_cn:               string
abstract:               string
abstract_cn:            string
journal:                string
journal_if:             string
publication_date:       string
year:                   int
month:                  int
authors_meta:           Author[]
author_display:         string
first_author:           string
corresponding_authors:  string[]
affiliations:           string[]
research_team:          string
technical_route:        string
advantages:             string
limitations:            string
technical_barriers:     string
feasibility:            string
generalization:         string
pdf_path:               string | null
pdf_status:             "success" | "not_available" | "failed" | "cached"
pdf_source:             string

// Semantic Scholar enrichment (populated during "enriching" stage)
citation_count:               int       // S2 total citations
influential_citation_count:   int       // S2 influential citations
s2_paper_id:                  string    // Semantic Scholar internal ID
s2_url:                       string    // https://www.semanticscholar.org/paper/{id}
s2_authors:                   S2Author[]
references:                   CitationStub[]   // papers this paper cites
citations_in:                 CitationStub[]   // papers that cite this paper
```

### S2Author

```
name:      string
authorId:  string    // Semantic Scholar author ID (for disambiguation)
```

### CitationStub

```
title:          string
year:           int
doi:            string | null
pmid:           string | null
s2_paper_id:    string | null
url:            string | null    // Semantic Scholar URL
citation_count: int
journal:        string
authors:        string[]         // first 3 author names
```

### Author

```
name:                      string
affiliation:               string
email:                     string
is_first_author:           bool
is_corresponding_author:   bool
```

### VectorChunk

```
chunk_id:     string
paper_id:     string
content:      string
level:        "document" | "section" | "subsection" | "atomic"
section_type: string
page_start:   int
page_end:     int
topic:        string
```

---

## 10. Testing Requirements

### Backend Unit / Integration Tests (`backend/tests/test_modules.py`)

Target: **34 tests, all pass**, runtime < 5s.

| Test Class | Scope |
|---|---|
| `TestPDFDownload` | 5-tier download chain; HTTP calls mocked |
| `TestVectorStoreTopics` | Topic tagging, topic filter, delete by topic |
| `TestFetchPapers` | Query detection helpers, batch parsing, zero drop for valid queries |
| `TestLiteratureResearchService` | Job lifecycle: create → run → complete → delete |
| `TestReportGeneration` | Markdown, HTML, HTML-PPT output not empty and contains expected sections |
| `TestHypergraphBuilder` | Node creation, influence score calculation, edge construction |

All external HTTP calls (PubMed, Unpaywall, PMC, LLM) must be mocked. No test should require network access.

### End-to-End Validation

- Run `fetch_papers()` against live PubMed with a reference query; assert returned count equals PubMed's reported `count` field from esearch
- For the reference query `("non-invasive prenatal diagnosis"[Title/Abstract] OR …) NOT (…)` with `max_papers=300`: assert result = 264

---

## 11. Deployment

### Local Development

```bash
# Backend (with auto-reload)
cd backend
python -m uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm run dev   # Vite dev server on :5173
```

### Docker (Recommended)

```bash
docker-compose up -d --build
```

Services: `backend` (:8000), `frontend` (:5173 or :80), `chromadb` (:8001), `postgres`, `redis`, `celery`

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | One of these two | Claude LLM API |
| `OPENAI_API_KEY` | One of these two | OpenAI LLM API |
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `REDIS_URL` | Yes | Redis connection string |
| `SECRET_KEY` | Yes | JWT signing secret |
| `VECTOR_DB_PATH` | Yes | ChromaDB persistence directory |
| `UPLOAD_DIR` | Yes | PDF upload storage directory |
| `UNPAYWALL_EMAIL` | Recommended | Required for Unpaywall API |
| `HTTP_PROXY` / `HTTPS_PROXY` | Optional | Network proxy for restricted environments |

### File Storage Layout

```
backend/
  data/
    research/
      {job_id}.json          ← Job state + all paper metadata
  literature_research/
    result/
      {topic}调研_{start_date}至{today}/   ← entire folder deleted on job delete
          {topic}_原始NCBI_{date}.md
          {topic}_文献调研报告_{date}.md
          {topic}_report_{date}.docx
          {topic}_report_{date}.html
          {topic}_ppt_{date}.html
          {topic}_ppt_{date}.pdf
    pdfs/
      {doi_or_pmid}.pdf      ← Downloaded OA PDFs
```

---

## 12. Out of Scope

The following are explicitly excluded from this version:

- **Sci-Hub or any paywall-bypass mechanism** — only open-access and OA-licensed content
- **Real-time collaborative editing** — single-user session only
- **Citation graph construction from reference lists** — citation counts sourced from metadata only, not parsed from PDF reference sections
- **Automated submission to journals or preprint servers**
- **Support for non-English primary literature** (Chinese, German, etc.) beyond translation of abstracts
- **Mobile application** — web responsive design only

---

## 13. Open Questions & Risks

| # | Issue | Risk Level | Notes |
|---|---|---|---|
| R1 | PubMed eUtils rate limits (3 req/s unauthenticated, 10/s with API key) | Medium | Large jobs (>300 papers) may be throttled; add API key support and rate limiter |
| R2 | OA PDF availability varies by field and publisher | Medium | Target ≥60% retrieval rate; some domains (clinical, paywalled) may be lower |
| R3 | LLM API cost at scale | Medium | 264 papers × 6 analysis dimensions = significant token spend; batch and cache aggressively |
| R4 | OCR quality for scanned PDFs | Low-Medium | pytesseract accuracy degrades for low-DPI scans; consider cloud OCR fallback |
| R5 | Vector store scaling beyond 10k chunks | Low | SQLite-backed ChromaDB acceptable to ~100k chunks; migrate to hosted ChromaDB or Weaviate above that |
| R6 | Job output persistence on server restart | Low | Jobs are written to disk as JSON; uvicorn restart is safe; only in-flight `running` jobs may need recovery logic |
| R7 | ~~`delete_job()` does not remove the Markdown result file~~ | ~~Low~~ | **RESOLVED (2026-04-05):** `delete_job()` now removes the entire result folder via `shutil.rmtree` with Windows file-lock retry. Stale job detection in `list_jobs()` handles the reverse direction (manual folder deletion). |
| R8 | ~~PDF PPT blank pages for large reports; HTML PPT abstract truncation~~ | ~~Medium~~ | **RESOLVED (2026-04-05):** (1) HTML truncation — removed all CSS clamp/overflow constraints from slide layout; slides now grow beyond 720px for long abstracts. (2) PDF blank pages — replaced full-page screenshot approach with per-slide scroll strategy; each slide is scrolled into the Chromium viewport before capture, bypassing the GPU rasterizer height limit (~16384px). Three-layer review (A/B/C) added to catch regressions automatically. |
