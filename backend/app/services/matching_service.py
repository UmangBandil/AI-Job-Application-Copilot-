"""Match scoring: embedding similarity + keyword-based skill matching."""

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import JobDescription, Resume, ResumeChunk
from app.services.resume_service import embed_query


def cosine_similarity(a: list[float], b: list[float]) -> float:
    a_arr = np.array(a)
    b_arr = np.array(b)
    dot = np.dot(a_arr, b_arr)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


async def compute_match_score(
    db: AsyncSession,
    resume_id: str,
    jd_id: str,
) -> dict:
    """Compute match score between a resume and a job description.

    Returns dict with overall_score, matched_skills, missing_skills, suggested_bullets.
    """
    # Fetch resume chunks
    result = await db.execute(
        select(ResumeChunk).where(ResumeChunk.resume_id == resume_id)
    )
    chunks = result.scalars().all()

    # Fetch JD
    jd_result = await db.execute(
        select(JobDescription).where(JobDescription.id == jd_id)
    )
    jd = jd_result.scalar_one_or_none()
    if not jd:
        raise ValueError("Job description not found")

    jd_data = jd.parsed_data or {}
    must_have = set(jd_data.get("must_have_skills", []))
    nice_to_have = set(jd_data.get("nice_to_have_skills", []))

    # Extract all skills from resume chunks
    resume_skills = set()
    for chunk in chunks:
        meta = chunk.metadata_ or {}
        if chunk.chunk_type == "skill":
            resume_skills.update(meta.get("skills", []))
        # Also scan chunk text for skills
        text_lower = chunk.chunk_text.lower()
        for skill in must_have | nice_to_have:
            if skill in text_lower:
                resume_skills.add(skill)

    resume_skills_lower = {s.lower() for s in resume_skills}
    must_have_lower = {s.lower() for s in must_have}
    nice_to_have_lower = {s.lower() for s in nice_to_have}

    matched = resume_skills_lower & must_have_lower
    nice_matched = resume_skills_lower & nice_to_have_lower
    missing = must_have_lower - resume_skills_lower

    # Keyword match score (60% weight)
    keyword_score = 0.0
    if must_have_lower:
        keyword_score = (len(matched) / len(must_have_lower)) * 100

    # Embedding similarity score (40% weight)
    embedding_score = 0.0
    if chunks:
        jd_text = f"{jd_data.get('role', '')} {jd.title} {' '.join(jd_data.get('must_have_skills', []))} {' '.join(jd_data.get('responsibilities', [])[:5])}"
        jd_embedding = embed_query(jd_text)

        chunk_similarities = []
        for chunk in chunks:
            if chunk.embedding:
                sim = cosine_similarity(jd_embedding, chunk.embedding)
                chunk_similarities.append(sim)

        if chunk_similarities:
            # Use top-5 average
            top_k = sorted(chunk_similarities, reverse=True)[:5]
            embedding_score = (sum(top_k) / len(top_k)) * 100

    # Combined score
    overall = (keyword_score * 0.6) + (embedding_score * 0.4)
    overall = round(min(overall, 100.0), 1)

    # Suggested bullets — chunks most relevant to the JD
    suggested_bullets = []
    if chunks and jd_embedding:
        scored_chunks = []
        for chunk in chunks:
            if chunk.embedding and chunk.chunk_type in ("experience", "project"):
                sim = cosine_similarity(jd_embedding, chunk.embedding)
                scored_chunks.append((sim, chunk.chunk_text))
        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        suggested_bullets = [text for _, text in scored_chunks[:5]]

    return {
        "overall_score": overall,
        "matched_skills": sorted(matched),
        "missing_skills": sorted(missing),
        "suggested_bullets": suggested_bullets,
    }
