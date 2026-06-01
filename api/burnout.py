"""
Burnout Detection API
Endpoints for detecting calendar overload, stress, and providing interventions.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime, timezone
import pytz

from db import storage
from services.burnout_detection import detect_burnout
from services.microsoft_client import (
    get_today_work_calendar_events,
    is_microsoft_connected,
    apply_burnout_changes
)
from services.ics_generator import generate_ics_file, format_ics_filename
from services.calendar_view_generator import generate_optimized_view


router = APIRouter(prefix="/burnout", tags=["Burnout Detection"])


# ═══════════════════════════════════════════════════════════════════════
# REQUEST MODELS
# ═══════════════════════════════════════════════════════════════════════

class BurnoutDetectionRequest(BaseModel):
    user_id: str
    priority: str = Field(..., min_length=1, max_length=500)
    manual_energy: Optional[str] = Field(None, pattern="^(low|medium|high)$")
    manual_sleep: Optional[float] = Field(None, ge=0, le=24)
    date: Optional[str] = None  # YYYY-MM-DD, defaults to today


class ApplyChangesRequest(BaseModel):
    user_id: str
    focus_block: Dict  # Focus block from burnout detection result
    suggested_changes: Optional[List[Dict]] = None  # Meetings to move with reasons
    priority: Optional[str] = None  # For ICS description


# ═══════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

async def get_merged_calendar_events(
    user_id: str,
    date_str: str,
    user_timezone: str = "UTC"
) -> List[Dict]:
    """
    Merge calendar events from Google (personal) and Microsoft (work) calendars.

    Args:
        user_id: User's google_id
        date_str: Date string (YYYY-MM-DD)
        user_timezone: User's timezone

    Returns:
        List of merged events with normalized format
    """
    merged_events = []

    # Get Google calendar events (personal)
    try:
        tz = pytz.timezone(user_timezone)
        google_events = storage.get_today_events(user_id, user_timezone=tz)

        for event in google_events:
            merged_events.append({
                'summary': event.get('summary', 'Untitled'),
                'start_time': event.get('start_time'),
                'end_time': event.get('end_time'),
                'source': 'google',
                'is_organizer': True  # Assume organizer for personal calendar
            })

        print(f"[Burnout] Fetched {len(google_events)} Google calendar events")
    except Exception as e:
        print(f"[Burnout] Failed to fetch Google calendar: {e}")

    # Get Microsoft calendar events (work) if connected
    if is_microsoft_connected(user_id):
        try:
            ms_events = await get_today_work_calendar_events(user_id, user_timezone)

            for event in ms_events:
                merged_events.append({
                    'summary': event.get('summary', 'Untitled'),
                    'start_time': event.get('start_time'),
                    'end_time': event.get('end_time'),
                    'source': 'microsoft',
                    'is_organizer': event.get('is_organizer', False)
                })

            print(f"[Burnout] Fetched {len(ms_events)} Microsoft calendar events")
        except Exception as e:
            print(f"[Burnout] Failed to fetch Microsoft calendar: {e}")
    else:
        print(f"[Burnout] Microsoft calendar not connected for user {user_id}")

    print(f"[Burnout] Total merged events: {len(merged_events)}")
    return merged_events


def get_wearable_data(user_id: str, date_str: str) -> Optional[Dict]:
    """
    Get wearable data (Oura/Fitbit) for a specific date.

    Returns:
        {
            "readiness_score": int,
            "sleep_duration_minutes": int,
            "resting_heart_rate": int,
            ...
        }
    """
    try:
        health_data = storage.get_latest_health_data(user_id, date_str)
        if health_data:
            print(f"[Burnout] Found wearable data from {health_data.get('provider')}")
            return health_data
    except Exception as e:
        print(f"[Burnout] Failed to fetch wearable data: {e}")

    return None


# ═══════════════════════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@router.post("/detect")
async def detect_burnout_endpoint(request: BurnoutDetectionRequest):
    """
    Detect burnout/overload and provide intervention recommendations.

    This endpoint:
    1. Merges Google (personal) + Microsoft (work) calendar events
    2. Gets wearable data (Oura/Fitbit) if connected
    3. Runs burnout detection algorithm
    4. Returns tier, drain percentage, focus block suggestion, and meeting changes

    Returns:
        {
            "tier": int (0-3),
            "drain_percentage": int (0-100),
            "signals_detected": List[str],
            "messages": {
                "headline": str,
                "before": str (optional),
                "after": str (optional),
                "insight": str (optional),
                "action": str
            },
            "focus_block": {
                "start_time": str (ISO),
                "end_time": str (ISO),
                "duration_minutes": int,
                "time_slot": str,
                "reasoning": str
            } (optional),
            "suggested_changes": List[Dict] (Tier 3 only),
            "details": {...}
        }
    """
    # Validate user exists
    user = storage.get_user(request.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_timezone = user.get("timezone", "UTC")

    # Determine date (default to today)
    if request.date:
        date_str = request.date
    else:
        tz = pytz.timezone(user_timezone)
        now = datetime.now(tz)
        date_str = now.strftime("%Y-%m-%d")

    print(f"[Burnout] Starting detection for user {request.user_id} on {date_str}")

    try:
        # Get merged calendar events (Google + Microsoft)
        events = await get_merged_calendar_events(request.user_id, date_str, user_timezone)

        if not events:
            print(f"[Burnout] Warning: No calendar events found for {request.user_id}")

        # Filter out existing focus blocks to prevent duplicate suggestions
        # Focus blocks have title "🎯 Focus Block - Priority Work" or "Focus Block - Priority Work"
        original_count = len(events)
        events = [
            evt for evt in events
            if "Focus Block" not in evt.get("summary", "")
            and "Focus Block" not in evt.get("title", "")
        ]
        filtered_count = original_count - len(events)
        if filtered_count > 0:
            print(f"[Burnout] Filtered out {filtered_count} existing focus block(s) from calendar")

        # Get wearable data if available
        wearable_data = get_wearable_data(request.user_id, date_str)

        # Run burnout detection
        result = detect_burnout(
            events=events,
            priority=request.priority,
            wearable_data=wearable_data,
            manual_energy=request.manual_energy,
            manual_sleep=request.manual_sleep,
            user_timezone=user_timezone
        )

        print(f"[Burnout] Detection complete: Tier {result['tier']}, {result['drain_percentage']}% drain")

        return result

    except Exception as exc:
        print(f"[Burnout] Detection failed: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Burnout detection failed: {exc}"
        ) from exc


@router.get("/status")
async def burnout_status(user_id: str, date: Optional[str] = None):
    """
    Quick check of user's burnout risk without full detection.

    Returns:
        {
            "calendars_connected": {
                "google": bool,
                "microsoft": bool
            },
            "wearables_connected": bool,
            "meeting_count": int,
            "data_completeness": str ("full", "partial", "minimal")
        }
    """
    user = storage.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_timezone = user.get("timezone", "UTC")

    # Determine date
    if date:
        date_str = date
    else:
        tz = pytz.timezone(user_timezone)
        now = datetime.now(tz)
        date_str = now.strftime("%Y-%m-%d")

    # Check calendar connections
    google_connected = True  # Always have Google if user exists
    microsoft_connected = is_microsoft_connected(user_id)

    # Check wearables
    wearable_data = get_wearable_data(user_id, date_str)
    wearables_connected = wearable_data is not None

    # Get event count
    try:
        events = await get_merged_calendar_events(user_id, date_str, user_timezone)
        meeting_count = len(events)
    except Exception:
        meeting_count = 0

    # Determine data completeness
    if google_connected and microsoft_connected and wearables_connected:
        completeness = "full"
    elif google_connected or microsoft_connected:
        completeness = "partial"
    else:
        completeness = "minimal"

    return {
        "calendars_connected": {
            "google": google_connected,
            "microsoft": microsoft_connected
        },
        "wearables_connected": wearables_connected,
        "meeting_count": meeting_count,
        "data_completeness": completeness
    }


@router.post("/apply")
async def apply_changes(request: ApplyChangesRequest):
    """
    Apply burnout detection changes to calendar via MS Graph API.

    This endpoint:
    1. Checks if Microsoft calendar is connected
    2. Creates focus block event in Microsoft calendar
    3. Returns success/failure status

    User must click "Apply Changes" button to trigger this.

    Returns:
        {
            "success": bool,
            "focus_block_created": Dict (event object),
            "errors": List[str],
            "fallback_ics_available": bool
        }
    """
    # Validate user
    user = storage.get_user(request.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_timezone = user.get("timezone", "UTC")

    # Check if Microsoft calendar is connected
    if not is_microsoft_connected(request.user_id):
        raise HTTPException(
            status_code=400,
            detail="Microsoft calendar not connected. Use ICS download instead."
        )

    try:
        # Apply changes via MS Graph API
        result = await apply_burnout_changes(
            user_id=request.user_id,
            focus_block=request.focus_block,
            suggested_changes=request.suggested_changes,
            user_timezone=user_timezone
        )

        # Add fallback option
        result["fallback_ics_available"] = True

        return result

    except Exception as exc:
        print(f"[Burnout] Apply changes failed: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to apply changes: {exc}"
        ) from exc


@router.get("/download-ics")
async def download_ics(
    user_id: str,
    focus_block_start: str,
    focus_block_end: str,
    reasoning: str,
    priority: Optional[str] = None
):
    """
    Download .ics file for focus block (fallback when no MS Graph write permission).

    Query params:
        user_id: User's google_id
        focus_block_start: ISO datetime string
        focus_block_end: ISO datetime string
        reasoning: Reason for focus block placement
        priority: User's priority text (optional)

    Returns:
        ICS file download
    """
    # Validate user
    user = storage.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_timezone = user.get("timezone", "UTC")
    tz = pytz.timezone(user_timezone)
    now = datetime.now(tz)
    date_str = now.strftime("%Y-%m-%d")

    # Build focus block dict
    focus_block = {
        "start_time": focus_block_start,
        "end_time": focus_block_end,
        "reasoning": reasoning
    }

    try:
        # Generate ICS content
        ics_content = generate_ics_file(
            focus_block=focus_block,
            user_timezone=user_timezone,
            priority_text=priority
        )

        # Generate filename
        filename = format_ics_filename(user_id, date_str)

        # Return as downloadable file
        return Response(
            content=ics_content,
            media_type="text/calendar",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )

    except Exception as exc:
        print(f"[Burnout] ICS generation failed: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate ICS file: {exc}"
        ) from exc


@router.post("/optimized-view")
async def get_optimized_view(burnout_result: Dict):
    """
    Generate human-readable optimized calendar view for manual copy-paste.

    This is the fallback option when user can't use MS Graph API or ICS download.

    Args:
        burnout_result: Full burnout detection result from /burnout/detect

    Returns:
        {
            "timeline": List[str],  # Text lines showing before/after
            "instructions": List[str],  # Step-by-step what to do
            "summary": str  # One-line summary
        }
    """
    try:
        # Extract user_id from burnout_result details if available
        # For now, we'll use UTC as default
        user_timezone = "UTC"

        # Generate optimized view
        view = generate_optimized_view(burnout_result, user_timezone)

        return view

    except Exception as exc:
        print(f"[Burnout] Optimized view generation failed: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate optimized view: {exc}"
        ) from exc
