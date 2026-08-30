# 🎯 AI Job Application Copilot

A full-stack AI-powered tool that helps job seekers apply to more roles faster and with higher quality. Combines resume/JD understanding, retrieval-augmented generation (RAG), and job-board APIs into one workflow.

## ✨ Features

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
| Backend | FastAPI (Python 3.12) |
| Frontend | React + Vite |
| Database | PostgreSQL + pgvector |
| Vector Store | pgvector (on same Postgres) |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| LLM | Claude / OpenAI API |
| Auth | JWT |
| Deploy | Docker Compose |

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- Node.js 20+
- PostgreSQL 16+ (or use Docker)

### 1. Clone & configure
```bash
cp .env.example .env
# Edit .env with your API keys (at least one LLM key)
```

### 2. Start database (Docker)
```bash
docker run -d --name pgvector -p 5432:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=jobcopilot pgvector/pgvector:pg16
```

### 3. Start backend
```bash
cd backend
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 4. Start frontend
```bash
cd frontend
npm install
npm run dev
```

### 5. Open
- Frontend: http://localhost:5173
- API docs: http://localhost:8000/docs

### Docker Compose (all-in-one)
```bash
docker compose up --build
```

## 📁 Project Structure

```
├── backend/
│   ├── app/
│   │   ├── api/          # API route handlers
│   │   ├── core/         # Config, DB, auth, dependencies
│   │   ├── models/       # SQLAlchemy ORM models
│   │   ├── schemas/      # Pydantic request/response schemas
│   │   └── services/     # Business logic (parsing, RAG, LLM, search)
│   ├── alembic/          # Database migrations
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/   # Shared UI components
│   │   ├── contexts/     # React contexts (auth)
│   │   ├── pages/        # Page components
│   │   └── services/     # API client
│   └── package.json
└── docker-compose.yml
```

## 🔑 Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL async connection string |
| `SECRET_KEY` | Yes | JWT signing secret |
| `ANTHROPIC_API_KEY` | One LLM key | Claude API key |
| `OPENAI_API_KEY` | One LLM key | OpenAI API key |
| `ADZUNA_APP_ID` | Optional | Adzuna API credentials |
| `ADZUNA_APP_KEY` | Optional | Adzuna API credentials |

## 📋 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/register` | Register new user |
| POST | `/api/v1/auth/login` | Login |
| POST | `/api/v1/resumes` | Upload resume |
| GET | `/api/v1/resumes` | List resumes |
| POST | `/api/v1/job-descriptions` | Create JD |
| POST | `/api/v1/job-descriptions/match` | Match resume to JD |
| POST | `/api/v1/generate` | Generate content (RAG) |
| GET/POST | `/api/v1/applications` | CRUD applications |
| POST | `/api/v1/job-search` | Search job boards |
| GET | `/api/v1/dashboard/stats` | Dashboard analytics |

---

Built as a portfolio project for AI-powered job search automation.
