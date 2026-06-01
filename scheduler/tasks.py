from apscheduler.schedulers.asyncio import AsyncIOScheduler
from services import email_sendgrid
from services.openai_service import generate_schedule_insights
from db import storage
from datetime import datetime, timezone, timedelta
import pytz
import httpx
import secrets

scheduler = AsyncIOScheduler()

_sent_today: dict[str, str] = {}


async def morning_trigger_job():
    """
    Runs every 15 minutes. Sends ONE morning email per user per day
    at their preferred insight_time in their timezone.
    """
    print("Running morning trigger check...")

    try:
        users = storage.get_all_users()
        print(f"📊 Found {len(users)} users in database")
    except Exception as e:
        print(f"Failed to fetch users: {e}")
        return

    for user in users:
        google_id = user.get("google_id")
        if not google_id:
            continue

        # Skip users who have unsubscribed from email notifications
        if not user.get("email_notifications_enabled", True):
            print(f"⏭️ Skipping {user.get('email')} - email notifications disabled")
            continue

        user_tz_str = user.get("timezone", "UTC")

        # Handle both label format ("morning") and time format ("07:00")
        TIME_LABELS = {
            'morning': '07:00',
            'evening': '18:00',
            'night': '21:00'
        }
        raw_insight_time = user.get("insight_time", "morning")
        insight_time_str = TIME_LABELS.get(raw_insight_time, raw_insight_time)

        try:
            user_tz = pytz.timezone(user_tz_str)
        except pytz.exceptions.UnknownTimeZoneError:
            user_tz = pytz.UTC

        now_in_user_tz = datetime.now(user_tz)
        today_str = now_in_user_tz.strftime("%Y-%m-%d")
        current_time = now_in_user_tz.strftime("%H:%M")

        print(f"🔍 Checking {user.get('email')}: tz={user_tz_str}, current={current_time}, target={insight_time_str}")

        # Skip if already sent today
        if _sent_today.get(google_id) == today_str:
            print(f"⏭️ Already sent to {user.get('email')} today")
            continue

        # Skip if not yet time
        if not _time_matches(current_time, insight_time_str):
            print(f"⏰ Not time yet for {user.get('email')} (current: {current_time}, target: {insight_time_str})")
            continue

        print(f"✅ Time match! Processing {user.get('email')}...")

        try:
            # Fetch today's calendar events in user's timezone
            events = storage.get_today_events(google_id, user_timezone=user_tz)
            meeting_count = len(events)
            print(f"📅 Found {meeting_count} meetings for {user.get('email')} on {today_str}")

            # Fetch health data (readiness score from Oura/Fitbit if connected)
            readiness_score = None
            try:
                health_data = storage.get_latest_health_data(google_id, today_str)
                if health_data:
                    readiness_score = health_data.get("readiness_score")
                    provider = health_data.get("provider", "health device")
                    print(f"💪 Health data found: readiness={readiness_score}/100 (from {provider})")
                else:
                    print(f"⚠️ No health data found for {today_str}")
            except Exception as e:
                print(f"❌ Error fetching health data: {e}")
                readiness_score = None

            # Create email auth token for one-click dashboard access
            email_token = secrets.token_urlsafe(32)
            token_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
            try:
                storage.create_email_auth_token(
                    user_id=google_id,
                    token=email_token,
                    expires_at=token_expires_at.isoformat()
                )
            except Exception as token_err:
                print(f"⚠️ Failed to create email token for {user['email']}: {token_err}")
                email_token = None  # Continue without token

            # Create unsubscribe token for email preference management
            unsubscribe_token = secrets.token_urlsafe(32)
            unsubscribe_expires_at = datetime.now(timezone.utc) + timedelta(days=365)  # Long-lived
            try:
                storage.create_unsubscribe_token(
                    user_id=google_id,
                    token=unsubscribe_token,
                    expires_at=unsubscribe_expires_at.isoformat()
                )
            except Exception as unsub_err:
                print(f"⚠️ Failed to create unsubscribe token for {user['email']}: {unsub_err}")
                unsubscribe_token = None  # Continue without token

            # Send email via SendGrid (energy-aware, simple message)
            email_sent = email_sendgrid.send_daily_insights_email(
                to_email=user["email"],
                name=user.get("name", "there"),
                meeting_count=meeting_count,
                readiness_score=readiness_score,
                user_id=google_id,
                email_token=email_token,
                unsubscribe_token=unsubscribe_token
            )

            if email_sent:
                _sent_today[google_id] = today_str
                health_status = f"readiness={readiness_score}" if readiness_score else "no health data"
                print(f"✅ Daily insights email sent to {user['email']} at {insight_time_str} ({user_tz_str})")
                print(f"   Summary: {meeting_count} meetings, {health_status}")
            else:
                print(f"⚠️ Failed to send email to {user['email']}, will retry next cycle")

        except Exception as e:
            print(f"❌ Failed to process {user.get('email')}: {e}")

    _cleanup_sent_tracker()


def _time_matches(current_time: str, preferred_time: str) -> bool:
    """Check if current time is within the 15-min window of preferred time."""
    try:
        curr_h, curr_m = map(int, current_time.split(":"))
        pref_h, pref_m = map(int, preferred_time.split(":"))
        curr_total = curr_h * 60 + curr_m
        pref_total = pref_h * 60 + pref_m
        return 0 <= (curr_total - pref_total) < 15
    except ValueError:
        return False


def _cleanup_sent_tracker():
    """Remove stale entries from yesterday."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    stale = [uid for uid, date in _sent_today.items() if date != today]
    for uid in stale:
        del _sent_today[uid]


async def evening_trigger_job():
    """
    Runs every 15 minutes. Sends ONE evening check-in email per user per day
    at 5:00 PM in their timezone (if they completed morning check-in).
    """
    print("Running evening check-in trigger...")

    try:
        users = storage.get_all_users()
        print(f"📊 Found {len(users)} users for evening check-in")
    except Exception as e:
        print(f"Failed to fetch users: {e}")
        return

    for user in users:
        google_id = user.get("google_id")
        if not google_id:
            continue

        # Skip users who have unsubscribed from email notifications
        if not user.get("email_notifications_enabled", True):
            print(f"⏭️ Skipping evening email for {user.get('email')} - email notifications disabled")
            continue

        user_tz_str = user.get("timezone", "UTC")
        try:
            user_tz = pytz.timezone(user_tz_str)
        except pytz.exceptions.UnknownTimeZoneError:
            user_tz = pytz.UTC

        now_in_user_tz = datetime.now(user_tz)
        today_str = now_in_user_tz.strftime("%Y-%m-%d")
        current_time = now_in_user_tz.strftime("%H:%M")

        # Evening email at 5:00 PM (17:00)
        evening_time = "17:00"

        print(f"🔍 Checking {user.get('email')}: tz={user_tz_str}, current={current_time}, target={evening_time}")

        # Skip if not yet time
        if not _time_matches(current_time, evening_time):
            continue

        # Check if user completed morning check-in today
        try:
            checkin = storage.get_checkin(google_id, today_str)
            if not checkin or not checkin.get("priority"):
                print(f"⏭️ No morning check-in for {user.get('email')}, skipping evening email")
                continue

            # Skip if already completed evening check-in
            if checkin.get("evening_completed_at"):
                print(f"⏭️ {user.get('email')} already completed evening check-in")
                continue

            priority = checkin.get("priority")

        except Exception as e:
            print(f"❌ Error checking morning data for {user.get('email')}: {e}")
            continue

        # Create email auth token for one-click dashboard access
        email_token = secrets.token_urlsafe(32)
        token_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        try:
            storage.create_email_auth_token(
                user_id=google_id,
                token=email_token,
                expires_at=token_expires_at.isoformat()
            )
        except Exception as token_err:
            print(f"⚠️ Failed to create email token for {user['email']}: {token_err}")
            email_token = None

        # Create unsubscribe token for email preference management
        unsubscribe_token = secrets.token_urlsafe(32)
        unsubscribe_expires_at = datetime.now(timezone.utc) + timedelta(days=365)  # Long-lived
        try:
            storage.create_unsubscribe_token(
                user_id=google_id,
                token=unsubscribe_token,
                expires_at=unsubscribe_expires_at.isoformat()
            )
        except Exception as unsub_err:
            print(f"⚠️ Failed to create unsubscribe token for {user['email']}: {unsub_err}")
            unsubscribe_token = None

        # Send evening check-in email
        email_sent = email_sendgrid.send_evening_checkin_email(
            to_email=user["email"],
            name=user.get("name", "there"),
            priority=priority,
            user_id=google_id,
            email_token=email_token,
            unsubscribe_token=unsubscribe_token
        )

        if email_sent:
            print(f"✅ Evening check-in email sent to {user['email']} at {evening_time} ({user_tz_str})")
        else:
            print(f"⚠️ Failed to send evening email to {user['email']}")


def start_scheduler():
    """Start the APScheduler for daily insights and evening check-in emails."""
    scheduler.add_job(morning_trigger_job, "cron", minute="*/15")
    scheduler.add_job(evening_trigger_job, "cron", minute="*/15")
    scheduler.start()
    print("✅ Scheduler started. Checking every 15 min for morning insights and evening check-ins via SendGrid.")
