from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import pytz

from db import storage
from services.openai_service import generate_schedule_insights
from services.email_service import send_insights_email
from services.burnout_detection import detect_burnout
from services.microsoft_client import get_today_work_calendar_events, is_microsoft_connected

router = APIRouter(prefix="/checkin", tags=["Check-in"])


class CheckinRequest(BaseModel):
    user_id: str
    sleep_hours: Optional[float] = Field(None, ge=0, le=24)
    energy_level: Optional[str] = Field(None, pattern="^(low|medium|high)$")
    priority: Optional[str] = Field(None, max_length=255)


@router.post("/")
async def submit_checkin(checkin: CheckinRequest):
    """
    User submits check-in data (sleep, energy, priority).

    NEW: Now includes burnout detection!
    - Merges Google + Microsoft calendar events
    - Detects overload, energy mismatch, missing breaks
    - Suggests focus blocks and meeting changes
    - Generates AI insights and sends them via email

    Returns insights + burnout detection results.
    """
    user = storage.get_user(checkin.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_timezone = user.get("timezone", "UTC")
    tz = pytz.timezone(user_timezone)
    today_str = datetime.now(tz).strftime('%Y-%m-%d')

    # ═══════════════════════════════════════════════════════════════════
    # STEP 1: Fetch Google calendar events (personal)
    # ═══════════════════════════════════════════════════════════════════
    try:
        google_events = storage.get_today_events(checkin.user_id, user_timezone=tz)
        print(f"[Checkin] Fetched {len(google_events)} Google calendar events")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch events: {exc}") from exc

    # ═══════════════════════════════════════════════════════════════════
    # STEP 2: Fetch Microsoft calendar events (work) if connected
    # ═══════════════════════════════════════════════════════════════════
    microsoft_events = []
    if is_microsoft_connected(checkin.user_id):
        try:
            microsoft_events = await get_today_work_calendar_events(checkin.user_id, user_timezone)
            print(f"[Checkin] Fetched {len(microsoft_events)} Microsoft calendar events")
        except Exception as e:
            print(f"[Checkin] Failed to fetch Microsoft calendar: {e}")
            # Continue without work calendar

    # Merge all events for burnout detection
    all_events_for_burnout = []

    # Add Google events
    for event in google_events:
        all_events_for_burnout.append({
            'summary': event.get('summary', 'Untitled'),
            'start_time': event.get('start_time'),
            'end_time': event.get('end_time'),
            'source': 'google',
            'is_organizer': True
        })

    # Add Microsoft events
    for event in microsoft_events:
        all_events_for_burnout.append({
            'summary': event.get('summary', 'Untitled'),
            'start_time': event.get('start_time'),
            'end_time': event.get('end_time'),
            'source': 'microsoft',
            'is_organizer': event.get('is_organizer', False)
        })

    # Deduplicate events by normalized title (trim spaces, lowercase)
    # Prefer Microsoft events over Google when duplicates exist
    seen_titles = {}
    deduped_events = []

    for event in all_events_for_burnout:
        normalized_title = event['summary'].strip().lower()

        if normalized_title in seen_titles:
            # Duplicate found - prefer Microsoft over Google
            existing = seen_titles[normalized_title]
            if event['source'] == 'microsoft' and existing['source'] == 'google':
                # Replace Google with Microsoft
                deduped_events.remove(existing)
                seen_titles[normalized_title] = event
                deduped_events.append(event)
                print(f"[Checkin] Deduplicated '{event['summary']}' - keeping Microsoft version")
            # else: keep existing (already Microsoft or both same source)
        else:
            # New event
            seen_titles[normalized_title] = event
            deduped_events.append(event)

    all_events_for_burnout = deduped_events
    total_event_count = len(all_events_for_burnout)
    print(f"[Checkin] Total merged events after dedup: {total_event_count}")

    # ═══════════════════════════════════════════════════════════════════
    # STEP 3: Get wearable data (Oura/Fitbit) if available
    # ═══════════════════════════════════════════════════════════════════
    wearable_data = None
    try:
        wearable_data = storage.get_latest_health_data(checkin.user_id, today_str)
        if wearable_data:
            print(f"[Checkin] Found wearable data from {wearable_data.get('provider')}")
    except Exception as e:
        print(f"[Checkin] No wearable data: {e}")

    # ═══════════════════════════════════════════════════════════════════
    # STEP 4: Run burnout detection (if priority provided)
    # ═══════════════════════════════════════════════════════════════════
    burnout_result = None
    if checkin.priority:
        try:
            # Check if focus blocks already exist for today
            # Focus blocks have title "🎯 Focus Block - Priority Work" or "Focus Block - Priority Work"
            existing_focus_blocks = [
                evt for evt in all_events_for_burnout
                if "Focus Block" in evt.get("summary", "")
                or "Focus Block" in evt.get("title", "")
            ]

            if existing_focus_blocks:
                # Skip burnout detection if focus block already exists
                print(f"[Checkin] Skipping burnout detection - {len(existing_focus_blocks)} focus block(s) already exist for today")
                burnout_result = None
            else:
                # No focus blocks exist - run burnout detection
                burnout_result = detect_burnout(
                    events=all_events_for_burnout,
                    priority=checkin.priority,
                    wearable_data=wearable_data,
                    manual_energy=checkin.energy_level,
                    manual_sleep=checkin.sleep_hours,
                    user_timezone=user_timezone
                )
            print(f"[Checkin] Burnout detection: Tier {burnout_result['tier']}, {burnout_result['drain_percentage']}% drain")
        except Exception as e:
            print(f"[Checkin] Burnout detection failed: {e}")
            # Continue without burnout detection

    # ═══════════════════════════════════════════════════════════════════
    # STEP 4.5: Save check-in data to database
    # ═══════════════════════════════════════════════════════════════════
    try:
        checkin_payload = {
            "user_id": checkin.user_id,
            "date": today_str,
            "sleep_hours": checkin.sleep_hours,
            "energy_level": checkin.energy_level,
            "priority": checkin.priority
        }
        storage.upsert_checkin(checkin_payload)
        print(f"[Checkin] Saved check-in to database for {checkin.user_id}")
    except Exception as e:
        print(f"[Checkin] Failed to save check-in: {e}")
        # Continue anyway - insights can still be generated

    # ═══════════════════════════════════════════════════════════════════
    # STEP 5: Generate AI insights (existing flow)
    # ═══════════════════════════════════════════════════════════════════
    user_context = {
        "name": user.get("name"),
        "profession": user.get("profession"),
        "short_term_goal": user.get("short_term_goal"),
        "timezone": user_timezone,
    }

    checkin_data = {
        "sleep_hours": checkin.sleep_hours,
        "energy_level": checkin.energy_level,
        "priority": checkin.priority,
    }

    try:
        detailed, quick, day_type = await generate_schedule_insights(
            google_events,  # Use Google events for existing insights
            user_context=user_context,
            checkin_data=checkin_data,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate insights: {exc}") from exc

    # ═══════════════════════════════════════════════════════════════════
    # STEP 6: Cache insights
    # ═══════════════════════════════════════════════════════════════════
    try:
        storage.cache_insights(
            user_id=checkin.user_id,
            date=today_str,
            detailed=detailed,
            quick=quick,
            day_type=day_type
        )
        print(f"[Checkin] Cached insights for {checkin.user_id}")
    except Exception as e:
        print(f"[Checkin] Failed to cache insights: {e}")

    # ═══════════════════════════════════════════════════════════════════
    # STEP 7: Send insights email
    # ═══════════════════════════════════════════════════════════════════
    try:
        send_insights_email(
            to_email=user["email"],
            name=user.get("name", ""),
            detailed=detailed,
            quick=quick,
            day_type=day_type,
            events=google_events,
        )
    except Exception as e:
        print(f"[Checkin] Insights email failed: {e}")

    # ═══════════════════════════════════════════════════════════════════
    # STEP 8: Return combined response
    # ═══════════════════════════════════════════════════════════════════
    response = {
        "detailed": detailed,
        "quick": quick,
        "day_type": day_type,
        "event_count": total_event_count,
        "calendars": {
            "google": len(google_events),
            "microsoft": len(microsoft_events)
        }
    }

    # Include burnout detection if available
    if burnout_result:
        response["burnout"] = burnout_result

    return response
