"""Dashboard analytics API endpoints."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import Application, JobDescription, MatchScore, User
from app.schemas.schemas import DashboardStats

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get dashboard analytics for the current user."""
    # Total applications
    total_result = await db.execute(
        select(func.count(Application.id)).where(Application.user_id == user.id)
    )
    total_applications = total_result.scalar() or 0

    # Applications by status
    status_result = await db.execute(
        select(Application.status, func.count(Application.id))
        .where(Application.user_id == user.id)
        .group_by(Application.status)
    )
    applications_by_status = {
        "saved": 0, "applied": 0, "interview": 0, "offer": 0, "rejected": 0
    }
    for status, count in status_result.all():
        applications_by_status[status] = count

    # Applications this week
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    week_result = await db.execute(
        select(func.count(Application.id)).where(
            Application.user_id == user.id,
            Application.created_at >= week_ago,
        )
    )
    applications_this_week = week_result.scalar() or 0

    # Average match score
    avg_result = await db.execute(
        select(func.avg(MatchScore.overall_score)).where(MatchScore.user_id == user.id)
    )
    average_match_score = round(float(avg_result.scalar() or 0), 1)

    # Response rate (interviews / total submitted, i.e. excluding 'saved')
    submitted = (applications_by_status.get("applied", 0)
                 + applications_by_status.get("interview", 0)
                 + applications_by_status.get("offer", 0)
                 + applications_by_status.get("rejected", 0))
    interviews = applications_by_status.get("interview", 0) + applications_by_status.get("offer", 0)
    response_rate = round((interviews / submitted * 100) if submitted > 0 else 0, 1)

    # Skill gap trends across all JDs
    jd_result = await db.execute(
        select(JobDescription.parsed_data).where(JobDescription.user_id == user.id)
    )
    all_must_have: dict[str, int] = {}
    all_nice_have: dict[str, int] = {}
    total_jds = 0
    for (parsed_data,) in jd_result.all():
        total_jds += 1
        if parsed_data:
            for skill in parsed_data.get("must_have_skills", []):
                all_must_have[skill] = all_must_have.get(skill, 0) + 1
            for skill in parsed_data.get("nice_to_have_skills", []):
                all_nice_have[skill] = all_nice_have.get(skill, 0) + 1

    total_jds = max(total_jds, 1)

    # Find skills that appear frequently in JDs
    skill_gap_trends = []
    for skill, freq in sorted(all_must_have.items(), key=lambda x: x[1], reverse=True):
        skill_gap_trends.append({
            "skill": skill,
            "frequency": freq,
            "percentage": round(freq / total_jds * 100, 1),
            "in_rejected_matches": False,  # Could be enhanced with match data
        })

    return DashboardStats(
        total_applications=total_applications,
        applications_by_status=applications_by_status,
        applications_this_week=applications_this_week,
        average_match_score=average_match_score,
        response_rate=response_rate,
        skill_gap_trends=skill_gap_trends[:15],
    )
