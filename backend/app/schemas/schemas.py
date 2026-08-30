from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


# ── Auth ──────────────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str = ""


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ── Resume ────────────────────────────────────────────────────────────────
class ResumeResponse(BaseModel):
    id: UUID
    title: str
    file_name: str
    raw_text: str
    parsed_data: dict
    is_active: bool
    created_at: datetime
    chunk_count: int = 0

    model_config = {"from_attributes": True}


class ResumeChunkResponse(BaseModel):
    id: UUID
    chunk_text: str
    chunk_type: str
    metadata_: dict

    model_config = {"from_attributes": True}


# ── Job Description ──────────────────────────────────────────────────────
class JDCreate(BaseModel):
    title: str = ""
    company: str = ""
    raw_text: str
    source_url: str = ""


class JDResponse(BaseModel):
    id: UUID
    title: str
    company: str
    raw_text: str
    source_url: str
    parsed_data: dict
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Match Score ──────────────────────────────────────────────────────────
class MatchScoreResponse(BaseModel):
    id: UUID
    job_description_id: UUID
    resume_id: UUID
    overall_score: float
    matched_skills: list[str]
    missing_skills: list[str]
    suggested_bullets: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class MatchRequest(BaseModel):
    job_description_id: UUID
    resume_id: UUID


# ── Generation ──────────────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    job_description_id: UUID
    resume_id: UUID
    tone: str = "formal"  # formal, casual
    length: str = "concise"  # concise, detailed
    content_type: str = "cover_letter"  # cover_letter, resume_summary, resume_bullets


class GeneratedContent(BaseModel):
    content: str
    citations: list[dict]  # [{chunk_id, chunk_text, relevance}]
    content_type: str


# ── Application ──────────────────────────────────────────────────────────
class ApplicationCreate(BaseModel):
    job_description_id: UUID
    resume_id: UUID
    match_score: float | None = None
    cover_letter: str = ""
    tailored_resume: str = ""
    notes: str = ""


class ApplicationUpdate(BaseModel):
    status: str | None = None
    notes: str | None = None
    follow_up_date: datetime | None = None
    cover_letter: str | None = None
    tailored_resume: str | None = None


class ApplicationResponse(BaseModel):
    id: UUID
    job_description_id: UUID
    resume_id: UUID
    status: str
    match_score: float | None
    cover_letter: str
    tailored_resume: str
    notes: str
    follow_up_date: datetime | None
    created_at: datetime
    updated_at: datetime
    job_title: str = ""
    company: str = ""

    model_config = {"from_attributes": True}


# ── Job Search ──────────────────────────────────────────────────────────
class JobSearchParams(BaseModel):
    query: str = ""
    location: str = ""
    page: int = 1
    source: str = "all"  # all, adzuna, remoteok


class JobSearchResultResponse(BaseModel):
    id: UUID
    title: str
    company: str
    location: str
    description: str
    url: str
    source: str
    salary_min: int | None
    salary_max: int | None
    imported: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Dashboard ──────────────────────────────────────────────────────────
class DashboardStats(BaseModel):
    total_applications: int
    applications_by_status: dict[str, int]
    applications_this_week: int
    average_match_score: float
    response_rate: float  # interview / applied
    skill_gap_trends: list[dict]  # [{skill, frequency, in_rejected_matches}]
