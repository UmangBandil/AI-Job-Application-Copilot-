"""Resume parsing, chunking, and embedding service."""

import io
import re
from uuid import UUID

from PyPDF2 import PdfReader
from docx import Document as DocxDocument
from sentence_transformers import SentenceTransformer

from app.core.config import get_settings

settings = get_settings()

# Singleton model — loaded once
_embedding_model: SentenceTransformer | None = None


def get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(settings.EMBEDDING_MODEL)
    return _embedding_model


# ── File extraction ──────────────────────────────────────────────────────

def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def extract_text_from_docx(file_bytes: bytes) -> str:
    doc = DocxDocument(io.BytesIO(file_bytes))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def extract_text(file_bytes: bytes, filename: str) -> str:
    name_lower = filename.lower()
    if name_lower.endswith(".pdf"):
        return extract_text_from_pdf(file_bytes)
    elif name_lower.endswith(".docx"):
        return extract_text_from_docx(file_bytes)
    elif name_lower.endswith(".txt"):
        return file_bytes.decode("utf-8", errors="replace")
    else:
        raise ValueError(f"Unsupported file format: {filename}")


# ── Structured parsing ──────────────────────────────────────────────────

SECTION_PATTERNS = {
    "summary": re.compile(
        r"(?i)(?:summary|profile|objective|about)\s*\n",
        re.MULTILINE,
    ),
    "experience": re.compile(
        r"(?i)(?:experience|work\s+history|employment)\s*\n",
        re.MULTILINE,
    ),
    "education": re.compile(
        r"(?i)(?:education|academic)\s*\n",
        re.MULTILINE,
    ),
    "skills": re.compile(
        r"(?i)(?:skills?|technologies|tech\s+stack|competencies)\s*\n",
        re.MULTILINE,
    ),
    "projects": re.compile(
        r"(?i)(?:projects?|portfolio)\s*\n",
        re.MULTILINE,
    ),
}

SKILL_KEYWORDS = [
    # Languages
    "python", "javascript", "typescript", "java", "c++", "c#", "go", "rust", "ruby", "php", "swift", "kotlin", "sql", "html", "css", "scss",
    # Frameworks
    "react", "vue", "angular", "next.js", "nuxt", "svelte", "fastapi", "django", "flask", "spring", "express", "node.js", "rails", "laravel",
    "tailwind", "bootstrap", "jquery",
    # Databases
    "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "sqlite", "dynamodb", "cassandra", "neo4j",
    # Cloud/Infra
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform", "jenkins", "github actions", "ci/cd", "nginx",
    # ML/AI
    "machine learning", "deep learning", "nlp", "pytorch", "tensorflow", "scikit-learn", "pandas", "numpy",
    "opencv", "hugging face", "langchain", "openai", "llm", "rag", "transformers",
    # Tools
    "git", "linux", "bash", "rest api", "graphql", "grpc", "kafka", "rabbitmq", "celery",
]


def parse_resume(raw_text: str) -> dict:
    """Parse resume text into structured sections."""
    lines = raw_text.split("\n")
    sections: dict[str, list[str]] = {
        "summary": [],
        "experience": [],
        "education": [],
        "skills": [],
        "projects": [],
        "other": [],
    }

    current_section = "other"
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        matched = False
        for section_name, pattern in SECTION_PATTERNS.items():
            if pattern.match(stripped):
                current_section = section_name
                matched = True
                break

        if not matched:
            sections[current_section].append(stripped)

    # Extract skills from skill section and full text
    skills_found = set()
    full_text_lower = raw_text.lower()
    for skill in SKILL_KEYWORDS:
        if skill.lower() in full_text_lower:
            skills_found.add(skill)

    # Also extract skills from the skills section explicitly
    for line in sections.get("skills", []):
        for part in re.split(r"[,|•\-–]", line):
            part = part.strip().lower()
            if part and len(part) < 40:
                skills_found.add(part)

    return {
        "summary": "\n".join(sections["summary"]),
        "experience": sections["experience"],
        "education": "\n".join(sections["education"]),
        "skills": sorted(skills_found),
        "projects": sections["projects"],
        "raw_sections": sections,
    }


# ── Chunking ──────────────────────────────────────────────────────────

def chunk_resume(parsed_data: dict, raw_text: str) -> list[dict]:
    """Split parsed resume into typed chunks for embedding."""
    chunks = []

    # Summary chunk
    summary = parsed_data.get("summary", "").strip()
    if summary:
        chunks.append({
            "chunk_text": summary,
            "chunk_type": "summary",
            "metadata_": {},
        })

    # Skills chunks (grouped in batches of 10)
    skills = parsed_data.get("skills", [])
    for i in range(0, len(skills), 10):
        batch = skills[i : i + 10]
        chunks.append({
            "chunk_text": "Skills: " + ", ".join(batch),
            "chunk_type": "skill",
            "metadata_": {"skills": batch},
        })

    # Experience chunks — each bullet/experience entry
    experience_lines = parsed_data.get("experience", [])
    current_exp: list[str] = []
    for line in experience_lines:
        if re.match(r"^(?:[A-Z][\w\s]*\s+at\s+|[\w\s]+—|[\w\s]+–|[\w\s]+\|\s)", line) and current_exp:
            chunks.append({
                "chunk_text": "\n".join(current_exp),
                "chunk_type": "experience",
                "metadata_": {},
            })
            current_exp = [line]
        else:
            current_exp.append(line)
    if current_exp:
        chunks.append({
            "chunk_text": "\n".join(current_exp),
            "chunk_type": "experience",
            "metadata_": {},
        })

    # Project chunks
    project_lines = parsed_data.get("projects", [])
    current_proj: list[str] = []
    for line in project_lines:
        if re.match(r"^[A-Z]", line) and current_proj:
            chunks.append({
                "chunk_text": "\n".join(current_proj),
                "chunk_type": "project",
                "metadata_": {},
            })
            current_proj = [line]
        else:
            current_proj.append(line)
    if current_proj:
        chunks.append({
            "chunk_text": "\n".join(current_proj),
            "chunk_type": "project",
            "metadata_": {},
        })

    # Education chunk
    education = parsed_data.get("education", "").strip()
    if education:
        chunks.append({
            "chunk_text": education,
            "chunk_type": "education",
            "metadata_": {},
        })

    # If no structured chunks were created, use the full text as one chunk
    if not chunks:
        chunks.append({
            "chunk_text": raw_text[:2000],
            "chunk_type": "other",
            "metadata_": {},
        })

    return chunks


# ── Embedding ──────────────────────────────────────────────────────────

def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts using the sentence-transformers model."""
    model = get_embedding_model()
    embeddings = model.encode(texts, show_progress_bar=False)
    return embeddings.tolist()


def embed_query(query: str) -> list[float]:
    """Embed a single query string."""
    model = get_embedding_model()
    embedding = model.encode([query], show_progress_bar=False)
    return embedding[0].tolist()
