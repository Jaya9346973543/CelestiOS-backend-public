from fastapi import APIRouter, HTTPException
import httpx
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo
from core.config import settings
from db import storage
from services.microsoft_client import get_today_work_calendar_events, is_microsoft_connected

router = APIRouter(prefix="/calendar", tags=["Calendar Synchronization"])


def _day_range(date_str: Optional[str], tz_str: Optional[str] = None) -> tuple[str, str]:
    """
    Build start/end ISO timestamps for the given date in the user's timezone.
    Falls back to UTC if no timezone provided.
    """
    # Resolve timezone
    user_tz = timezone.utc
    if tz_str:
        try:
            user_tz = ZoneInfo(tz_str)
        except Exception:
            user_tz = timezone.utc

    if date_str:
        try:
            day = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid date format") from exc
    else:
        day = datetime.now(user_tz)

    # Midnight in user's timezone
    start_local = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)

    # Attach timezone and convert to UTC ISO for Google API
    start_aware = start_local.replace(tzinfo=user_tz)
    end_aware = end_local.replace(tzinfo=user_tz)

    return start_aware.isoformat(), end_aware.isoformat()


def _normalize_google_time(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if "T" in value:
        return value
    return f"{value}T00:00:00Z"


def _get_token_row(user_id: str) -> Dict[str, Any]:
    token_row = storage.get_token(user_id)
    if not token_row:
        raise HTTPException(status_code=404, detail="No token found for user")
    return token_row


async def _refresh_access_token(refresh_token: str) -> Dict[str, Any]:
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")

    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, data=data)
        token_data = response.json()
        if response.status_code != 200 or "error" in token_data:
            raise HTTPException(status_code=401, detail="Failed to refresh token")
    return token_data


async def _get_access_token(user_id: str) -> str:
    token_row = _get_token_row(user_id)
    access_token = token_row.get("access_token")
    if not access_token:
        raise HTTPException(status_code=401, detail="Missing access token")

    expires_at = token_row.get("expires_at")
    if expires_at:
        try:
            expires_at_int = int(expires_at)
        except (TypeError, ValueError):
            expires_at_int = 0

        if expires_at_int and expires_at_int <= int(time.time()) + 30:
            refresh_token = token_row.get("refresh_token")
            if not refresh_token:
                raise HTTPException(status_code=401, detail="Token expired")
            token_data = await _refresh_access_token(refresh_token)
            access_token = token_data.get("access_token")
            expires_in = int(token_data.get("expires_in", 0))
            new_expires_at = int(time.time()) + expires_in if expires_in else 0
            storage.upsert_token(
                {
                    "user_id": user_id,
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": new_expires_at,
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            )

    return access_token


async def _fetch_google_events(
    access_token: str,
    time_min: str,
    time_max: str,
) -> List[Dict[str, Any]]:
    calendar_url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "timeMin": time_min,
        "timeMax": time_max,
        "maxResults": 250,
        "singleEvents": "true",
        "orderBy": "startTime",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(calendar_url, headers=headers, params=params)
        if response.status_code != 200:
            error_detail = f"Failed to fetch calendar events"
            try:
                error_body = response.json()
                error_msg = error_body.get("error", {}).get("message", str(error_body))
                error_detail = f"Google Calendar API error ({response.status_code}): {error_msg}"
                print(f"[Calendar] Google API error: {response.status_code} - {error_body}")
            except Exception:
                error_detail = f"Google Calendar API error ({response.status_code}): {response.text[:200]}"
                print(f"[Calendar] Google API error: {response.status_code} - {response.text[:500]}")
            raise HTTPException(status_code=400, detail=error_detail)
        return response.json().get("items", [])


def _build_event_payload(user_id: str, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    start_raw = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
    end_raw = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")
    start_time = _normalize_google_time(start_raw)
    end_time = _normalize_google_time(end_raw)
    if not start_time or not end_time:
        return None
    return {
        "user_id": user_id,
        "google_event_id": event.get("id"),
        "summary": event.get("summary") or "Untitled",
        "description": event.get("description"),
        "start_time": start_time,
        "end_time": end_time,
        "status": event.get("status") or "confirmed",
    }


def _format_response_event(event_payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": event_payload.get("google_event_id"),
        "summary": event_payload.get("summary"),
        "start": event_payload.get("start_time"),
        "end": event_payload.get("end_time"),
        "status": event_payload.get("status"),
    }


@router.post("/sync")
async def sync_calendar(user_id: str, date: Optional[str] = None, tz: Optional[str] = None):
    """
    Sync events from Google Calendar for the given user.
    """
    time_min, time_max = _day_range(date, tz)
    access_token = await _get_access_token(user_id)
    events = await _fetch_google_events(access_token, time_min, time_max)
    payloads = []
    for event in events:
        payload = _build_event_payload(user_id, event)
        if payload:
            payloads.append(payload)

    if payloads:
        storage.upsert_events(payloads)

    return {
        "message": "Calendar synced successfully",
        "events_synced": len(payloads),
    }


@router.get("/events")
async def get_events(user_id: str, date: str, tz: Optional[str] = None):
    """Return events for a given day in the user's timezone (both Google and Microsoft)."""
    time_min, time_max = _day_range(date, tz)

    # Fetch Google events
    google_events = []
    try:
        access_token = await _get_access_token(user_id)
        google_events = await _fetch_google_events(access_token, time_min, time_max)
        payloads = []
        response_events = []
        for event in google_events:
            payload = _build_event_payload(user_id, event)
            if payload:
                payloads.append(payload)
                response_events.append(_format_response_event(payload))

        if payloads:
            storage.upsert_events(payloads)
    except HTTPException:
        # Fall back to cached Google events
        rows = storage.get_events_between(user_id, time_min, time_max)
        response_events = [
            {
                "id": row.get("google_event_id") or row.get("id"),
                "summary": row.get("summary"),
                "start": row.get("start_time"),
                "end": row.get("end_time"),
                "status": row.get("status"),
            }
            for row in rows
        ]

    # Fetch Microsoft events (if connected)
    microsoft_events = []
    if is_microsoft_connected(user_id):
        try:
            ms_events = await get_today_work_calendar_events(user_id, tz)
            print(f"[Calendar] Fetched {len(ms_events)} Microsoft events for user {user_id}")

            # Convert Microsoft events to response format
            for evt in ms_events:
                microsoft_events.append({
                    "id": f"ms_{evt['start_time']}",  # Generate unique ID
                    "summary": evt["summary"],
                    "start": evt["start_time"],
                    "end": evt["end_time"],
                    "status": "confirmed",
                    "source": "microsoft",
                    "is_organizer": evt.get("is_organizer", False)
                })
        except Exception as e:
            print(f"[Calendar] Failed to fetch Microsoft events: {e}")

    # Merge Google and Microsoft events
    all_events = response_events + microsoft_events
    print(f"[Calendar] Total events: {len(all_events)} (Google: {len(response_events)}, Microsoft: {len(microsoft_events)})")

    return all_events


@router.post("/disconnect")
async def disconnect_calendar(user_id: str):
    """
    Disconnect Google Calendar by revoking OAuth tokens and clearing from database.
    """
    try:
        # Get token from database
        token_row = storage.get_token(user_id)
        if not token_row:
            return {
                "message": "No calendar connection found",
                "success": True,
            }

        access_token = token_row.get("access_token")

        # Revoke token with Google if we have one
        if access_token:
            revoke_url = f"https://oauth2.googleapis.com/revoke?token={access_token}"
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.post(revoke_url)
                    if response.status_code == 200:
                        print(f"[Calendar] Token revoked with Google for user {user_id}")
                    else:
                        print(f"[Calendar] Token revoke returned {response.status_code} (may already be invalid)")
                except Exception as e:
                    print(f"[Calendar] Failed to revoke token with Google: {e}")
                    # Continue anyway to delete from our database

        # Delete token from database
        storage.delete_token(user_id)
        print(f"[Calendar] Token deleted from database for user {user_id}")

        # Note: calendar_connected flag is computed dynamically in /auth/me
        # by checking if refresh_token exists, so no need to update user table

        return {
            "message": "Calendar disconnected successfully",
            "success": True,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to disconnect calendar: {exc}") from exc
