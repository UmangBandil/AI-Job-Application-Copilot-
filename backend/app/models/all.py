"""Single import point registering every ORM model on Base.metadata."""

from app.models.models import (  # noqa: F401
    Application,
    JobDescription,
    JobSearchResult,
    MatchScore,
    Resume,
    ResumeChunk,
    User,
)
