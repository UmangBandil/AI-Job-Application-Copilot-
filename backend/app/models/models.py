import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    resumes = relationship("Resume", back_populates="user", cascade="all, delete-orphan")
    job_descriptions = relationship("JobDescription", back_populates="user", cascade="all, delete-orphan")
    applications = relationship("Application", back_populates="user", cascade="all, delete-orphan")
    profile = relationship("Profile", back_populates="user", uselist=False, cascade="all, delete-orphan")


class Profile(Base):
    """Authoritative candidate profile — the single source of truth for
    personal facts. The LLM may NEVER invent these values; answers must
    cite or stay silent."""

    __tablename__ = "profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True, index=True)

    # Contact / identity
    full_name = Column(String(255), default="")
    email = Column(String(255), default="")  # preferred contact email (may differ from login)
    phone = Column(String(50), default="")
    location = Column(String(255), default="")

    # Links
    website = Column(String(500), default="")
    linkedin_url = Column(String(500), default="")
    github_url = Column(String(500), default="")
    portfolio_url = Column(String(500), default="")

    # Structured history (JSONB)
    education = Column(JSONB, default=list)   # [{degree, institution, graduation_year, ...}]
    experience = Column(JSONB, default=list)  # [{company, title, start, end, highlights: []}]
    skills = Column(JSONB, default=list)      # ["python", "react", ...]
    projects = Column(JSONB, default=list)    # [{name, description, url, tech: []}]

    # Sensitive / preference data — never LLM-guessable
    work_authorization = Column(JSONB, default=dict)  # {status, requires_sponsorship, ...}
    notice_period = Column(String(100), default="")
    salary_expectation = Column(String(100), default="")
    willing_to_relocate = Column(Boolean, nullable=True)
    preferred_locations = Column(JSONB, default=list)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="profile")


class Resume(Base):
    __tablename__ = "resumes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=False)
    file_name = Column(String(255), nullable=False)
    raw_text = Column(Text, nullable=False)
    parsed_data = Column(JSONB, default=dict)  # structured: skills, experience, education, projects
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="resumes")
    chunks = relationship("ResumeChunk", back_populates="resume", cascade="all, delete-orphan")


class ResumeChunk(Base):
    __tablename__ = "resume_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resume_id = Column(UUID(as_uuid=True), ForeignKey("resumes.id"), nullable=False)
    chunk_text = Column(Text, nullable=False)
    chunk_type = Column(String(50), nullable=False)  # skill, experience, education, project, summary
    metadata_ = Column("metadata", JSONB, default=dict)
    # pgvector column (384 dims for all-MiniLM-L6-v2); migrated from ARRAY(Float)
    embedding = Column(Vector(384), nullable=True)

    resume = relationship("Resume", back_populates="chunks")


class JobDescription(Base):
    __tablename__ = "job_descriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title = Column(String(500), nullable=False)
    company = Column(String(255), default="")
    raw_text = Column(Text, nullable=False)
    source_url = Column(String(1000), default="")
    parsed_data = Column(JSONB, default=dict)
    # structured: role, must_have_skills, nice_to_have_skills, responsibilities, seniority
    created_at = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("User", back_populates="job_descriptions")
    applications = relationship("Application", back_populates="job_description")


class MatchScore(Base):
    __tablename__ = "match_scores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    job_description_id = Column(UUID(as_uuid=True), ForeignKey("job_descriptions.id"), nullable=False)
    resume_id = Column(UUID(as_uuid=True), ForeignKey("resumes.id"), nullable=False)
    overall_score = Column(Float, nullable=False)  # 0-100
    matched_skills = Column(JSONB, default=list)
    missing_skills = Column(JSONB, default=list)
    suggested_bullets = Column(JSONB, default=list)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    job_description = relationship("JobDescription")
    resume = relationship("Resume")


class Application(Base):
    __tablename__ = "applications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    job_description_id = Column(UUID(as_uuid=True), ForeignKey("job_descriptions.id"), nullable=False)
    resume_id = Column(UUID(as_uuid=True), ForeignKey("resumes.id"), nullable=False)
    status = Column(
        Enum("saved", "applied", "interview", "offer", "rejected", name="application_status"),
        default="saved",
    )
    match_score = Column(Float, nullable=True)
    cover_letter = Column(Text, default="")
    tailored_resume = Column(Text, default="")
    notes = Column(Text, default="")
    follow_up_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="applications")
    job_description = relationship("JobDescription", back_populates="applications")
    resume = relationship("Resume")


class ApplicationQuestion(Base):
    """Persistent question/answer memory.

    Every application question a user answers is stored with its semantic
    representation so future similar questions can reuse the approved
    answer instead of re-generating it. User-provided answers outrank
    LLM-generated ones (source authority: user > memory > profile > llm).
    """

    __tablename__ = "application_questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    question = Column(Text, nullable=False)
    normalized_question = Column(String(500), nullable=False)
    answer = Column(Text, nullable=False)
    # user (typed/approved by the human) | profile | memory | llm
    source = Column(String(20), nullable=False, default="user")
    confidence = Column(Float, default=1.0)
    # optional context (job/company) the answer was given in
    context = Column(String(500), default="")
    embedding = Column(Vector(384), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class JobSearchResult(Base):
    __tablename__ = "job_search_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title = Column(String(500), nullable=False)
    company = Column(String(255), default="")
    location = Column(String(255), default="")
    description = Column(Text, default="")
    url = Column(String(1000), default="")
    source = Column(String(50), nullable=False)  # adzuna, remoteok, manual
    salary_min = Column(Integer, nullable=True)
    salary_max = Column(Integer, nullable=True)
    raw_data = Column(JSONB, default=dict)
    imported = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
