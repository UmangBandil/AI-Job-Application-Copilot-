"""RAG-grounded content generation with citation enforcement."""

import json
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import JobDescription, Resume, ResumeChunk
from app.services.matching_service import cosine_similarity
from app.services.resume_service import embed_query

settings = get_settings()

# ── LLM client abstraction ────────────────────────────────────────────

async def _call_llm(prompt: str, system: str = "", max_tokens: int = 2000) -> str:
    """Call the best available LLM (Anthropic first, then OpenAI)."""
    if settings.ANTHROPIC_API_KEY:
        return await _call_anthropic(prompt, system, max_tokens)
    elif settings.OPENAI_API_KEY:
        return await _call_openai(prompt, system, max_tokens)
    else:
        raise RuntimeError("No LLM API key configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.")


async def _call_anthropic(prompt: str, system: str, max_tokens: int) -> str:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    message = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


async def _call_openai(prompt: str, system: str, max_tokens: int) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content


# ── Retrieval ────────────────────────────────────────────────────────

async def retrieve_relevant_chunks(
    db: AsyncSession,
    resume_id: str,
    jd: JobDescription,
    top_k: int = 8,
) -> list[ResumeChunk]:
    """Retrieve the most relevant resume chunks for a JD using embedding similarity."""
    result = await db.execute(
        select(ResumeChunk).where(ResumeChunk.resume_id == resume_id)
    )
    chunks = result.scalars().all()

    if not chunks:
        return []

    jd_data = jd.parsed_data or {}
    jd_text = f"{jd_data.get('role', '')} {jd.title} {' '.join(jd_data.get('must_have_skills', []))} {' '.join(jd_data.get('nice_to_have_skills', []))} {' '.join(jd_data.get('responsibilities', [])[:10])}"
    jd_embedding = embed_query(jd_text)

    scored = []
    for chunk in chunks:
        if chunk.embedding:
            sim = cosine_similarity(jd_embedding, chunk.embedding)
            scored.append((sim, chunk))
        else:
            scored.append((0.0, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [chunk for _, chunk in scored[:top_k]]


# ── Generation ───────────────────────────────────────────────────────

GENERATION_SYSTEM_PROMPT = """You are an expert job application writer. You generate tailored resume content and cover letters that are STRICTLY grounded in the candidate's actual experience.

CRITICAL RULES:
1. ONLY use information from the provided resume excerpts. Every claim MUST be traceable to a provided source.
2. DO NOT fabricate skills, experience, projects, or achievements not present in the source material.
3. If the JD requires skills the candidate doesn't have, acknowledge the gap rather than fabricating.
4. Use the [SOURCE: N] citation format to reference which resume excerpt supports each claim.
5. Write naturally but honestly — quality over quantity.

You will be given:
- The job description
- Resume excerpts (numbered chunks)
- Instructions on what to generate and the tone/length"""


COVER_LETTER_PROMPT = """Write a cover letter for this position.

JOB DESCRIPTION:
{jd_text}

RESUME EXCERPTS:
{resume_excerpts}

INSTRUCTIONS:
- Tone: {tone}
- Length: {length}
- Include [SOURCE: N] citations after each claim
- Address the specific role and company
- Highlight the most relevant experience from the excerpts
- Be honest about fit — don't claim experience that isn't in the excerpts"""


RESUME_SUMMARY_PROMPT = """Write a tailored resume professional summary for this position.

JOB DESCRIPTION:
{jd_text}

RESUME EXCERPTS:
{resume_excerpts}

INSTRUCTIONS:
- Tone: {tone}
- Length: {length}
- 3-5 sentences maximum
- Include [SOURCE: N] citations
- Highlight the most relevant skills and experience for this specific role
- Be honest — only reference what's in the excerpts"""


RESUME_BULLETS_PROMPT = """Generate tailored resume bullet points for this position.

JOB DESCRIPTION:
{jd_text}

RESUME EXCERPTS:
{resume_excerpts}

INSTRUCTIONS:
- Tone: {tone}
- Length: {length}
- 5-8 bullet points
- Each bullet must have [SOURCE: N] citation
- Use strong action verbs
- Quantify achievements where the source material supports it
- Prioritize experience most relevant to the JD"""


async def generate_content(
    db: AsyncSession,
    resume_id: str,
    jd_id: str,
    content_type: str = "cover_letter",
    tone: str = "formal",
    length: str = "concise",
) -> dict:
    """Generate RAG-grounded content with citations."""
    # Fetch JD
    jd_result = await db.execute(select(JobDescription).where(JobDescription.id == jd_id))
    jd = jd_result.scalar_one_or_none()
    if not jd:
        raise ValueError("Job description not found")

    # Retrieve relevant chunks
    chunks = await retrieve_relevant_chunks(db, resume_id, jd)

    # Format excerpts
    excerpts = []
    for i, chunk in enumerate(chunks, 1):
        excerpts.append(f"[{i}] ({chunk.chunk_type}) {chunk.chunk_text}")
    resume_excerpts = "\n\n".join(excerpts)

    jd_text = f"Role: {jd.title}\nCompany: {jd.company}\n\n{jd.raw_text}"

    # Select prompt
    if content_type == "cover_letter":
        prompt = COVER_LETTER_PROMPT
    elif content_type == "resume_summary":
        prompt = RESUME_SUMMARY_PROMPT
    elif content_type == "resume_bullets":
        prompt = RESUME_BULLETS_PROMPT
    else:
        raise ValueError(f"Unknown content_type: {content_type}")

    length_desc = "Keep it brief and impactful" if length == "concise" else "Be thorough and detailed"
    tone_desc = "Professional and formal tone" if tone == "formal" else "Friendly and conversational tone"

    formatted_prompt = prompt.format(
        jd_text=jd_text,
        resume_excerpts=resume_excerpts,
        tone=tone_desc,
        length=length_desc,
    )

    content = await _call_llm(formatted_prompt, system=GENERATION_SYSTEM_PROMPT)

    # Extract citations from the generated content
    citations = []
    citation_pattern = re.compile(r"\[SOURCE:\s*(\d+)\]")
    found_indices = set(citation_pattern.findall(content))
    for idx_str in found_indices:
        idx = int(idx_str) - 1
        if 0 <= idx < len(chunks):
            chunk = chunks[idx]
            citations.append({
                "chunk_id": str(chunk.id),
                "chunk_text": chunk.chunk_text[:200],
                "chunk_type": chunk.chunk_type,
                "source_number": int(idx_str),
            })

    return {
        "content": content,
        "citations": citations,
        "content_type": content_type,
    }
