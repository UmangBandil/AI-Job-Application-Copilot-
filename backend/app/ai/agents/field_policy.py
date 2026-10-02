"""Field policy engine.

Classifies an application question into one of six policies BEFORE any LLM
call, with a classification confidence. This is the server-side authority:
the extension's mapper is a fast client-side pre-filter, but this module
decides what the answer engine may actually do. Sensitive topics always map
to USER_CONFIRMATION_REQUIRED — the LLM is never asked and memory is never
auto-applied to them, no matter what the client claims.

Confidence expresses certainty about the *policy*, not the answer:
regex profile/sensitive matches are near-certain (0.95–1.0), heuristic
buckets (choice fields, open text) sit in the 0.75–0.90 band, and anything
with no usable text is UNKNOWN (0.0) so it can never be auto-filled.
"""

import re
from enum import Enum


class AnswerPolicy(str, Enum):
    PROFILE_ONLY = "profile_only"                      # deterministic profile fill, no LLM
    PROFILE_OR_MEMORY = "profile_or_memory"            # memory may answer if profile has none
    RESUME_REQUIRED = "resume_required"                # answerable only from resume facts
    LLM_GENERATED = "llm_generated"                    # grounded generation allowed
    USER_CONFIRMATION_REQUIRED = "user_confirmation_required"  # never auto-answered
    UNKNOWN = "unknown"                                # unclassifiable — never auto-filled


# Server-side sensitive-topic rules. Mirrors the extension mapper's
# SENSITIVE_RULES so a tampered/naive client can never downgrade a
# sensitive question to "ask the LLM". Order matters: first match wins.
SENSITIVE_RULES = [
    (re.compile(r"sponsorship|sponsor|visa|h1b|h-1b|immigra|work\s*auth|authorized|eligible|right\s*to\s*work"), "work authorization / sponsorship"),
    (re.compile(r"salary|compensation|expected\s*pay|pay\s*expect|wage|notice\s*period"), "compensation / notice period"),
    (re.compile(r"gender|ethnic|race|disab|veteran|criminal|convict|crime|background\s*check|religion"), "demographics / background"),
    (re.compile(r"relocat|willing\s*to\s*move|travel"), "relocation / travel"),
]

# Deterministic profile mappings (superset of the fill-planner's map so the
# answer endpoint can also serve as fallback for fields whose profile value
# was empty). Keys are profile keys; the agent resolves actual values.
_PROFILE_PATTERNS = [
    ("first_name", re.compile(r"first\s*name|given\s*name")),
    ("last_name", re.compile(r"last\s*name|surname|family\s*name")),
    ("full_name", re.compile(r"^name$|full\s*name|your\s*name")),
    ("email", re.compile(r"e-?mail")),
    ("phone", re.compile(r"phone|mobile|contact\s*number")),
    ("linkedin_url", re.compile(r"linked\s*in")),
    ("github_url", re.compile(r"git\s*hub")),
    ("portfolio_url", re.compile(r"portfolio|website|personal\s*site")),
    ("location", re.compile(r"location|city|current\s*city")),
]

# Experience-length questions ("How many years of experience…") are answered
# from profile/memory, not invented by the LLM.
_YEARS_RE = re.compile(r"years\s*of\s*experience|years\s*exp|experience.*\byears|years.*experience")

_QUESTION_RE = re.compile(r"\?")
_LETTER_RE = re.compile(r"[a-z]")


def sensitive_reason(question: str) -> str | None:
    """Return the sensitive topic this question touches, or None."""
    q = (question or "").lower()
    for pattern, reason in SENSITIVE_RULES:
        if pattern.search(q):
            return reason
    return None


def classify_question(
    question: str,
    field_type: str = "text",
    client_policy: str | None = None,
) -> tuple[AnswerPolicy, str, float]:
    """Map a question to its answer policy with a classification confidence.

    Returns (policy, reason, confidence). The client's own classification is
    recorded but never trusted for sensitive topics — the server always
    re-checks. Fields with no recognizable text classify as UNKNOWN with
    confidence 0.0 so downstream gates can never auto-fill them.
    """
    q = (question or "").strip().lower()

    # Nothing to classify on — the field cannot be trusted to automation.
    if not q or not _LETTER_RE.search(q):
        return AnswerPolicy.UNKNOWN, "no recognizable label — cannot classify", 0.0

    reason = sensitive_reason(q)
    if reason:
        return AnswerPolicy.USER_CONFIRMATION_REQUIRED, reason, 1.0

    if _YEARS_RE.search(q):
        return AnswerPolicy.PROFILE_OR_MEMORY, "experience length (profile-or-memory)", 0.90

    for profile_key, pattern in _PROFILE_PATTERNS:
        if pattern.search(q):
            return AnswerPolicy.PROFILE_ONLY, f"profile field '{profile_key}'", 0.95

    is_choice = field_type in ("select", "checkbox", "radio")
    is_long_text = field_type == "textarea"
    if is_choice:
        return AnswerPolicy.PROFILE_OR_MEMORY, "choice field — check saved answers", 0.85
    if is_long_text or _QUESTION_RE.search(q):
        return AnswerPolicy.LLM_GENERATED, "free-text / open question", 0.90

    return AnswerPolicy.LLM_GENERATED, "general question", 0.75


def match_profile_key(question: str) -> str | None:
    """Which profile field does this question map to (None = none)?"""
    q = (question or "").lower()
    for profile_key, pattern in _PROFILE_PATTERNS:
        if pattern.search(q):
            return profile_key
    return None


def client_policy_matches(server_policy: AnswerPolicy, client_policy: str | None) -> bool:
    """Whether the extension's classification agrees with the server's.

    Used for anomaly notes only — the server policy always wins.
    """
    if not client_policy:
        return True
    mapping = {
        AnswerPolicy.PROFILE_ONLY: {"profile"},
        AnswerPolicy.PROFILE_OR_MEMORY: {"profile", "memory"},
        AnswerPolicy.RESUME_REQUIRED: {"ai", "memory"},
        AnswerPolicy.LLM_GENERATED: {"ai", "memory", "unknown"},
        AnswerPolicy.USER_CONFIRMATION_REQUIRED: {"review"},
        AnswerPolicy.UNKNOWN: {"unknown"},
    }
    return client_policy in mapping.get(server_policy, set())
