# Domain Expert Multi-Agent System

A sophisticated AI-powered system for single-cell 3D genomics research that provides hierarchical knowledge retrieval, domain timeline tracking, and intelligent document analysis.

## Features

### 1. Hierarchical Knowledge Base
- 4-level content hierarchy: Document → Section → Subsection → Atomic chunks
- Full traceability with page-level citations
- RAG + semantic detection + OCR for comprehensive PDF understanding
- Multi-hop retrieval for complex queries

### 2. Multi-Agent Architecture
- **Document Analysis Agent**: Deep paper understanding and annotation
- **Knowledge Retrieval Agent**: Hierarchical RAG with citation tracking
- **Timeline & Synthesis Agent**: Domain evolution and method comparison
- **Writing Assistant Agent**: Review drafting and citation suggestions
- **Reviewer Agent**: Paper evaluation with scoring rubric

### 3. Interactive Frontend
- Chat interface with clickable citations
- Knowledge explorer with timeline visualization
- Method comparison matrices
- Paper management and upload
- Review dashboard with scoring

### 4. Domain Coverage
Specialized for single-cell 3D genomics:
- scHi-C and variants
- Dip-C
- scMicro-C
- LIANTI
- HiRES
- TCC and related methods

## Quick Start

### Using Docker (Recommended)

1. **Clone and configure:**
```bash
cd domain_expert
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY or OPENAI_API_KEY
```

2. **Start services:**
```bash
docker-compose up -d
```

3. **Access:**
- Frontend: http://localhost
- API: http://localhost/api
- API Docs: http://localhost/api/docs

### Manual Setup

1. **Setup script:**
```bash
./setup.sh
```

2. **Configure environment:**
```bash
cp .env.example .env
# Edit .env with your API keys
```

3. **Start backend:**
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload
```

4. **Start frontend:**
```bash
cd frontend
npm run dev
```

5. **Process existing PDFs:**
```bash
cd scripts
python process_pdfs.py
```

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (React)                      │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐    │
│  │   Chat      │  │   Knowledge  │  │  Review         │    │
│  │ Interface   │  │  Explorer    │  │ Dashboard       │    │
│  └─────────────┘  └──────────────┘  └─────────────────┘    │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP/WebSocket
┌──────────────────────────────▼──────────────────────────────┐
│                     FastAPI Backend                          │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Agent Coordinator                       │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────────┐    │    │
│  │  │ Document │ │Knowledge │ │Timeline &        │    │    │
│  │  │ Analysis │ │Retrieval │ │Synthesis         │    │    │
│  │  └──────────┘ └──────────┘ └──────────────────┘    │    │
│  │  ┌──────────┐ ┌──────────┐                        │    │
│  │  │ Writing  │ │Reviewer  │                        │    │
│  │  │Assistant │ │          │                        │    │
│  │  └──────────┘ └──────────┘                        │    │
│  └─────────────────────────────────────────────────────┘    │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
┌───────▼─────┐ ┌──────▼──────┐ ┌────▼──────┐
│ ChromaDB    │ │ PostgreSQL  │ │   Redis   │
│ (Vectors)   │ │ (Metadata)  │ │  (Cache)  │
└─────────────┘ └─────────────┘ └───────────┘
```

## API Endpoints

### Papers
- `POST /api/v1/papers/upload` - Upload PDF
- `GET /api/v1/papers` - List papers
- `GET /api/v1/papers/{id}` - Get paper details

### Knowledge
- `POST /api/v1/knowledge/query` - Query knowledge base
- `POST /api/v1/knowledge/chat` - Chat with AI
- `GET /api/v1/knowledge/timeline` - Get domain timeline
- `POST /api/v1/knowledge/compare` - Compare methods
- `GET /api/v1/knowledge/debates` - Get debates

### Writing
- `POST /api/v1/writing/draft-review` - Draft review section
- `POST /api/v1/writing/suggest-citations` - Suggest citations
- `POST /api/v1/writing/check-claims` - Check claim validity

### Review
- `POST /api/v1/review/evaluate` - Review paper

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `ANTHROPIC_API_KEY` | Claude API key | Yes* |
| `OPENAI_API_KEY` | OpenAI API key | Yes* |
| `DATABASE_URL` | PostgreSQL connection | Yes |
| `REDIS_URL` | Redis connection | Yes |
| `SECRET_KEY` | JWT secret | Yes |

*At least one LLM API key is required.

## Development

### Backend Structure
```
backend/
├── app/
│   ├── api/          # API endpoints
│   ├── core/         # Configuration
│   ├── db/           # Database models
│   └── main.py       # FastAPI app
├── agents/           # Multi-agent system
├── models/           # Database models
└── services/         # Business logic
```

### Frontend Structure
```
frontend/src/
├── components/       # React components
├── utils/           # API utilities
├── App.tsx          # Main app
└── main.tsx         # Entry point
```

## Deployment

### Cloud Deployment

1. **Build images:**
```bash
docker-compose build
```

2. **Push to registry:**
```bash
docker tag domain_expert_backend your-registry/domain_expert_backend
docker push your-registry/domain_expert_backend
```

3. **Deploy with docker-compose on server**

### Production Considerations

- Use HTTPS with proper SSL certificates
- Set strong SECRET_KEY
- Configure proper CORS origins
- Enable authentication for production use
- Set up monitoring (Prometheus/Grafana)
- Configure log aggregation
- Use managed database services
- Set up backup strategies

## License

MIT License

## Citation

If you use this system in your research, please cite:

```
Domain Expert Multi-Agent System for Single-Cell 3D Genomics
https://github.com/yourusername/domain_expert
```
