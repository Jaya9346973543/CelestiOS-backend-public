from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from core.config import settings
from db.supabase_client import supabase_client
from db import local_db

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List


def _use_supabase() -> bool:
    return bool(settings.SUPABASE_URL and settings.SUPABASE_KEY and supabase_client is not None)


def _fallback_enabled() -> bool:
    return bool(settings.ENABLE_LOCAL_FALLBACK)


def _supabase_error_detail(error: object) -> str:
    message = getattr(error, "message", None)
    if message:
        return str(message)
    return str(error)


# ─── Users ───────────────────────────────────────────────────────────

def upsert_user(user_payload: Dict[str, Any]) -> None:
    if _use_supabase():
        try:
            result = supabase_client.table(settings.SUPABASE_USERS_TABLE).upsert(
                user_payload,
                on_conflict="google_id",
            ).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return
        except Exception as exc:
            if _fallback_enabled():
                local_db.upsert_user(user_payload)
                return
            raise exc
    local_db.upsert_user(user_payload)


def get_user(google_id: str) -> Optional[Dict[str, Any]]:
    if _use_supabase():
        try:
            result = supabase_client.table(settings.SUPABASE_USERS_TABLE).select(
                "*"
            ).eq("google_id", google_id).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            if getattr(result, "data", None):
                return result.data[0]
            return None
        except Exception as exc:
            if _fallback_enabled():
                return local_db.get_user(google_id)
            raise exc
    return local_db.get_user(google_id)


def delete_user(google_id: str) -> None:
    """Delete a user by google_id. Used when merging manual + Google accounts."""
    # First, delete all password reset tokens for this user
    try:
        delete_reset_tokens_by_user(google_id)
    except Exception:
        pass  # Continue even if token cleanup fails

    if _use_supabase():
        try:
            result = supabase_client.table(settings.SUPABASE_USERS_TABLE).delete().eq(
                "google_id", google_id
            ).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return
        except Exception as exc:
            if _fallback_enabled():
                local_db.delete_user(google_id)
                return
            raise exc
    local_db.delete_user(google_id)


def update_user_profile(google_id: str, update_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if _use_supabase():
        try:
            result = supabase_client.table(settings.SUPABASE_USERS_TABLE).update(
                update_data
            ).eq("google_id", google_id).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            if getattr(result, "data", None):
                return result.data[0]
            return None
        except Exception as exc:
            if _fallback_enabled():
                return local_db.update_user_profile(google_id, update_data)
            raise exc
    return local_db.update_user_profile(google_id, update_data)


def update_email_preferences(google_id: str, enabled: bool) -> None:
    """Update email notification preferences for a user."""
    if _use_supabase():
        try:
            result = supabase_client.table(settings.SUPABASE_USERS_TABLE).update(
                {"email_notifications_enabled": enabled}
            ).eq("google_id", google_id).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return
        except Exception as exc:
            if _fallback_enabled():
                local_db.update_email_preferences(google_id, enabled)
                return
            raise exc
    local_db.update_email_preferences(google_id, enabled)


# ─── Tokens ──────────────────────────────────────────────────────────

def get_token(user_id: str) -> Optional[Dict[str, Any]]:
    if _use_supabase():
        try:
            result = supabase_client.table(settings.SUPABASE_TOKENS_TABLE).select(
                "*"
            ).eq("user_id", user_id).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            if getattr(result, "data", None):
                return result.data[0]
            return None
        except Exception as exc:
            if _fallback_enabled():
                return local_db.get_token(user_id)
            raise exc
    return local_db.get_token(user_id)


def upsert_token(token_payload: Dict[str, Any]) -> None:
    if _use_supabase():
        try:
            result = supabase_client.table(settings.SUPABASE_TOKENS_TABLE).upsert(
                token_payload,
                on_conflict="user_id",
            ).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return
        except Exception as exc:
            if _fallback_enabled():
                local_db.upsert_token(token_payload)
                return
            raise exc
    local_db.upsert_token(token_payload)


def delete_token(user_id: str) -> None:
    """Delete OAuth token for a user."""
    if _use_supabase():
        try:
            result = supabase_client.table(settings.SUPABASE_TOKENS_TABLE).delete().eq(
                "user_id", user_id
            ).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return
        except Exception as exc:
            if _fallback_enabled():
                local_db.delete_token(user_id)
                return
            raise exc
    local_db.delete_token(user_id)


# ─── Events ──────────────────────────────────────────────────────────

def upsert_events(events_payload: Iterable[Dict[str, Any]]) -> None:
    payloads = list(events_payload)
    if _use_supabase():
        try:
            result = supabase_client.table(settings.SUPABASE_EVENTS_TABLE).upsert(
                payloads,
                on_conflict="google_event_id",
            ).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return
        except Exception as exc:
            if _fallback_enabled():
                local_db.upsert_events(payloads)
                return
            raise exc
    local_db.upsert_events(payloads)


def get_events_between(user_id: str, start_time: str, end_time: str) -> List[Dict[str, Any]]:
    if _use_supabase():
        try:
            result = supabase_client.table(settings.SUPABASE_EVENTS_TABLE).select(
                "*"
            ).eq("user_id", user_id).gte("start_time", start_time).lt(
                "start_time", end_time
            ).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return getattr(result, "data", []) or []
        except Exception as exc:
            if _fallback_enabled():
                return local_db.get_events_between(user_id, start_time, end_time)
            raise exc
    return local_db.get_events_between(user_id, start_time, end_time)


# ─── Feedback ────────────────────────────────────────────────────────

def insert_feedback(feedback_payload: Dict[str, Any]) -> None:
    if _use_supabase():
        try:
            result = supabase_client.table("feedback").insert(
                feedback_payload
            ).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return
        except Exception as exc:
            if _fallback_enabled():
                local_db.insert_feedback(feedback_payload)
                return
            raise exc
    local_db.insert_feedback(feedback_payload)


def get_feedback_by_user(user_id: str, limit: int = 30) -> List[Dict[str, Any]]:
    if _use_supabase():
        try:
            result = supabase_client.table("feedback").select(
                "*"
            ).eq("user_id", user_id).order(
                "created_at", desc=True
            ).limit(limit).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return getattr(result, "data", []) or []
        except Exception as exc:
            if _fallback_enabled():
                return local_db.get_feedback_by_user(user_id, limit)
            raise exc
    return local_db.get_feedback_by_user(user_id, limit)



def get_all_users() -> List[Dict[str, Any]]:
    """Fetch all users from the database."""
    if _use_supabase():
        try:
            result = supabase_client.table("users").select("*").execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return getattr(result, "data", []) or []
        except Exception as exc:
            if _fallback_enabled():
                return local_db.get_all_users()
            raise exc
    return local_db.get_all_users()


def get_today_events(user_id: str, user_timezone=None) -> List[Dict[str, Any]]:
    """Fetch today's calendar events for a user in their timezone."""
    # Use user's timezone if provided, otherwise UTC
    if user_timezone:
        now = datetime.now(user_timezone)
    else:
        now = datetime.now(timezone.utc)

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()

    if _use_supabase():
        try:
            result = (
                supabase_client.table("calendar_events")
                .select("*")
                .eq("user_id", user_id)
                .gte("start_time", today_start)
                .lte("start_time", today_end)
                .order("start_time")
                .execute()
            )
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return getattr(result, "data", []) or []
        except Exception:
            return []
    return []


# ─── Password Management ─────────────────────────────────────────────

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Get user by email address. If duplicates exist, prefer the one with password_hash."""
    if _use_supabase():
        try:
            result = supabase_client.table(settings.SUPABASE_USERS_TABLE).select("*").eq("email", email).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            data = getattr(result, "data", [])

            if not data:
                return None

            # If multiple records exist, prefer the one with password_hash
            # (This handles legacy duplicates before the merge fix was deployed)
            if len(data) > 1:
                for user in data:
                    if user.get("password_hash"):
                        return user

            return data[0]
        except Exception as exc:
            if _fallback_enabled():
                return local_db.get_user_by_email(email)
            raise exc
    return local_db.get_user_by_email(email)


def update_user_password(user_id: str, password_hash: str) -> None:
    """Update user's password hash."""
    if _use_supabase():
        try:
            result = supabase_client.table(settings.SUPABASE_USERS_TABLE).update(
                {"password_hash": password_hash}
            ).eq("google_id", user_id).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return
        except Exception as exc:
            if _fallback_enabled():
                local_db.update_user_password(user_id, password_hash)
                return
            raise exc
    local_db.update_user_password(user_id, password_hash)


def create_password_reset_token(user_id: str, email: str, token: str, expires_at: str) -> None:
    """Create a password reset token."""
    if _use_supabase():
        try:
            payload = {
                "user_id": user_id,
                "email": email,
                "token": token,
                "token_type": "password_reset",
                "expires_at": expires_at,
                "used": False
            }
            result = supabase_client.table("password_reset_tokens").insert(payload).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return
        except Exception as exc:
            if _fallback_enabled():
                local_db.create_password_reset_token(user_id, email, token, expires_at)
                return
            raise exc
    local_db.create_password_reset_token(user_id, email, token, expires_at)


def get_password_reset_token(token: str) -> Optional[Dict[str, Any]]:
    """Get password reset token details."""
    if _use_supabase():
        try:
            result = supabase_client.table("password_reset_tokens").select("*").eq("token", token).eq("token_type", "password_reset").eq("used", False).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            data = getattr(result, "data", [])
            return data[0] if data else None
        except Exception as exc:
            if _fallback_enabled():
                return local_db.get_password_reset_token(token)
            raise exc
    return local_db.get_password_reset_token(token)


def mark_reset_token_used(token: str) -> None:
    """Mark a password reset token as used."""
    if _use_supabase():
        try:
            result = supabase_client.table("password_reset_tokens").update(
                {"used": True}
            ).eq("token", token).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return
        except Exception as exc:
            if _fallback_enabled():
                local_db.mark_reset_token_used(token)
                return
            raise exc
    local_db.mark_reset_token_used(token)


def delete_reset_tokens_by_user(user_id: str) -> None:
    """Delete all password reset tokens for a user (called when account is deleted)."""
    if _use_supabase():
        try:
            result = supabase_client.table("password_reset_tokens").delete().eq("user_id", user_id).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return
        except Exception as exc:
            if _fallback_enabled():
                local_db.delete_reset_tokens_by_user(user_id)
                return
            raise exc
    local_db.delete_reset_tokens_by_user(user_id)


# ─── Email Auth Tokens ───────────────────────────────────────────────

def create_email_auth_token(user_id: str, token: str, expires_at: str) -> None:
    """Create an email authentication token for one-click login from emails."""
    if _use_supabase():
        try:
            payload = {
                "user_id": user_id,
                "email": user_id,  # Placeholder, not used for email auth
                "token": token,
                "token_type": "email_auth",
                "expires_at": expires_at,
                "used": False
            }
            result = supabase_client.table("password_reset_tokens").insert(payload).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return
        except Exception as exc:
            if _fallback_enabled():
                local_db.create_email_auth_token(user_id, token, expires_at)
                return
            raise exc
    local_db.create_email_auth_token(user_id, token, expires_at)


def get_email_auth_token(token: str) -> Optional[Dict[str, Any]]:
    """Get email auth token details."""
    if _use_supabase():
        try:
            result = supabase_client.table("password_reset_tokens").select("*").eq("token", token).eq("token_type", "email_auth").eq("used", False).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            data = getattr(result, "data", [])
            return data[0] if data else None
        except Exception as exc:
            if _fallback_enabled():
                return local_db.get_email_auth_token(token)
            raise exc
    return local_db.get_email_auth_token(token)


def mark_email_auth_token_used(token: str) -> None:
    """Mark an email auth token as used."""
    if _use_supabase():
        try:
            result = supabase_client.table("password_reset_tokens").update(
                {"used": True}
            ).eq("token", token).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return
        except Exception as exc:
            if _fallback_enabled():
                local_db.mark_email_auth_token_used(token)
                return
            raise exc
    local_db.mark_email_auth_token_used(token)


# ─── Unsubscribe Tokens ──────────────────────────────────────────────

def create_unsubscribe_token(user_id: str, token: str, expires_at: str) -> None:
    """Create an unsubscribe token for email preference management."""
    if _use_supabase():
        try:
            payload = {
                "user_id": user_id,
                "email": user_id,  # Placeholder, not used for unsubscribe
                "token": token,
                "token_type": "unsubscribe",
                "expires_at": expires_at,
                "used": False
            }
            result = supabase_client.table("password_reset_tokens").insert(payload).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return
        except Exception as exc:
            if _fallback_enabled():
                local_db.create_unsubscribe_token(user_id, token, expires_at)
                return
            raise exc
    local_db.create_unsubscribe_token(user_id, token, expires_at)


def get_unsubscribe_token(token: str) -> Optional[Dict[str, Any]]:
    """Get unsubscribe token details."""
    if _use_supabase():
        try:
            result = supabase_client.table("password_reset_tokens").select("*").eq("token", token).eq("token_type", "unsubscribe").eq("used", False).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            data = getattr(result, "data", [])
            return data[0] if data else None
        except Exception as exc:
            if _fallback_enabled():
                return local_db.get_unsubscribe_token(token)
            raise exc
    return local_db.get_unsubscribe_token(token)


def mark_unsubscribe_token_used(token: str) -> None:
    """Mark an unsubscribe token as used."""
    if _use_supabase():
        try:
            result = supabase_client.table("password_reset_tokens").update(
                {"used": True}
            ).eq("token", token).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return
        except Exception as exc:
            if _fallback_enabled():
                local_db.mark_unsubscribe_token_used(token)
                return
            raise exc
    local_db.mark_unsubscribe_token_used(token)


# ─── Check-ins ───────────────────────────────────────────────────────

def upsert_checkin(checkin_payload: Dict[str, Any]) -> None:
    """Save or update daily check-in data."""
    if _use_supabase():
        try:
            result = supabase_client.table("checkins").upsert(
                checkin_payload,
                on_conflict="user_id,date",
            ).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return
        except Exception as exc:
            if _fallback_enabled():
                local_db.upsert_checkin(checkin_payload)
                return
            raise exc
    local_db.upsert_checkin(checkin_payload)


def get_checkin(user_id: str, date: str) -> Optional[Dict[str, Any]]:
    """Get check-in data for a specific user and date."""
    if _use_supabase():
        try:
            result = supabase_client.table("checkins").select("*").eq(
                "user_id", user_id
            ).eq("date", date).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            data = getattr(result, "data", [])
            return data[0] if data else None
        except Exception as exc:
            if _fallback_enabled():
                return local_db.get_checkin(user_id, date)
            raise exc
    return local_db.get_checkin(user_id, date)


# ─── Insights Cache ──────────────────────────────────────────────────

def cache_insights(user_id: str, date: str, detailed: str, quick: str, day_type: str) -> None:
    """Cache AI-generated insights to avoid duplicate OpenAI calls."""
    if _use_supabase():
        try:
            payload = {
                "user_id": user_id,
                "date": date,
                "detailed_insights": detailed,
                "quick_insights": quick,
                "day_type": day_type
            }
            result = supabase_client.table("insights_cache").upsert(
                payload,
                on_conflict="user_id,date"
            ).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            return
        except Exception as exc:
            if _fallback_enabled():
                local_db.cache_insights(user_id, date, detailed, quick, day_type)
                return
            raise exc
    local_db.cache_insights(user_id, date, detailed, quick, day_type)


def get_cached_insights(user_id: str, date: str, max_age_hours: int = 2) -> Optional[Dict[str, Any]]:
    """Get cached insights if they exist and are fresh (< max_age_hours old)."""
    if _use_supabase():
        try:
            result = supabase_client.table("insights_cache").select("*").eq(
                "user_id", user_id
            ).eq("date", date).execute()
            if getattr(result, "error", None):
                raise RuntimeError(_supabase_error_detail(result.error))
            data = getattr(result, "data", [])
            if not data:
                return None

            cache = data[0]
            # Check if cache is fresh
            from datetime import datetime, timedelta, timezone
            cached_at = datetime.fromisoformat(cache["cached_at"].replace("Z", "+00:00"))
            age = datetime.now(timezone.utc) - cached_at

            if age.total_seconds() > max_age_hours * 3600:
                return None  # Cache expired

            return cache
        except Exception as exc:
            if _fallback_enabled():
                return local_db.get_cached_insights(user_id, date, max_age_hours)
            raise exc
    return local_db.get_cached_insights(user_id, date, max_age_hours)


# ============================================
# Health Integration Functions
# ============================================

def save_health_connection(connection_payload: Dict[str, Any]) -> None:
    """Save or update a health device connection (OAuth tokens)."""
    if supabase_client:
        try:
            supabase_client.table("health_connections").upsert(
                connection_payload,
                on_conflict="user_id,provider"
            ).execute()
        except Exception as exc:
            if _fallback_enabled():
                local_db.save_health_connection(connection_payload)
            else:
                raise exc
    else:
        local_db.save_health_connection(connection_payload)


def get_health_connection(user_id: str, provider: str) -> Optional[Dict[str, Any]]:
    """Get health device connection for a specific provider."""
    if supabase_client:
        try:
            response = supabase_client.table("health_connections").select("*").eq(
                "user_id", user_id
            ).eq("provider", provider).execute()

            if response.data:
                return response.data[0]
            return None
        except Exception as exc:
            if _fallback_enabled():
                return local_db.get_health_connection(user_id, provider)
            raise exc
    return local_db.get_health_connection(user_id, provider)


def delete_health_connection(user_id: str, provider: str) -> None:
    """Delete health device connection."""
    if supabase_client:
        try:
            supabase_client.table("health_connections").delete().eq(
                "user_id", user_id
            ).eq("provider", provider).execute()
        except Exception as exc:
            if _fallback_enabled():
                local_db.delete_health_connection(user_id, provider)
            else:
                raise exc
    else:
        local_db.delete_health_connection(user_id, provider)


def save_health_data(health_payload: Dict[str, Any]) -> None:
    """Save health metrics data."""
    if supabase_client:
        try:
            supabase_client.table("health_data").upsert(
                health_payload,
                on_conflict="user_id,date,provider"
            ).execute()
        except Exception as exc:
            if _fallback_enabled():
                local_db.save_health_data(health_payload)
            else:
                raise exc
    else:
        local_db.save_health_data(health_payload)


def get_latest_health_data(user_id: str, date: str) -> Optional[Dict[str, Any]]:
    """Get the most recent health data for a user on a specific date (any provider)."""
    if supabase_client:
        try:
            result = supabase_client.table("health_data")\
                .select("*")\
                .eq("user_id", user_id)\
                .eq("date", date)\
                .order("synced_at", desc=True)\
                .limit(1)\
                .execute()
            return result.data[0] if result.data else None
        except Exception as exc:
            if _fallback_enabled():
                return local_db.get_latest_health_data(user_id, date)
            raise exc
    else:
        return local_db.get_latest_health_data(user_id, date)


# ============================================
# Microsoft Calendar Integration Functions
# ============================================

def store_microsoft_token(token_payload: Dict[str, Any]) -> None:
    """Save or update Microsoft OAuth token for calendar access."""
    user_id = token_payload.get("user_id")
    print(f"[storage.store_microsoft_token] Called for user {user_id}")

    if supabase_client:
        try:
            print(f"[storage.store_microsoft_token] Using Supabase client")
            result = supabase_client.table("microsoft_tokens").upsert(
                token_payload,
                on_conflict="user_id"
            ).execute()
            print(f"[storage.store_microsoft_token] ✅ Supabase upsert completed for user {user_id}")
            print(f"[storage.store_microsoft_token] Result: {result.data if hasattr(result, 'data') else 'no data'}")
        except Exception as exc:
            print(f"[storage.store_microsoft_token] ❌ Supabase error: {exc}")
            if _fallback_enabled():
                print(f"[storage.store_microsoft_token] Falling back to local DB")
                local_db.store_microsoft_token(token_payload)
            else:
                raise exc
    else:
        print(f"[storage.store_microsoft_token] Using local DB (no Supabase client)")
        local_db.store_microsoft_token(token_payload)


def get_microsoft_token(user_id: str) -> Optional[Dict[str, Any]]:
    """Get Microsoft OAuth token for a user."""
    if supabase_client:
        try:
            response = supabase_client.table("microsoft_tokens").select("*").eq(
                "user_id", user_id
            ).execute()

            if response.data:
                return response.data[0]
            return None
        except Exception as exc:
            if _fallback_enabled():
                return local_db.get_microsoft_token(user_id)
            raise exc
    return local_db.get_microsoft_token(user_id)


def update_microsoft_token(
    user_id: str,
    access_token: str,
    refresh_token: str,
    expires_at: int,
    scope: Optional[str] = None
) -> None:
    """Update Microsoft access token after refresh."""
    update_payload = {
        "user_id": user_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    if scope:
        update_payload["scope"] = scope

    if supabase_client:
        try:
            print(f"[storage.update_microsoft_token] Upserting token for user {user_id}")
            # Use upsert instead of update to ensure token is saved even if record doesn't exist
            result = supabase_client.table("microsoft_tokens").upsert(
                update_payload,
                on_conflict="user_id"
            ).execute()
            print(f"[storage.update_microsoft_token] ✅ Token upserted successfully for user {user_id}")
        except Exception as exc:
            print(f"[storage.update_microsoft_token] ❌ Supabase error: {exc}")
            if _fallback_enabled():
                print(f"[storage.update_microsoft_token] Falling back to local DB")
                local_db.update_microsoft_token(user_id, access_token, refresh_token, expires_at, scope)
            else:
                raise exc
    else:
        print(f"[storage.update_microsoft_token] Using local DB (no Supabase client)")
        local_db.update_microsoft_token(user_id, access_token, refresh_token, expires_at, scope)


def migrate_microsoft_token_user_id(old_user_id: str, new_user_id: str) -> None:
    """
    Migrate Microsoft token from old user_id to new user_id.
    Used during account merges when google_id changes.
    """
    if supabase_client:
        try:
            # Check if token exists for old user
            result = supabase_client.table("microsoft_tokens").select("*").eq(
                "user_id", old_user_id
            ).execute()

            if result.data and len(result.data) > 0:
                token_data = result.data[0]
                # Update user_id to new value
                token_data["user_id"] = new_user_id
                # Remove id field to avoid conflict
                token_data.pop("id", None)
                # Upsert with new user_id
                supabase_client.table("microsoft_tokens").upsert(
                    token_data,
                    on_conflict="user_id"
                ).execute()
                print(f"[storage] Migrated Microsoft token from {old_user_id} to {new_user_id}")
        except Exception as exc:
            print(f"[storage] Failed to migrate Microsoft token: {exc}")
            if _fallback_enabled():
                local_db.migrate_microsoft_token_user_id(old_user_id, new_user_id)
            else:
                raise exc
    else:
        local_db.migrate_microsoft_token_user_id(old_user_id, new_user_id)


def delete_microsoft_token(user_id: str) -> None:
    """Delete Microsoft token (disconnect work calendar)."""
    if supabase_client:
        try:
            supabase_client.table("microsoft_tokens").delete().eq(
                "user_id", user_id
            ).execute()
        except Exception as exc:
            if _fallback_enabled():
                local_db.delete_microsoft_token(user_id)
            else:
                raise exc
    else:
        local_db.delete_microsoft_token(user_id)
