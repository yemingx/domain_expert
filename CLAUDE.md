# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Domain Expert Multi-Agent System is a sophisticated AI-powered system for single-cell 3D genomics research. It provides hierarchical knowledge retrieval, domain timeline tracking, and intelligent document analysis through a multi-agent architecture.

## Architecture

### High-Level Architecture

```
Frontend (React + Vite + Ant Design)
  ↓ HTTP/WebSocket
Backend (FastAPI + Python)
  ↓
├─ PostgreSQL (Metadata)
├─ ChromaDB (Vectors)
├─ Redis (Cache/Celery)
└─ Celery Workers (Async processing)
```

### Multi-Agent System

The backend uses a coordinator-based multi-agent architecture in `backend/agents/`:

- **AgentCoordinator** (`coordinator.py`): Routes queries to appropriate agents using LLM-based classification
- **KnowledgeRetrievalAgent** (`knowledge_retrieval.py`): Hierarchical RAG with citation tracking
- **DocumentAnalysisAgent** (`document_analysis.py`): Deep paper understanding and annotation
- **TimelineSynthesisAgent** (`timeline_synthesis.py`): Domain evolution and method comparison
- **WritingAssistantAgent** (`writing_assistant.py`): Review drafting and citation suggestions
- **ReviewerAgent** (`reviewer.py`): Paper evaluation with scoring rubric

All agents inherit from `BaseAgent` (`base.py`) and share a common `AgentContext` for state management.

### Data Flow

1. PDFs are processed by `PDFProcessor` with hierarchical chunking (Document → Section → Subsection → Atomic)
2. Embeddings stored in ChromaDB with paper metadata for traceability
3. Queries routed through `AgentCoordinator` to appropriate agent(s)
4. Agents use vector store for retrieval with page-level citations

## Key Directories

```
backend/
  app/
    api/endpoints.py      # FastAPI routes
    core/config.py        # Settings via pydantic-settings
    db/base.py            # SQLAlchemy models
    main.py               # FastAPI app entry
  agents/                 # Multi-agent system
  models/                 # SQLAlchemy model definitions
  services/               # Business logic (PDFProcessor, VectorStoreService, LLMService)

frontend/
  src/
    components/           # React components (ChatInterface, KnowledgeExplorer, etc.)
    utils/api.ts          # API client
    App.tsx               # Main app component

domain_pdf/               # Source PDFs for processing
scripts/                  # Utility scripts (process_pdfs.py)
```

## Common Commands

### Docker (Recommended for Development)

```bash
# Start all services
docker-compose up -d

# Rebuild and start (after code changes)
docker-compose up -d --build

# View logs
docker-compose logs -f backend
docker-compose logs -f celery

# Stop
docker-compose down

# Stop and remove volumes (reset data)
docker-compose down -v
```

### Manual Setup

```bash
# Initial setup (creates venv, installs deps)
./setup.sh

# Backend
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Celery worker (async PDF processing)
cd backend
source venv/bin/activate
celery -A app.tasks worker --loglevel=info

# Frontend
cd frontend
npm install
npm run dev          # Vite dev server on port 5173

# Process PDFs from domain_pdf/
cd scripts
python process_pdfs.py
```

### Testing

```bash
# Backend tests
cd backend
source venv/bin/activate
pytest

# Run specific test file
pytest tests/test_specific.py -v

# Run with coverage
pytest --cov=app --cov-report=html
```

### Linting

```bash
# Frontend linting
cd frontend
npm run lint         # ESLint for TypeScript/React
```

## Environment Configuration

Copy `.env.example` to `.env` and configure:

- `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` (at least one required)
- `DATABASE_URL` (PostgreSQL)
- `REDIS_URL` (Redis)
- `SECRET_KEY` (JWT secret)
- `VECTOR_DB_PATH` (ChromaDB persistence directory)
- `UPLOAD_DIR` (PDF upload directory)

## Key Dependencies

Backend:
- FastAPI, Pydantic v2, SQLAlchemy 2.0
- ChromaDB (vector store), sentence-transformers (embeddings)
- PyMuPDF, pytesseract (PDF processing with OCR)
- Celery + Redis (async tasks)

Frontend:
- React 18, TypeScript, Vite
- Ant Design (UI), TanStack Query (data fetching)
- Zustand (state management)
- Cytoscape.js (knowledge graphs), D3 (visualizations)

## API Endpoints

Base: `/api/v1`

- `POST /papers/upload` - Upload and process PDF
- `POST /knowledge/query` - Query knowledge base
- `POST /knowledge/chat` - Chat with AI
- `GET /knowledge/timeline` - Get domain timeline
- `POST /knowledge/compare` - Compare methods
- `POST /writing/draft-review` - Draft review section
- `POST /writing/suggest-citations` - Suggest citations
- `POST /review/evaluate` - Review paper

## Important Notes

- PDF processing uses hierarchical chunking with 4 levels (Document → Section → Subsection → Atomic chunks)
- Vector store stores chunks with page_start/page_end for traceability
- Agent routing uses LLM to classify queries before dispatching
- Celery workers handle async PDF processing; worker must be running for PDF uploads to complete
- Domain PDFs go in `domain_pdf/` folder; run `scripts/process_pdfs.py` to index them
- ChromaDB runs as separate container on port 8001 (docker) or use `chromadb` package directly (manual)
