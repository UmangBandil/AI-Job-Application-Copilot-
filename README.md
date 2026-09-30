# 🎯 AI Job Application Copilot

A full-stack AI-powered tool that helps job seekers apply to more roles faster and with higher quality. Combines resume/JD understanding, retrieval-augmented generation (RAG), and job-board APIs into one workflow.

## ✨ Features

- **Local LLM (Ollama)** — Run the AI fully locally via a provider abstraction (Ollama / OpenAI / Anthropic), with structured JSON generation and a health endpoint
- **Resume RAG Corpus** — Upload resumes, parse into structured chunks, embed into vector store
- **JD Ingestion** — Paste text or URLs, auto-parse into structured fields
- **Match Scoring** — Compare JD requirements against resume using embedding similarity + keyword checks
- **RAG Content Generation** — Generate cover letters, resume summaries, and bullets with source citations
- **Application Tracker** — Kanban board: Saved → Applied → Interview → Offer → Rejected
- **Job Search** — Pull live listings from Adzuna/RemoteOK, one-click import
- **Dashboard** — Analytics on applications, match scores, skill-gap trends

## 🏗️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (Python 3.12) + Gunicorn |
| Frontend | React + Vite |
| Database | PostgreSQL + pgvector |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| LLM | Ollama (local) or Claude / OpenAI API |
| Auth | JWT |
| Deploy | Docker, Render (or any Docker host) |

## 🚀 Quick Start (Local Development)

### Prerequisites
- Python 3.12+
- Node.js 20+
- PostgreSQL 16+ (or use Docker)

```bash
# 1. Clone & configure
git clone https://github.com/UmangBandil/AI-Job-Application-Copilot-.git
cd AI-Job-Application-Copilot-
cp .env.example .env
# Edit .env — set LLM_PROVIDER=ollama (local, no key needed) or add a cloud API key

# 2. Start database
docker run -d --name pgvector -p 5432:5432 \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=jobcopilot \
  pgvector/pgvector:pg16

# 3. Start backend
cd backend
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 4. Start frontend (new terminal)
cd frontend
npm install
npm run dev
```

- **Frontend:** http://localhost:5173
- **API docs:** http://localhost:8000/docs

### Local AI (Ollama)

The backend runs fully locally — no cloud API key required:

```powershell
# Install Ollama: https://ollama.com/download
ollama pull qwen3:8b
```

Then in `.env`:

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b
```

`GET /api/v1/ai/health` reports whether the local model is connected and available. If Ollama is offline, AI endpoints return a clear 503 with instructions.

## 🧪 Testing

```bash
cd backend
python -m pytest -q   # 56 tests — no Ollama or database required (LLM and network mocked)
```

## 🌐 Deploy to Render (Free)

### One-Click Deploy

1. **Push to GitHub** (already done)
2. Go to [Render Dashboard](https://dashboard.render.com)
3. Click **New → Blueprint**
4. Connect your GitHub repo
5. Render detects `render.yaml` and provisions:
   - A **Web Service** (backend + bundled frontend)
   - A **PostgreSQL database** (free tier)
6. In the service **Environment** tab, set:
   - `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` (at least one)
   - `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` (optional, for job search)
7. Click **Deploy**

Your app will be live at `https://job-copilot.onrender.com` (or similar).

### Manual Deploy (without Blueprint)

```bash
# Build and run locally with production settings
docker compose -f docker-compose.production.yml up --build -d

# Access at http://localhost:8000
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Auto (Render) | PostgreSQL async connection string |
| `DATABASE_URL_SYNC` | Auto (Render) | PostgreSQL sync connection string |
| `SECRET_KEY` | Auto (Render) | JWT signing secret (auto-generated) |
| `LLM_PROVIDER` | One LLM source | `ollama` (local, no key), `openai`, `anthropic`, or empty for auto-detect |
| `OLLAMA_BASE_URL` | With ollama | Local Ollama API URL |
| `OLLAMA_MODEL` | With ollama | Local model tag (e.g. `qwen3:8b`) |
| `ANTHROPIC_API_KEY` | One LLM key | Claude API key |
| `OPENAI_API_KEY` | One LLM key | OpenAI API key |
| `ADZUNA_APP_ID` | Optional | Adzuna API credentials |
| `ADZUNA_APP_KEY` | Optional | Adzuna API credentials |
| `DEBUG` | No | Set to `false` in production |

## 📁 Project Structure

```
├── backend/
│   ├── app/
│   │   ├── ai/           # LLM provider abstraction (Ollama / OpenAI / Anthropic)
│   │   ├── api/          # 8 API route modules
│   │   ├── core/         # Config, DB, auth, dependencies
│   │   ├── models/       # 7 SQLAlchemy ORM models
│   │   ├── schemas/      # Pydantic request/response schemas
│   │   └── services/     # Business logic (parsing, RAG, LLM, search)
│   ├── Dockerfile                # Development Dockerfile
│   ├── Dockerfile.production     # Production (multi-stage, bundled frontend)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/   # Shared UI components
│   │   ├── contexts/     # React contexts (auth)
│   │   ├── pages/        # 6 page components
│   │   └── services/     # API client
│   └── package.json
├── docker-compose.yml                # Development
├── docker-compose.production.yml     # Production (single service)
├── render.yaml                       # Render Blueprint (one-click deploy)
└── .env.example
```

## 📋 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/ai/health` | LLM provider status |
| POST | `/api/v1/ai/chat` | Chat with configured LLM |
| POST | `/api/v1/ai/generate-json` | Structured JSON generation |
| GET / PATCH | `/api/v1/profile` | Candidate profile (authoritative personal data) |
| GET | `/api/v1/memory/search` | Semantic search over previous Q/A |
| POST / GET | `/api/v1/memory/answers` | Save / list question memory |
| POST | `/api/v1/auth/register` | Register new user |
| POST | `/api/v1/auth/login` | Login |
| GET | `/api/v1/auth/me` | Current user |
| POST | `/api/v1/resumes` | Upload resume |
| GET | `/api/v1/resumes` | List resumes |
| DELETE | `/api/v1/resumes/:id` | Delete resume |
| POST | `/api/v1/job-descriptions` | Create JD |
| GET | `/api/v1/job-descriptions` | List JDs |
| POST | `/api/v1/job-descriptions/match` | Match resume to JD |
| POST | `/api/v1/generate` | RAG content generation |
| POST | `/api/v1/applications` | Create application |
| GET | `/api/v1/applications` | List applications |
| PATCH | `/api/v1/applications/:id` | Update application |
| DELETE | `/api/v1/applications/:id` | Delete application |
| POST | `/api/v1/job-search` | Search job boards |
| GET | `/api/v1/dashboard/stats` | Dashboard analytics |
| GET | `/api/v1/health` | Health check |

## 🗺️ Status

**IMPLEMENTED:** auth · resume RAG · JD parsing · match scoring · cited content generation · application tracker · job search · dashboard · Docker/Render deploy · LLM provider abstraction with local Ollama + AI endpoints (health / chat / generate-json) · SSRF-hardened JD fetching · Alembic migrations (schema changes are migrations, startup auto-applies) · pgvector embeddings with HNSW cosine index · candidate profile (GET/PATCH /api/v1/profile) · application question memory with semantic retrieval (/api/v1/memory) · backend test suite

**PARTIAL:** in-DB vector search for resume chunks (column + index ready; matching still loads chunks in Python) · job-search deduplication

**PLANNED:** Chrome extension (MV3) · answer engine with anti-hallucination field policies · ATS adapters · multi-page application agent · human-review UI · Playwright fixture tests — see [docs/ARCHITECTURE_AUDIT.md](docs/ARCHITECTURE_AUDIT.md)

---

Built as a portfolio project for AI-powered job search automation.
