"""Prompt assembly for the form answer engine (M5).

The system prompt encodes the honesty contract the whole product depends on:
ground every answer in supplied context, never invent personal facts, never
answer sensitive topics, and return JSON only.
"""

ANSWER_SYSTEM_PROMPT = """\
You are a job application assistant. You answer ONE application question \
for a candidate, based ONLY on the context provided.

STRICT RULES:
1. Ground every claim in the CANDIDATE CONTEXT, SAVED ANSWERS, or RESUME \
EXCERPTS below. Never invent employers, dates, numbers, certifications, \
degrees, or achievements.
2. If the context does not contain the information, return \
"insufficient_context" as the answer and do not guess.
3. For Yes/No questions, answer exactly "Yes" or "No" only when the context \
clearly supports it; otherwise return "insufficient_context".
4. Keep text answers concise (1-3 sentences unless asked for more), \
first person, professional tone, factual.
5. If the question touches compensation, sponsorship/visa, work \
authorization, demographics, criminal history, notice period, relocation, \
or travel availability, you MUST return "declined" as the answer — a human \
answers these, never you.
6. Do not include explanations, apologies, or commentary outside the JSON.
7. Respond with a single JSON object, no markdown fences.

Respond with exactly this JSON shape:
{
  "answer": "<the answer text, or 'insufficient_context', or 'declined'>",
  "confidence": <number between 0.0 and 1.0 measuring how well the supplied \
context supports this answer>,
  "notes": "<one short sentence: which context facts you used, or what is \
missing>"
}
"""


def build_answer_prompt(
    question: str,
    profile_context: str = "",
    memory_matches: list[dict] | None = None,
    resume_excerpts: list[dict] | None = None,
    job_description: str = "",
    field_type: str = "text",
    field_options: list[str] | None = None,
    max_chars: int = 500,
) -> str:
    """Assemble the user prompt for a single application question."""
    options_block = ""
    if field_options:
        listed = "\n".join(f"  - {o}" for o in field_options[:25])
        options_block = f"\nALLOWED OPTIONS (answer should be one of these, verbatim):\n{listed}\n"

    memory_block = ""
    if memory_matches:
        pairs = "\n".join(
            f"- Q: {m.get('question', '')}\n  A: {m.get('answer', '')} (similarity {m.get('similarity', 0):.2f})"
            for m in memory_matches[:5]
        )
        memory_block = f"\nSAVED ANSWERS (previous answers by this candidate to similar questions):\n{pairs}\n"

    resume_block = ""
    if resume_excerpts:
        joined = "\n---\n".join(f"[{e.get('chunk_type', 'resume')}]\n{e.get('chunk_text', '')}" for e in resume_excerpts[:5])
        resume_block = f"\nRESUME EXCERPTS (verbatim facts about this candidate):\n{joined}\n"

    jd_block = ""
    if job_description:
        jd_block = f"\nJOB DESCRIPTION (for tone/relevance only — never source personal facts):\n{job_description[:4000]}\n"

    profile_block = ""
    if profile_context:
        profile_block = f"\nCANDIDATE CONTEXT (authoritative facts):\n{profile_context}\n"

    return f"""\
QUESTION: {question}
FIELD TYPE: {field_type}
MAX ANSWER LENGTH: {max_chars} characters{options_block}{profile_block}{memory_block}{resume_block}{jd_block}
Answer the question now using only the context above. Return the JSON object.
"""
