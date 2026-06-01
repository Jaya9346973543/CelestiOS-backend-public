"""
Microsoft Graph API client for calendar integration.
Handles OAuth token management and calendar event fetching.
"""

import httpx
import time
import pytz
from typing import List, Dict, Optional
from datetime import datetime, timezone, timedelta
from core.config import settings
from db import storage


async def get_calendar_events(
    user_id: str,
    start_datetime: str,
    end_datetime: str
) -> List[Dict]:
    """
    Fetch calendar events from Microsoft Graph API for a specific date range.

    Args:
        user_id: CelestiOS user ID
        start_datetime: ISO 8601 datetime string (e.g., "2026-05-04T00:00:00Z")
        end_datetime: ISO 8601 datetime string (e.g., "2026-05-04T23:59:59Z")

    Returns:
        List of event dictionaries with normalized format

    Raises:
        ValueError: If Microsoft calendar not connected
        httpx.HTTPStatusError: If API request fails
    """
    # Get Microsoft access token from storage
    token_data = storage.get_microsoft_token(user_id)
    if not token_data:
        raise ValueError("Microsoft calendar not connected")

    access_token = token_data["access_token"]
    expires_at = token_data["expires_at"]

    # Check if token is expired (with 5-minute buffer)
    if time.time() >= (expires_at - 300):
        print(f"[Microsoft] Token expired for user {user_id}, refreshing...")
        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            raise ValueError("No refresh token available, user needs to re-authenticate")
        access_token = await refresh_microsoft_token(user_id, refresh_token)

    # Fetch events using calendarView endpoint
    url = "https://graph.microsoft.com/v1.0/me/calendarView"
    params = {
        "startDateTime": start_datetime,
        "endDateTime": end_datetime,
        "$select": "subject,start,end,isAllDay,isCancelled,showAs,organizer",
        "$orderby": "start/dateTime",
        "$top": 100  # Limit to 100 events per day (reasonable for burnout detection)
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Prefer": 'outlook.timezone="UTC"'  # Normalize all times to UTC
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        print(f"[Microsoft] API error: {e.response.status_code} - {e.response.text}")
        raise
    except httpx.RequestError as e:
        print(f"[Microsoft] Network error: {e}")
        raise

    events = data.get("value", [])

    # Filter and normalize events
    normalized_events = []
    for event in events:
        # Skip cancelled or all-day events
        if event.get("isCancelled", False) or event.get("isAllDay", False):
            continue

        # Skip events marked as "free" (not busy time)
        if event.get("showAs") == "free":
            continue

        # Microsoft returns UTC times but without 'Z' suffix
        # Append 'Z' so JavaScript recognizes them as UTC
        start_dt = event["start"]["dateTime"]
        end_dt = event["end"]["dateTime"]
        if not start_dt.endswith('Z'):
            start_dt = start_dt.split('.')[0] + 'Z'  # Remove milliseconds, add Z
        if not end_dt.endswith('Z'):
            end_dt = end_dt.split('.')[0] + 'Z'

        normalized_events.append({
            "summary": event.get("subject", "Untitled Event"),
            "start_time": start_dt,
            "end_time": end_dt,
            "source": "microsoft",
            "is_organizer": event.get("isOrganizer", False),
            "raw_event": event  # Keep original for debugging
        })

    print(f"[Microsoft] Fetched {len(normalized_events)} events for user {user_id}")
    return normalized_events


async def refresh_microsoft_token(user_id: str, refresh_token: str) -> str:
    """
    Refresh expired Microsoft access token using refresh token.

    Args:
        user_id: CelestiOS user ID
        refresh_token: Microsoft refresh token

    Returns:
        New access token

    Raises:
        httpx.HTTPStatusError: If refresh fails
    """
    url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    data = {
        "client_id": settings.MICROSOFT_CLIENT_ID,
        "client_secret": settings.MICROSOFT_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "scope": settings.MICROSOFT_SCOPES
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, data=data)
            response.raise_for_status()
            token_data = response.json()
    except httpx.HTTPStatusError as e:
        print(f"[Microsoft] Token refresh failed: {e.response.status_code} - {e.response.text}")
        raise

    # Calculate expiration timestamp
    expires_at = int(time.time()) + token_data["expires_in"]

    # Update stored token
    storage.update_microsoft_token(
        user_id=user_id,
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token", refresh_token),  # May return new refresh token
        expires_at=expires_at,
        scope=token_data.get("scope", settings.MICROSOFT_SCOPES)
    )

    print(f"[Microsoft] Token refreshed successfully for user {user_id}")
    return token_data["access_token"]


async def get_today_work_calendar_events(user_id: str, user_timezone: Optional[str] = None) -> List[Dict]:
    """
    Convenience method to fetch today's work calendar events.

    Args:
        user_id: CelestiOS user ID
        user_timezone: User's timezone (e.g., "America/Los_Angeles"). If None, uses UTC.

    Returns:
        List of normalized event dictionaries
    """
    # Get today's date range in UTC
    if user_timezone:
        from datetime import datetime
        import pytz

        # Get today in user's timezone
        tz = pytz.timezone(user_timezone)
        now = datetime.now(tz)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=999999)

        # Convert to UTC for API call
        start_dt = start_of_day.astimezone(pytz.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_dt = end_of_day.astimezone(pytz.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        # Use UTC
        now = datetime.now(timezone.utc)
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_dt = now.replace(hour=23, minute=59, second=59, microsecond=999999).strftime("%Y-%m-%dT%H:%M:%SZ")

    return await get_calendar_events(user_id, start_dt, end_dt)


def is_microsoft_connected(user_id: str) -> bool:
    """
    Check if user has connected their Microsoft work calendar.

    Args:
        user_id: CelestiOS user ID

    Returns:
        True if Microsoft calendar is connected, False otherwise
    """
    try:
        token_data = storage.get_microsoft_token(user_id)
        return token_data is not None
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════
# CALENDAR WRITE OPERATIONS (Apply Changes)
# ═══════════════════════════════════════════════════════════════════════

async def create_calendar_event(
    user_id: str,
    subject: str,
    start_datetime: str,
    end_datetime: str,
    description: Optional[str] = None,
    location: Optional[str] = None,
    user_timezone: str = "UTC"
) -> Dict:
    """
    Create a new calendar event via MS Graph API.

    Args:
        user_id: CelestiOS user ID
        subject: Event title
        start_datetime: ISO 8601 datetime string
        end_datetime: ISO 8601 datetime string
        description: Optional event description
        location: Optional location
        user_timezone: User's timezone

    Returns:
        Created event object

    Raises:
        ValueError: If Microsoft calendar not connected
        httpx.HTTPStatusError: If API request fails
    """
    # Get Microsoft access token
    token_data = storage.get_microsoft_token(user_id)
    if not token_data:
        raise ValueError("Microsoft calendar not connected")

    access_token = token_data["access_token"]
    expires_at = token_data["expires_at"]

    # Check if token is expired
    if time.time() >= (expires_at - 300):
        print(f"[Microsoft] Token expired, refreshing...")
        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            raise ValueError("No refresh token available")
        access_token = await refresh_microsoft_token(user_id, refresh_token)

    # Build event payload
    event_payload = {
        "subject": subject,
        "start": {
            "dateTime": start_datetime,
            "timeZone": user_timezone
        },
        "end": {
            "dateTime": end_datetime,
            "timeZone": user_timezone
        },
        "showAs": "busy",
        "isReminderOn": True,
        "reminderMinutesBeforeStart": 15
    }

    if description:
        event_payload["body"] = {
            "contentType": "text",
            "content": description
        }

    if location:
        event_payload["location"] = {
            "displayName": location
        }

    # Create event via API
    url = "https://graph.microsoft.com/v1.0/me/events"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=event_payload, headers=headers)
            response.raise_for_status()
            created_event = response.json()

        print(f"[Microsoft] Created event: {subject} at {start_datetime}")
        return created_event

    except httpx.HTTPStatusError as e:
        print(f"[Microsoft] Failed to create event: {e.response.status_code} - {e.response.text}")
        raise


async def update_calendar_event(
    user_id: str,
    event_id: str,
    start_datetime: Optional[str] = None,
    end_datetime: Optional[str] = None,
    subject: Optional[str] = None,
    description: Optional[str] = None,
    user_timezone: str = "UTC"
) -> Dict:
    """
    Update an existing calendar event (e.g., move to different time).

    Args:
        user_id: CelestiOS user ID
        event_id: Microsoft event ID to update
        start_datetime: New start time (ISO 8601)
        end_datetime: New end time (ISO 8601)
        subject: New subject (optional)
        description: New description (optional)
        user_timezone: User's timezone

    Returns:
        Updated event object
    """
    token_data = storage.get_microsoft_token(user_id)
    if not token_data:
        raise ValueError("Microsoft calendar not connected")

    access_token = token_data["access_token"]
    expires_at = token_data["expires_at"]

    if time.time() >= (expires_at - 300):
        refresh_token = token_data.get("refresh_token")
        access_token = await refresh_microsoft_token(user_id, refresh_token)

    # Build update payload
    update_payload = {}

    if start_datetime:
        update_payload["start"] = {
            "dateTime": start_datetime,
            "timeZone": user_timezone
        }

    if end_datetime:
        update_payload["end"] = {
            "dateTime": end_datetime,
            "timeZone": user_timezone
        }

    if subject:
        update_payload["subject"] = subject

    if description:
        update_payload["body"] = {
            "contentType": "Text",
            "content": description
        }

    # Update event via API
    url = f"https://graph.microsoft.com/v1.0/me/events/{event_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.patch(url, json=update_payload, headers=headers)
            response.raise_for_status()
            updated_event = response.json()

        print(f"[Microsoft] Updated event {event_id}")
        return updated_event

    except httpx.HTTPStatusError as e:
        print(f"[Microsoft] Failed to update event: {e.response.status_code} - {e.response.text}")
        raise


async def delete_calendar_event(user_id: str, event_id: str) -> bool:
    """
    Delete a calendar event via MS Graph API.

    Args:
        user_id: CelestiOS user ID
        event_id: Microsoft event ID to delete

    Returns:
        True if deleted successfully
    """
    token_data = storage.get_microsoft_token(user_id)
    if not token_data:
        raise ValueError("Microsoft calendar not connected")

    access_token = token_data["access_token"]
    expires_at = token_data["expires_at"]

    if time.time() >= (expires_at - 300):
        refresh_token = token_data.get("refresh_token")
        access_token = await refresh_microsoft_token(user_id, refresh_token)

    url = f"https://graph.microsoft.com/v1.0/me/events/{event_id}"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.delete(url, headers=headers)
            response.raise_for_status()

        print(f"[Microsoft] Deleted event {event_id}")
        return True

    except httpx.HTTPStatusError as e:
        print(f"[Microsoft] Failed to delete event: {e.response.status_code} - {e.response.text}")
        raise


async def apply_burnout_changes(
    user_id: str,
    focus_block: Dict,
    suggested_changes: Optional[List[Dict]] = None,
    user_timezone: str = "UTC"
) -> Dict:
    """
    Apply burnout detection changes to calendar.
    1. Moves conflicting meetings to later times
    2. Creates focus block event in Microsoft calendar

    Args:
        user_id: CelestiOS user ID
        focus_block: Focus block dict from burnout detection
            {
                "start_time": ISO datetime,
                "end_time": ISO datetime,
                "duration_minutes": int,
                "time_slot": str,
                "reasoning": str
            }
        suggested_changes: List of meetings to move with reasons
            [
                {
                    "meeting": str,
                    "suggestion": str,
                    "reason": str,
                    "move_score": int
                }
            ]
        user_timezone: User's timezone

    Returns:
        {
            "success": bool,
            "focus_block_created": Dict (event object),
            "meetings_moved": List[Dict],
            "errors": List[str]
        }
    """
    errors = []
    focus_block_created = None
    meetings_moved = []

    # Step 1: Move conflicting meetings to later times
    if suggested_changes and len(suggested_changes) > 0:
        print(f"[Microsoft] Moving {len(suggested_changes)} conflicting meetings")

        # Get all today's events to find event IDs
        try:
            from datetime import datetime
            import pytz
            tz = pytz.timezone(user_timezone)
            today = datetime.now(tz).date()
            start_of_day = tz.localize(datetime.combine(today, datetime.min.time()))
            end_of_day = tz.localize(datetime.combine(today, datetime.max.time()))

            all_events = await get_calendar_events(
                user_id,
                start_of_day.strftime("%Y-%m-%dT%H:%M:%SZ"),
                end_of_day.strftime("%Y-%m-%dT%H:%M:%SZ")
            )

            # Build event lookup by title
            event_lookup = {}
            for evt in all_events:
                title = evt.get("summary", "").strip().lower()
                event_id = evt.get("raw_event", {}).get("id")
                if event_id:
                    event_lookup[title] = {
                        "id": event_id,
                        "start": evt.get("start_time"),
                        "end": evt.get("end_time")
                    }

            print(f"[Microsoft] Event lookup built with {len(event_lookup)} events:")
            for title in event_lookup.keys():
                print(f"  - '{title}'")

            for change in suggested_changes:
                meeting_title = change["meeting"].strip().lower()
                reason = change["reason"]
                suggestion = change.get("suggestion", "")

                # Parse exact time from suggestion (e.g., "Today 3:00 PM", "Monday 9:00 AM")
                new_start = None
                try:
                    if "Today" in suggestion:
                        # Extract time like "3:00 PM" from "Today 3:00 PM"
                        time_str = suggestion.replace("Today", "").strip()
                        parsed_time = datetime.strptime(time_str, "%I:%M %p").time()
                        new_start = tz.localize(datetime.combine(today, parsed_time))
                        print(f"[Microsoft] Parsed 'Today' suggestion '{suggestion}' -> {new_start.strftime('%I:%M %p')}")
                    else:
                        # Handle day names like "Monday 9:00 AM", "Tuesday 10:30 AM"
                        # Extract day name and time
                        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                        for day_name in day_names:
                            if day_name in suggestion:
                                time_str = suggestion.replace(day_name, "").strip()
                                parsed_time = datetime.strptime(time_str, "%I:%M %p").time()

                                # Calculate which date this day name refers to
                                current_weekday = today.weekday()  # 0=Monday, 6=Sunday
                                target_weekday = day_names.index(day_name)

                                # Calculate days ahead
                                days_ahead = target_weekday - current_weekday
                                if days_ahead <= 0:  # If it's today or earlier in week, move to next week
                                    days_ahead += 7

                                target_date = today + timedelta(days=days_ahead)
                                new_start = tz.localize(datetime.combine(target_date, parsed_time))
                                print(f"[Microsoft] Parsed '{day_name}' suggestion '{suggestion}' -> {new_start.strftime('%Y-%m-%d %I:%M %p')}")
                                break
                except Exception as e:
                    print(f"[Microsoft] Failed to parse suggestion '{suggestion}': {e}")

                # Fallback to 3 PM today if parsing failed
                if new_start is None:
                    new_start = tz.localize(datetime.combine(today, datetime.min.time().replace(hour=15, minute=0)))
                    print(f"[Microsoft] Using fallback time: 3:00 PM")

                new_start_str = new_start.strftime("%I:%M %p")

                # Check if this is a Microsoft event (can actually move it)
                if meeting_title in event_lookup:
                    event_info = event_lookup[meeting_title]
                    event_id = event_info["id"]

                    # Calculate duration
                    original_start = datetime.fromisoformat(event_info["start"].replace('Z', '+00:00'))
                    original_end = datetime.fromisoformat(event_info["end"].replace('Z', '+00:00'))
                    duration = original_end - original_start
                    new_end = new_start + duration

                    try:
                        # Format original time for note
                        original_time_str = original_start.strftime('%I:%M %p')

                        # Actually move the Microsoft event via API
                        await update_calendar_event(
                            user_id=user_id,
                            event_id=event_id,
                            start_datetime=new_start.isoformat(),
                            end_datetime=new_end.isoformat(),
                            description=f"Originally scheduled at {original_time_str}\n\nMoved by Celesti to optimize your day",
                            user_timezone=user_timezone
                        )

                        meetings_moved.append({
                            "meeting": change["meeting"],
                            "moved_to": new_start_str,
                            "reason": reason,
                            "source": "microsoft",
                            "actually_moved": True
                        })

                        print(f"[Microsoft] Moved '{change['meeting']}' to {new_start_str} - {reason}")

                    except Exception as e:
                        error_msg = f"Failed to move '{change['meeting']}': {str(e)}"
                        errors.append(error_msg)
                        print(f"[Microsoft] {error_msg}")

                else:
                    # Google event - can't actually move it, but add to list for UI simulation
                    meetings_moved.append({
                        "meeting": change["meeting"],
                        "moved_to": new_start_str,
                        "reason": reason,
                        "source": "google",
                        "actually_moved": False
                    })
                    print(f"[Microsoft] Simulated move for Google event '{change['meeting']}' to {new_start_str}")

        except Exception as e:
            error_msg = f"Failed to fetch events for moving: {str(e)}"
            errors.append(error_msg)
            print(f"[Microsoft] {error_msg}")

    # Step 2: Create focus block event
    try:
        focus_block_created = await create_calendar_event(
            user_id=user_id,
            subject="Focus Block - Priority Work",
            start_datetime=focus_block["start_time"],
            end_datetime=focus_block["end_time"],
            description=f"Protected time for focused work.\n\nCreated by Celesti",
            user_timezone=user_timezone
        )
        print(f"[Microsoft] Focus block created successfully at {focus_block['time_slot']}")

    except Exception as e:
        error_msg = f"Failed to create focus block: {str(e)}"
        errors.append(error_msg)
        print(f"[Microsoft] {error_msg}")

    return {
        "success": len(errors) == 0,
        "focus_block_created": focus_block_created,
        "meetings_moved": meetings_moved,
        "errors": errors
    }
