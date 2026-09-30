"""Application question memory.

Stores every question a user answers (with its semantic representation) and
retrieves previous answers for new, similar questions — the learn-as-you-go
memory behind answer reuse. User-provided answers outrank generated ones
(source authority: user > memory > profile > llm).
"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApplicationQuestion, User
from app.services.resume_service import embed_query

SOURCE_AUTHORITY = {"user": 3, "memory": 2, "profile": 1, "llm": 0}
DEFAULT_MIN_SIMILARITY = 0.80

_STOPWORDS = frozenset(
    """
    a an the do does did have has had are is was were will would can could shall should
    you your yours i my me we our us with and or of for to in on at from as by be been
    being it its this that these those before after any some about into over under again
    further once here there when why how what which who whom all both each more most
    other such no nor not only own same so than too very
    """.split()
)

# Light synonym folding so "Have you worked with Java before?", "Do you know
# Java?" and "Have you used Java?" all land on the same key as "experience
# with Java". Deliberately excludes "work" (e.g. "work authorization").
_SYNONYMS = {
    "worked": "experience",
    "used": "experience",
    "know": "experience",
    "familiar": "experience",
}


def normalize_question(question: str) -> str:
    """Reduce a question to a canonical keyword form.

    Lowercase, strip punctuation, drop stopwords, dedupe + sort keywords —
    so "Do you have experience with Java?" and "Have you worked with Java
    before?" normalize to the same fast-match key.
    """
    cleaned = re.sub(r"[^\w\s]", " ", question.lower())
    words = [_SYNONYMS.get(w, w) for w in cleaned.split() if w and w not in _STOPWORDS]
    return " ".join(sorted(set(words)))[:500]


async def save_answer(
    db: AsyncSession,
    user_id,
    question: str,
    answer: str,
    source: str = "user",
    confidence: float = 1.0,
    context: str = "",
    normalized: str | None = None,
) -> ApplicationQuestion:
    """Store a question/answer pair with its embedding."""
    if normalized is None:
        normalized = normalize_question(question)
    record = ApplicationQuestion(
        user_id=user_id,
        question=question,
        normalized_question=normalized,
        answer=answer,
        source=source,
        confidence=confidence,
        context=context or "",
        embedding=embed_query(question),
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return record


def _to_match(record: ApplicationQuestion, similarity: float) -> dict:
    return {
        "id": record.id,
        "question": record.question,
        "answer": record.answer,
        "source": record.source,
        "confidence": record.confidence,
        "context": record.context or "",
        "similarity": round(similarity, 4),
    }


async def find_similar_questions(
    db: AsyncSession,
    user: User,
    question: str,
    limit: int = 5,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> list[dict]:
    """Retrieve previous questions similar to the given one.

    Fast path: an exact normalized-form match returns immediately without
    paying for an embedding. Otherwise the question is embedded and pgvector
    cosine search runs (scoped to the user); results are ranked by source
    authority first, then similarity.
    """
    # 1. Exact normalized fast path
    normalized = normalize_question(question)
    res = await db.execute(
        select(ApplicationQuestion)
        .where(
            ApplicationQuestion.user_id == user.id,
            ApplicationQuestion.normalized_question == normalized,
        )
        .order_by(ApplicationQuestion.updated_at.desc())
        .limit(1)
    )
    exact = res.scalar_one_or_none()
    if exact is not None:
        return [_to_match(exact, similarity=1.0)]

    # 2. Semantic (pgvector) search
    query_vec = embed_query(question)
    distance = ApplicationQuestion.embedding.cosine_distance(query_vec)
    res = await db.execute(
        select(ApplicationQuestion, distance.label("distance"))
        .where(
            ApplicationQuestion.user_id == user.id,
            ApplicationQuestion.embedding.isnot(None),
        )
        .order_by(distance)
        .limit(limit * 3)
    )
    rows = res.all()

    min_distance = 1.0 - min_similarity
    pool = [_to_match(record, 1.0 - dist) for record, dist in rows if dist is not None and dist <= min_distance]

    # User-authored answers win over generated ones; similarity breaks ties.
    pool.sort(key=lambda m: (-SOURCE_AUTHORITY.get(m["source"], 0), -m["similarity"]))
    return pool[:limit]
