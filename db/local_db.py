from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from datetime import datetime, timezone

from core.config import settings

BASE_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_sqlite.sql"
_schema_initialized = False


def _db_path() -> Path:
    configured = Path(settings.LOCAL_DB_PATH)
    if configured.is_absolute():
        return configured
    return BASE_DIR / configured


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_local_schema() -> None:
    global _schema_initialized
    if _schema_initialized:
        return
    if not SCHEMA_PATH.exists():
        print("SQLite schema file not found; skipping local schema initialization.")
        return
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with _connect() as conn:
        conn.executescript(schema_sql)
        conn.commit()
    _schema_initialized = True


# ─── Users ───────────────────────────────────────────────────────────

def upsert_user(user_payload: Dict[str, Any]) -> None:
    ensure_local_schema()
    with _connect() as conn:
        conn.execute(
            """
            insert into users (google_id, email, name, picture_url)
            values (?, ?, ?, ?)
            on conflict(google_id) do update set
                email=excluded.email,
                name=excluded.name,
                picture_url=excluded.picture_url
            """,
            (
                user_payload.get("google_id"),
                user_payload.get("email"),
                user_payload.get("name"),
                user_payload.get("picture_url"),
            ),
        )
        conn.commit()


def get_user(google_id: str) -> Optional[Dict[str, Any]]:
    ensure_local_schema()
    with _connect() as conn:
        row = conn.execute(
            "select * from users where google_id = ?",
            (google_id,),
        ).fetchone()
        return dict(row) if row else None


def delete_user(google_id: str) -> None:
    """Delete a user by google_id."""
    ensure_local_schema()
    with _connect() as conn:
        # Delete reset tokens first
        conn.execute("delete from password_reset_tokens where user_id = ?", (google_id,))
        # Then delete user
        conn.execute("delete from users where google_id = ?", (google_id,))
        conn.commit()


def update_user_profile(google_id: str, update_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    ensure_local_schema()
    if not update_data:
        return get_user(google_id)

    allowed_fields = {"name", "age", "profession", "short_term_goal", "timezone", "insight_time", "email_notifications_enabled"}
    filtered = {k: v for k, v in update_data.items() if k in allowed_fields}

    if not filtered:
        return get_user(google_id)

    set_clause = ", ".join(f"{k} = ?" for k in filtered)
    values = list(filtered.values()) + [google_id]

    with _connect() as conn:
        conn.execute(
            f"update users set {set_clause} where google_id = ?",
            values,
        )
        conn.commit()

    return get_user(google_id)


def update_email_preferences(google_id: str, enabled: bool) -> None:
    """Update email notification preferences for a user."""
    ensure_local_schema()
    with _connect() as conn:
        # SQLite uses 1/0 for boolean
        conn.execute(
            "update users set email_notifications_enabled = ? where google_id = ?",
            (1 if enabled else 0, google_id)
        )
        conn.commit()


# ─── Tokens ──────────────────────────────────────────────────────────

def get_token(user_id: str) -> Optional[Dict[str, Any]]:
    ensure_local_schema()
    with _connect() as conn:
        row = conn.execute(
            "select * from tokens where user_id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def upsert_token(token_payload: Dict[str, Any]) -> None:
    ensure_local_schema()
    with _connect() as conn:
        conn.execute(
            """
            insert into tokens (user_id, access_token, refresh_token, expires_at, updated_at)
            values (?, ?, ?, ?, ?)
            on conflict(user_id) do update set
                access_token=excluded.access_token,
                refresh_token=excluded.refresh_token,
                expires_at=excluded.expires_at,
                updated_at=excluded.updated_at
            """,
            (
                token_payload.get("user_id"),
                token_payload.get("access_token"),
                token_payload.get("refresh_token"),
                token_payload.get("expires_at"),
                token_payload.get("updated_at"),
            ),
        )
        conn.commit()


def delete_token(user_id: str) -> None:
    """Delete OAuth token for a user."""
    ensure_local_schema()
    with _connect() as conn:
        conn.execute("delete from tokens where user_id = ?", (user_id,))
        conn.commit()


# ─── Events ──────────────────────────────────────────────────────────

def upsert_events(events_payload: Iterable[Dict[str, Any]]) -> None:
    ensure_local_schema()
    rows = [
        (
            payload.get("user_id"),
            payload.get("google_event_id"),
            payload.get("summary"),
            payload.get("description"),
            payload.get("start_time"),
            payload.get("end_time"),
            payload.get("status"),
        )
        for payload in events_payload
    ]
    if not rows:
        return
    with _connect() as conn:
        conn.executemany(
            """
            insert into calendar_events (
                user_id,
                google_event_id,
                summary,
                description,
                start_time,
                end_time,
                status
            )
            values (?, ?, ?, ?, ?, ?, ?)
            on conflict(google_event_id) do update set
                user_id=excluded.user_id,
                summary=excluded.summary,
                description=excluded.description,
                start_time=excluded.start_time,
                end_time=excluded.end_time,
                status=excluded.status
            """,
            rows,
        )
        conn.commit()


def get_events_between(user_id: str, start_time: str, end_time: str) -> List[Dict[str, Any]]:
    ensure_local_schema()
    with _connect() as conn:
        rows = conn.execute(
            """
            select *
            from calendar_events
            where user_id = ?
              and start_time >= ?
              and start_time < ?
            order by start_time
            """,
            (user_id, start_time, end_time),
        ).fetchall()
        return [dict(row) for row in rows]


# ─── Feedback ────────────────────────────────────────────────────────

def insert_feedback(feedback_payload: Dict[str, Any]) -> None:
    ensure_local_schema()
    with _connect() as conn:
        conn.execute(
            """
            insert into feedback (user_id, date, feedback_type, rating, thoughts)
            values (?, ?, ?, ?, ?)
            """,
            (
                feedback_payload.get("user_id"),
                feedback_payload.get("date"),
                feedback_payload.get("feedback_type", "end_of_day"),
                feedback_payload.get("rating"),
                feedback_payload.get("thoughts"),
            ),
        )
        conn.commit()


def get_feedback_by_user(user_id: str, limit: int = 30) -> List[Dict[str, Any]]:
    ensure_local_schema()
    with _connect() as conn:
        rows = conn.execute(
            """
            select * from feedback
            where user_id = ?
            order by created_at desc
            limit ?
            """,
            (user_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]


# ─── Password Management ─────────────────────────────────────────────

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Get user by email address. If duplicates exist, prefer the one with password_hash."""
    ensure_local_schema()
    with _connect() as conn:
        rows = conn.execute(
            "select * from users where email = ?",
            (email,)
        ).fetchall()

        if not rows:
            return None

        # If multiple records exist, prefer the one with password_hash
        if len(rows) > 1:
            for row in rows:
                if dict(row).get("password_hash"):
                    return dict(row)

        return dict(rows[0])


def update_user_password(user_id: str, password_hash: str) -> None:
    """Update user's password hash."""
    ensure_local_schema()
    with _connect() as conn:
        conn.execute(
            "update users set password_hash = ? where google_id = ?",
            (password_hash, user_id)
        )
        conn.commit()


def create_password_reset_token(user_id: str, email: str, token: str, expires_at: str) -> None:
    """Create a password reset token."""
    ensure_local_schema()
    import uuid
    with _connect() as conn:
        conn.execute(
            """
            insert into password_reset_tokens (id, user_id, email, token, token_type, expires_at, used)
            values (?, ?, ?, ?, ?, ?, 0)
            """,
            (str(uuid.uuid4()), user_id, email, token, 'password_reset', expires_at)
        )
        conn.commit()


def get_password_reset_token(token: str) -> Optional[Dict[str, Any]]:
    """Get password reset token details."""
    ensure_local_schema()
    with _connect() as conn:
        row = conn.execute(
            "select * from password_reset_tokens where token = ? and token_type = 'password_reset' and used = 0",
            (token,)
        ).fetchone()
        return dict(row) if row else None


def mark_reset_token_used(token: str) -> None:
    """Mark a password reset token as used."""
    ensure_local_schema()
    with _connect() as conn:
        conn.execute(
            "update password_reset_tokens set used = 1 where token = ?",
            (token,)
        )
        conn.commit()


def delete_reset_tokens_by_user(user_id: str) -> None:
    """Delete all password reset tokens for a user (called when account is deleted)."""
    ensure_local_schema()
    with _connect() as conn:
        conn.execute(
            "delete from password_reset_tokens where user_id = ?",
            (user_id,)
        )
        conn.commit()


# ─── Email Auth Tokens ───────────────────────────────────────────────

def create_email_auth_token(user_id: str, token: str, expires_at: str) -> None:
    """Create an email authentication token for one-click login from emails."""
    ensure_local_schema()
    import uuid
    with _connect() as conn:
        # Reuse password_reset_tokens table with token_type='email_auth'
        # Email is not required for email auth tokens, so we use user_id as placeholder
        conn.execute(
            """
            insert into password_reset_tokens (id, user_id, email, token, token_type, expires_at, used)
            values (?, ?, ?, ?, ?, ?, 0)
            """,
            (str(uuid.uuid4()), user_id, user_id, token, 'email_auth', expires_at)
        )
        conn.commit()


def get_email_auth_token(token: str) -> Optional[Dict[str, Any]]:
    """Get email auth token details."""
    ensure_local_schema()
    with _connect() as conn:
        row = conn.execute(
            "select * from password_reset_tokens where token = ? and token_type = 'email_auth' and used = 0",
            (token,)
        ).fetchone()
        return dict(row) if row else None


def mark_email_auth_token_used(token: str) -> None:
    """Mark an email auth token as used."""
    ensure_local_schema()
    with _connect() as conn:
        conn.execute(
            "update password_reset_tokens set used = 1 where token = ?",
            (token,)
        )
        conn.commit()


# ─── Unsubscribe Tokens ──────────────────────────────────────────────

def create_unsubscribe_token(user_id: str, token: str, expires_at: str) -> None:
    """Create an unsubscribe token for email preference management."""
    ensure_local_schema()
    import uuid
    with _connect() as conn:
        conn.execute(
            """
            insert into password_reset_tokens (id, user_id, email, token, token_type, expires_at, used)
            values (?, ?, ?, ?, ?, ?, 0)
            """,
            (str(uuid.uuid4()), user_id, user_id, token, 'unsubscribe', expires_at)
        )
        conn.commit()


def get_unsubscribe_token(token: str) -> Optional[Dict[str, Any]]:
    """Get unsubscribe token details."""
    ensure_local_schema()
    with _connect() as conn:
        row = conn.execute(
            "select * from password_reset_tokens where token = ? and token_type = 'unsubscribe' and used = 0",
            (token,)
        ).fetchone()
        return dict(row) if row else None


def mark_unsubscribe_token_used(token: str) -> None:
    """Mark an unsubscribe token as used."""
    ensure_local_schema()
    with _connect() as conn:
        conn.execute(
            "update password_reset_tokens set used = 1 where token = ?",
            (token,)
        )
        conn.commit()


# ─── Check-ins ───────────────────────────────────────────────────────

def upsert_checkin(checkin_payload: Dict[str, Any]) -> None:
    """Save or update daily check-in data."""
    ensure_local_schema()
    import uuid
    with _connect() as conn:
        conn.execute(
            """
            insert into checkins (id, user_id, date, sleep_hours, energy_level, priority)
            values (?, ?, ?, ?, ?, ?)
            on conflict(user_id, date) do update set
                sleep_hours=excluded.sleep_hours,
                energy_level=excluded.energy_level,
                priority=excluded.priority
            """,
            (
                str(uuid.uuid4()),
                checkin_payload.get("user_id"),
                checkin_payload.get("date"),
                checkin_payload.get("sleep_hours"),
                checkin_payload.get("energy_level"),
                checkin_payload.get("priority"),
            ),
        )
        conn.commit()


def get_checkin(user_id: str, date: str) -> Optional[Dict[str, Any]]:
    """Get check-in data for a specific user and date."""
    ensure_local_schema()
    with _connect() as conn:
        row = conn.execute(
            "select * from checkins where user_id = ? and date = ?",
            (user_id, date),
        ).fetchone()
        return dict(row) if row else None


def get_all_users() -> List[Dict[str, Any]]:
    """Get all users (for scheduler)."""
    ensure_local_schema()
    with _connect() as conn:
        rows = conn.execute("select * from users").fetchall()
        return [dict(row) for row in rows]


# ─── Insights Cache ──────────────────────────────────────────────────

def cache_insights(user_id: str, date: str, detailed: str, quick: str, day_type: str) -> None:
    """Cache AI-generated insights to avoid duplicate OpenAI calls."""
    ensure_local_schema()
    with _connect() as conn:
        conn.execute(
            """
            insert into insights_cache (user_id, date, detailed_insights, quick_insights, day_type)
            values (?, ?, ?, ?, ?)
            on conflict(user_id, date) do update set
                detailed_insights = excluded.detailed_insights,
                quick_insights = excluded.quick_insights,
                day_type = excluded.day_type,
                cached_at = datetime('now')
            """,
            (user_id, date, detailed, quick, day_type)
        )
        conn.commit()


def get_cached_insights(user_id: str, date: str, max_age_hours: int = 2) -> Optional[Dict[str, Any]]:
    """Get cached insights if they exist and are fresh (< max_age_hours old)."""
    ensure_local_schema()
    with _connect() as conn:
        row = conn.execute(
            """
            select * from insights_cache
            where user_id = ? and date = ?
            and (julianday('now') - julianday(cached_at)) * 24 < ?
            """,
            (user_id, date, max_age_hours)
        ).fetchone()
        return dict(row) if row else None


# ─── Health Integration ──────────────────────────────────────────────────

def save_health_connection(connection_payload: Dict[str, Any]) -> None:
    """Save or update a health device connection (OAuth tokens)."""
    ensure_local_schema()
    with _connect() as conn:
        conn.execute(
            """
            insert into health_connections (
                user_id, provider, access_token, refresh_token, expires_at,
                scope, provider_user_id, connected_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(user_id, provider) do update set
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                expires_at = excluded.expires_at,
                scope = excluded.scope,
                provider_user_id = excluded.provider_user_id,
                connected_at = excluded.connected_at
            """,
            (
                connection_payload["user_id"],
                connection_payload["provider"],
                connection_payload["access_token"],
                connection_payload.get("refresh_token"),
                connection_payload.get("expires_at"),
                connection_payload.get("scope"),
                connection_payload.get("provider_user_id"),
                connection_payload.get("connected_at", datetime.now(timezone.utc).isoformat())
            )
        )
        conn.commit()


def get_health_connection(user_id: str, provider: str) -> Optional[Dict[str, Any]]:
    """Get health device connection for a specific provider."""
    ensure_local_schema()
    with _connect() as conn:
        row = conn.execute(
            "select * from health_connections where user_id = ? and provider = ?",
            (user_id, provider)
        ).fetchone()
        return dict(row) if row else None


def delete_health_connection(user_id: str, provider: str) -> None:
    """Delete health device connection."""
    ensure_local_schema()
    with _connect() as conn:
        conn.execute(
            "delete from health_connections where user_id = ? and provider = ?",
            (user_id, provider)
        )
        conn.commit()


def save_health_data(health_payload: Dict[str, Any]) -> None:
    """Save health metrics data."""
    ensure_local_schema()
    with _connect() as conn:
        # Convert raw_data dict to JSON string for SQLite
        raw_data_str = None
        if health_payload.get("raw_data"):
            import json
            raw_data_str = json.dumps(health_payload["raw_data"])

        conn.execute(
            """
            insert into health_data (
                user_id, date, provider, sleep_score, sleep_duration_minutes,
                deep_sleep_minutes, rem_sleep_minutes, light_sleep_minutes,
                awake_time_minutes, sleep_efficiency, readiness_score,
                recovery_score, body_battery, resting_heart_rate, avg_heart_rate,
                max_heart_rate, min_heart_rate, hrv_avg, hrv_rmssd,
                activity_score, steps, active_calories, total_calories,
                active_minutes, stress_avg, spo2_avg, raw_data
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(user_id, date, provider) do update set
                sleep_score = excluded.sleep_score,
                sleep_duration_minutes = excluded.sleep_duration_minutes,
                deep_sleep_minutes = excluded.deep_sleep_minutes,
                rem_sleep_minutes = excluded.rem_sleep_minutes,
                light_sleep_minutes = excluded.light_sleep_minutes,
                awake_time_minutes = excluded.awake_time_minutes,
                sleep_efficiency = excluded.sleep_efficiency,
                readiness_score = excluded.readiness_score,
                recovery_score = excluded.recovery_score,
                body_battery = excluded.body_battery,
                resting_heart_rate = excluded.resting_heart_rate,
                avg_heart_rate = excluded.avg_heart_rate,
                max_heart_rate = excluded.max_heart_rate,
                min_heart_rate = excluded.min_heart_rate,
                hrv_avg = excluded.hrv_avg,
                hrv_rmssd = excluded.hrv_rmssd,
                activity_score = excluded.activity_score,
                steps = excluded.steps,
                active_calories = excluded.active_calories,
                total_calories = excluded.total_calories,
                active_minutes = excluded.active_minutes,
                stress_avg = excluded.stress_avg,
                spo2_avg = excluded.spo2_avg,
                raw_data = excluded.raw_data,
                synced_at = datetime('now')
            """,
            (
                health_payload["user_id"],
                health_payload["date"],
                health_payload["provider"],
                health_payload.get("sleep_score"),
                health_payload.get("sleep_duration_minutes"),
                health_payload.get("deep_sleep_minutes"),
                health_payload.get("rem_sleep_minutes"),
                health_payload.get("light_sleep_minutes"),
                health_payload.get("awake_time_minutes"),
                health_payload.get("sleep_efficiency"),
                health_payload.get("readiness_score"),
                health_payload.get("recovery_score"),
                health_payload.get("body_battery"),
                health_payload.get("resting_heart_rate"),
                health_payload.get("avg_heart_rate"),
                health_payload.get("max_heart_rate"),
                health_payload.get("min_heart_rate"),
                health_payload.get("hrv_avg"),
                health_payload.get("hrv_rmssd"),
                health_payload.get("activity_score"),
                health_payload.get("steps"),
                health_payload.get("active_calories"),
                health_payload.get("total_calories"),
                health_payload.get("active_minutes"),
                health_payload.get("stress_avg"),
                health_payload.get("spo2_avg"),
                raw_data_str
            )
        )
        conn.commit()


def get_latest_health_data(user_id: str, date: str) -> Optional[Dict[str, Any]]:
    """Get the most recent health data for a user on a specific date (any provider)."""
    ensure_local_schema()
    with _connect() as conn:
        row = conn.execute(
            """
            select * from health_data
            where user_id = ? and date = ?
            order by synced_at desc
            limit 1
            """,
            (user_id, date)
        ).fetchone()
        return dict(row) if row else None


# ============================================
# Microsoft Calendar Integration Functions
# ============================================

def store_microsoft_token(token_payload: Dict[str, Any]) -> None:
    """Save or update Microsoft OAuth token for calendar access."""
    ensure_local_schema()
    with _connect() as conn:
        conn.execute(
            """
            insert into microsoft_tokens (
                user_id, access_token, refresh_token, expires_at, scope, connected_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?)
            on conflict(user_id) do update set
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                expires_at = excluded.expires_at,
                scope = excluded.scope,
                updated_at = excluded.updated_at
            """,
            (
                token_payload["user_id"],
                token_payload["access_token"],
                token_payload.get("refresh_token"),
                token_payload["expires_at"],
                token_payload.get("scope"),
                token_payload.get("connected_at", datetime.now(timezone.utc).isoformat()),
                token_payload.get("updated_at", datetime.now(timezone.utc).isoformat())
            )
        )
        conn.commit()


def get_microsoft_token(user_id: str) -> Optional[Dict[str, Any]]:
    """Get Microsoft OAuth token for a user."""
    ensure_local_schema()
    with _connect() as conn:
        row = conn.execute(
            "select * from microsoft_tokens where user_id = ?",
            (user_id,)
        ).fetchone()
        return dict(row) if row else None


def update_microsoft_token(
    user_id: str,
    access_token: str,
    refresh_token: str,
    expires_at: int,
    scope: Optional[str] = None
) -> None:
    """Update Microsoft access token after refresh (uses upsert to handle missing records)."""
    ensure_local_schema()
    with _connect() as conn:
        # Use upsert instead of update to ensure token is saved even if record doesn't exist
        conn.execute(
            """
            insert into microsoft_tokens (
                user_id, access_token, refresh_token, expires_at, scope, connected_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?)
            on conflict(user_id) do update set
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                expires_at = excluded.expires_at,
                scope = excluded.scope,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                access_token,
                refresh_token,
                expires_at,
                scope,
                datetime.now(timezone.utc).isoformat(),  # connected_at (only used on initial insert)
                datetime.now(timezone.utc).isoformat()   # updated_at
            )
        )
        conn.commit()


def migrate_microsoft_token_user_id(old_user_id: str, new_user_id: str) -> None:
    """
    Migrate Microsoft token from old user_id to new user_id.
    Used during account merges when google_id changes.
    """
    ensure_local_schema()
    with _connect() as conn:
        conn.execute(
            "update microsoft_tokens set user_id = ? where user_id = ?",
            (new_user_id, old_user_id)
        )
        conn.commit()
        print(f"[local_db] Migrated Microsoft token from {old_user_id} to {new_user_id}")


def delete_microsoft_token(user_id: str) -> None:
    """Delete Microsoft token (disconnect work calendar)."""
    ensure_local_schema()
    with _connect() as conn:
        conn.execute("delete from microsoft_tokens where user_id = ?", (user_id,))
        conn.commit()
