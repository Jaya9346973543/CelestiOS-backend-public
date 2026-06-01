from fastapi import APIRouter, HTTPException
from typing import Optional, Dict, Any
from pydantic import BaseModel
from db.models import DailyFeedback
from db import storage
from services.openai_service import generate_schedule_insights, generate_rest_of_day_plan
from api.calendar import _day_range, _get_access_token, _fetch_google_events, _build_event_payload
from datetime import datetime, timedelta, timezone

router = APIRouter(prefix="", tags=["Recommendations and Feedback"])

_insights_cache: Dict[str, Dict[str, Any]] = {}

VALID_VIEWS = ("morning", "afternoon", "evening", "later")


def clear_user_cache(user_id: str) -> int:
    """
    Clear all in-memory cache entries for a specific user.
    Returns the number of cache entries cleared.
    """
    keys_to_delete = [key for key in _insights_cache.keys() if key.startswith(f"{user_id}:")]
    for key in keys_to_delete:
        del _insights_cache[key]
    print(f"[Cache] Cleared {len(keys_to_delete)} in-memory cache entries for user {user_id}")
    return len(keys_to_delete)


class RecommendationResponse(BaseModel):
    user_id: str
    date: str
    day_type: str
    view: str
    insights: str
    detailed_insights: str
    quick_insights: str


class LateStartCheckinRequest(BaseModel):
    date: str  # YYYY-MM-DD format
    late_start: bool
    started_at: str  # Time like "16:30"
    focus: Optional[str] = None  # Night work focus (e.g., "Finish the report")


class RestOfDayResponse(BaseModel):
    user_id: str
    date: str
    plan: str
    started_at: str


def _pick_insights(view: str, day_type: str, detailed: str, quick: str) -> str:
    if view in ("morning", "afternoon", "evening"):
        return detailed
    if day_type in ("burnout", "overloaded"):
        return detailed
    return quick


def _cache_key(
    user_id: str,
    date: str,
    sleep_hours: Optional[float],
    energy_level: Optional[str],
    priority: Optional[str],
) -> str:
    return f"{user_id}:{date}:{sleep_hours}:{energy_level}:{priority}"


@router.get("/recommendations", response_model=RecommendationResponse)
async def get_daily_recommendations(
    user_id: str,
    date: str,
    view: str = "morning",
    tz: Optional[str] = None,
    sleep_hours: Optional[float] = None,
    energy_level: Optional[str] = None,
    priority: Optional[str] = None,
):
    if view not in VALID_VIEWS:
        view = "morning"

    # 1. Check database cache FIRST (survives server restarts)
    db_cache = storage.get_cached_insights(user_id, date, max_age_hours=2)
    if db_cache:
        print(f"[Cache HIT - DATABASE] Using database cache for {user_id} on {date}")
        return {
            "user_id": user_id,
            "date": date,
            "day_type": db_cache["day_type"],
            "view": view,
            "insights": _pick_insights(
                view, db_cache["day_type"], db_cache["detailed_insights"], db_cache["quick_insights"]
            ),
            "detailed_insights": db_cache["detailed_insights"],
            "quick_insights": db_cache["quick_insights"],
        }

    # 2. Check in-memory cache (legacy, faster but lost on restart)
    key = _cache_key(user_id, date, sleep_hours, energy_level, priority)
    if key in _insights_cache:
        cached = _insights_cache[key]
        print(f"[Cache HIT - IN-MEMORY] Using in-memory cache for {user_id} on {date}")
        return {
            "user_id": user_id,
            "date": date,
            "day_type": cached["day_type"],
            "view": view,
            "insights": _pick_insights(
                view, cached["day_type"], cached["detailed"], cached["quick"]
            ),
            "detailed_insights": cached["detailed"],
            "quick_insights": cached["quick"],
        }

    print(f"[Cache MISS] Regenerating insights for {user_id} on {date}")

    # 3. Get user profile
    user = storage.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 3. Get today's events — NOW USES tz
    time_min, time_max = _day_range(date, tz)
    events = []

    try:
        access_token = await _get_access_token(user_id)
        google_events = await _fetch_google_events(access_token, time_min, time_max)
        for event in google_events:
            payload = _build_event_payload(user_id, event)
            if payload:
                events.append({
                    "summary": payload.get("summary"),
                    "start": payload.get("start_time"),
                    "end": payload.get("end_time"),
                    "status": payload.get("status"),
                })
    except Exception:
        db_events = storage.get_events_between(user_id, time_min, time_max)
        for row in db_events:
            events.append({
                "summary": row.get("summary"),
                "start": row.get("start_time"),
                "end": row.get("end_time"),
                "status": row.get("status"),
            })

    # 4. Build context
    user_timezone = tz or user.get("timezone")

    # Get yesterday's evening check-in data for context
    yesterday = (datetime.fromisoformat(date) - timedelta(days=1)).strftime('%Y-%m-%d')
    yesterday_checkin = storage.get_checkin(user_id, yesterday)
    yesterday_context = None
    if yesterday_checkin and yesterday_checkin.get("evening_completed_at"):
        yesterday_context = {
            "completed_priority": yesterday_checkin.get("completed_priority"),
            "disruption": yesterday_checkin.get("disruption"),
            "disruption_detail": yesterday_checkin.get("disruption_detail"),
        }

    user_context = {
        "name": user.get("name"),
        "profession": user.get("profession"),
        "short_term_goal": user.get("short_term_goal"),
        "timezone": user_timezone,
        "yesterday": yesterday_context,
    }

    checkin_data = {
        "sleep_hours": sleep_hours,
        "energy_level": energy_level,
        "priority": priority,
    }

    # 5. Generate insights with current time (timezone-aware)
    current_time = datetime.now(timezone.utc).isoformat()
    detailed, quick, day_type = await generate_schedule_insights(
        events, user_context, checkin_data, current_time
    )

    # 6. Cache it ONLY if check-in is complete (has priority)
    # Don't cache incomplete check-ins - they should regenerate on each request
    has_complete_checkin = bool(priority)

    if has_complete_checkin:
        # Cache in memory
        _insights_cache[key] = {
            "detailed": detailed,
            "quick": quick,
            "day_type": day_type,
        }

        # Save to database cache (survives server restarts)
        try:
            storage.cache_insights(
                user_id=user_id,
                date=date,
                detailed=detailed,
                quick=quick,
                day_type=day_type
            )
            print(f"[Cache SAVE] Cached insights for {user_id} on {date}")
        except Exception as e:
            print(f"[Cache ERROR] Failed to cache insights: {e}")
            # Continue even if caching fails
    else:
        print(f"[Cache SKIP] Incomplete check-in (no priority), not caching insights for {user_id} on {date}")

    # 7. Pick the right version
    primary_insights = _pick_insights(view, day_type, detailed, quick)

    return {
        "user_id": user_id,
        "date": date,
        "day_type": day_type,
        "view": view,
        "insights": primary_insights,
        "detailed_insights": detailed,
        "quick_insights": quick,
    }


@router.post("/recommendations/rest-of-day", response_model=RestOfDayResponse)
async def get_rest_of_day_plan(
    late_start_data: LateStartCheckinRequest,
    user_id: str,
    tz: Optional[str] = None,
):
    """
    Generate AI-powered rest-of-day plan for users who arrive late (4+ PM).
    This is the late-day mode that replaces full morning check-in.
    """
    # 1. Get user profile
    user = storage.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 2. Save late start check-in data
    late_start_payload = {
        "user_id": user_id,
        "date": late_start_data.date,
        "late_start": late_start_data.late_start,
        "started_at": late_start_data.started_at,
    }

    try:
        storage.upsert_checkin(late_start_payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save late start data: {exc}") from exc

    # 3. Get remaining events for today
    user_timezone = tz or user.get("timezone")
    current_time = datetime.now(timezone.utc).isoformat()
    _, time_max = _day_range(late_start_data.date, user_timezone)

    events = []
    try:
        access_token = await _get_access_token(user_id)
        google_events = await _fetch_google_events(access_token, current_time, time_max)
        for event in google_events:
            payload = _build_event_payload(user_id, event)
            if payload:
                events.append({
                    "summary": payload.get("summary"),
                    "start": payload.get("start_time"),
                    "end": payload.get("end_time"),
                    "status": payload.get("status"),
                })
    except Exception:
        db_events = storage.get_events_between(user_id, current_time, time_max)
        for row in db_events:
            events.append({
                "summary": row.get("summary"),
                "start": row.get("start_time"),
                "end": row.get("end_time"),
                "status": row.get("status"),
            })

    # 4. Build context
    user_context = {
        "name": user.get("name"),
        "profession": user.get("profession"),
        "short_term_goal": user.get("short_term_goal"),
        "timezone": user_timezone,
        "started_at": late_start_data.started_at,
        "focus": late_start_data.focus,  # Night work focus (optional)
    }

    # 5. Generate AI plan for rest of day (returns detailed and quick)
    detailed_plan, quick_plan = await generate_rest_of_day_plan(
        events, user_context, late_start_data.started_at, current_time
    )

    # Combine both formats with separator for storage
    combined_plan = f"{detailed_plan}\n---QUICK---\n{quick_plan}"

    # 6. Save plan to checkin for future retrieval
    try:
        storage.upsert_checkin({
            "user_id": user_id,
            "date": late_start_data.date,
            "rest_of_day_plan": combined_plan
        })
    except Exception:
        pass  # Don't fail if plan save fails

    return {
        "user_id": user_id,
        "date": late_start_data.date,
        "plan": combined_plan,  # Return combined format for backward compatibility
        "started_at": late_start_data.started_at,
    }


@router.post("/feedback")
async def submit_daily_feedback(feedback: DailyFeedback):
    try:
        storage.insert_feedback(feedback.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save feedback: {exc}") from exc
    return {"message": "Feedback saved successfully. Thank you!"}


@router.get("/feedback/{user_id}")
async def get_user_feedback(user_id: str, limit: int = 30):
    try:
        return storage.get_feedback_by_user(user_id, limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch feedback: {exc}") from exc
