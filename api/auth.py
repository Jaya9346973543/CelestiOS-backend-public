from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, EmailStr
import httpx
import secrets
import time
from datetime import datetime, timedelta, timezone
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from typing import Optional
from urllib.parse import urlencode
from passlib.context import CryptContext
from core.config import settings
from db import storage
from services import email_sendgrid
from services.microsoft_client import is_microsoft_connected


router = APIRouter(prefix="/auth", tags=["Authentication"])

OAUTH_STATE_SALT = "celestios-oauth-state"

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ─── Request / Response Models ───────────────────────────────────────

class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    age: Optional[int] = None
    profession: Optional[str] = None
    short_term_goal: Optional[str] = None
    timezone: Optional[str] = None
    insight_time: Optional[str] = None


class UserProfile(BaseModel):
    google_id: str
    email: str
    name: str
    picture_url: Optional[str] = None
    age: Optional[int] = None
    profession: Optional[str] = None
    short_term_goal: Optional[str] = None
    timezone: Optional[str] = "UTC"
    insight_time: Optional[str] = "08:00"


class FeedbackRequest(BaseModel):
    user_id: str
    date: str
    feedback_type: str = "end_of_day"
    rating: int = Field(ge=1, le=5)
    thoughts: Optional[str] = None


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str


class SigninRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class EmailAuthRequest(BaseModel):
    token: str


class CheckinRequest(BaseModel):
    date: str  # YYYY-MM-DD format
    sleep_hours: Optional[str] = None
    energy_level: Optional[str] = None
    priority: Optional[str] = None
    # Evening check-in fields
    completed_priority: Optional[bool] = None
    disruption: Optional[bool] = None
    disruption_detail: Optional[str] = None
    late_start: Optional[bool] = None
    started_at: Optional[str] = None


class EveningCheckinRequest(BaseModel):
    date: str  # YYYY-MM-DD format
    completed_priority: bool
    disruption: Optional[bool] = None  # None when not answered yet, True when disrupted, False when completed
    disruption_detail: Optional[str] = None  # Category or freeform text describing the disruption


class UnsubscribeRequest(BaseModel):
    token: str


# ─── Helpers ─────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt.
    Bcrypt has a 72-byte limit, so we truncate if necessary.
    """
    # Truncate to 72 bytes to comply with bcrypt's limit
    password_bytes = password.encode('utf-8')[:72]
    truncated_password = password_bytes.decode('utf-8', errors='ignore')
    return pwd_context.hash(truncated_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash.
    Applies the same 72-byte truncation as hash_password.
    """
    # Truncate to 72 bytes to match what was hashed
    password_bytes = plain_password.encode('utf-8')[:72]
    truncated_password = password_bytes.decode('utf-8', errors='ignore')
    return pwd_context.verify(truncated_password, hashed_password)

def _state_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.SECRET_KEY, salt=OAUTH_STATE_SALT)


def _build_google_auth_url(state: str, force_consent: bool = False) -> str:
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": settings.GOOGLE_SCOPES,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "state": state,
    }
    if force_consent:
        params["prompt"] = "consent"
    else:
        params["prompt"] = "select_account"
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def _frontend_redirect(path: str, params: Optional[dict] = None) -> str:
    base_url = settings.FRONTEND_URL.rstrip("/")
    target = f"{base_url}{path}"
    if params:
        return f"{target}?{urlencode(params)}"
    return target


# ─── Routes ──────────────────────────────────────────────────────────

@router.get("/login")
def login_via_google(request: Request, intent: Optional[str] = "signin"):
    """Single login endpoint. Accepts intent parameter to distinguish signin vs connect_calendar."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Google client ID not configured")

    state = _state_serializer().dumps({
        "nonce": secrets.token_urlsafe(16),
        "intent": intent
    })
    # Force consent screen when explicitly connecting calendar to ensure we get all scopes
    force_consent = (intent == "connect_calendar")
    auth_url = _build_google_auth_url(state, force_consent=force_consent)

    accepts_html = "text/html" in request.headers.get("accept", "")
    if accepts_html:
        return RedirectResponse(auth_url)
    return {"auth_url": auth_url}


@router.get("/callback")
async def google_auth_callback(code: str, state: Optional[str] = None):
    """Callback for Google OAuth. Auto-detects first-time vs returning user."""
    if not state:
        raise HTTPException(status_code=400, detail="Missing OAuth state")

    try:
        state_data = _state_serializer().loads(state, max_age=settings.OAUTH_STATE_MAX_AGE_SECONDS)
    except SignatureExpired as exc:
        raise HTTPException(status_code=400, detail="OAuth state expired") from exc
    except BadSignature as exc:
        raise HTTPException(status_code=400, detail="Invalid OAuth state") from exc

    # Extract intent from state (default to "signin" for backward compatibility)
    intent = state_data.get("intent", "signin")

    token_url = "https://oauth2.googleapis.com/token"

    data = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
    }

    if not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Google client secret not configured")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data)
            token_data = response.json()
            if response.status_code != 200 or "error" in token_data:
                return RedirectResponse(
                    _frontend_redirect("/", {"auth": "error"})
                )

            access_token = token_data.get("access_token")
            if not access_token:
                return RedirectResponse(_frontend_redirect("/", {"auth": "error"}))

            userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
            userinfo_response = await client.get(
                userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if userinfo_response.status_code != 200:
                return RedirectResponse(_frontend_redirect("/", {"auth": "error"}))

            user_info = userinfo_response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Google OAuth request failed: {exc}") from exc

    google_id = user_info.get("sub")
    if not google_id:
        return RedirectResponse(_frontend_redirect("/", {"auth": "error"}))

    email = user_info.get("email")

    # CRITICAL FIX: Check if user already exists with this email (manual signup)
    # If yes, UPDATE their google_id to merge accounts instead of creating duplicate
    existing_user = None
    if email:
        try:
            existing_user = storage.get_user_by_email(email)
        except Exception:
            pass  # If lookup fails, treat as new user

    if existing_user:
        # SECURITY CHECK: Block "Sign in/Sign up with Google" for password accounts
        # UNLESS they already merged this specific Google account
        if existing_user.get("password_hash") and intent in ["signin", "signup"]:
            # Allow if this is the same Google account (already merged)
            if existing_user.get("google_id") != google_id:
                return RedirectResponse(
                    _frontend_redirect("/signin", {
                        "error": "email_has_password",
                        "message": "This email is registered with password. Please sign in with email and password."
                    })
                )

        old_google_id = existing_user.get("google_id")

        # DEBUG: Log comparison values to diagnose migration bug
        print(f"[AUTH DEBUG] old_google_id = '{old_google_id}' (type: {type(old_google_id).__name__})")
        print(f"[AUTH DEBUG] google_id = '{google_id}' (type: {type(google_id).__name__})")
        print(f"[AUTH DEBUG] Are they equal? {old_google_id == google_id}")
        print(f"[AUTH DEBUG] Comparison (old != new): {old_google_id != google_id}")

        # Only merge if Google ID is actually changing (email → Google ID scenario)
        # This prevents CASCADE DELETE when user signs in with the same Google account
        if old_google_id != google_id:
            # User exists with this email - MERGE accounts
            # CRITICAL: Delete old record first, then insert merged record
            # (upsert won't work because google_id changes from email to real Google ID)

            # Build merged payload with NEW google_id
            user_payload = {
                "google_id": google_id,  # Real Google ID
                "email": email,
                "name": user_info.get("name") or existing_user.get("name") or "Unknown",
                "picture_url": user_info.get("picture"),
            }

            # Preserve password_hash so user can still sign in with password
            if existing_user.get("password_hash"):
                user_payload["password_hash"] = existing_user["password_hash"]

            # Preserve other profile fields
            for field in ["profession", "age", "short_term_goal", "timezone", "insight_time"]:
                if existing_user.get(field):
                    user_payload[field] = existing_user[field]

            try:
                # Step 1: Migrate Microsoft token before deleting user (CASCADE protection)
                storage.migrate_microsoft_token_user_id(old_google_id, google_id)

                # Step 2: Delete old record (google_id = email)
                storage.delete_user(old_google_id)

                # Step 3: Insert new merged record (google_id = real Google ID)
                storage.upsert_user(user_payload)
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Account merge failed: {exc}") from exc
        else:
            # Same Google account signing in again - just update profile without delete
            # This avoids CASCADE DELETE that would remove Microsoft tokens
            user_payload = {
                "google_id": google_id,
                "email": email,
                "name": user_info.get("name") or existing_user.get("name") or "Unknown",
                "picture_url": user_info.get("picture"),
            }

            # Preserve password_hash so user can still sign in with password
            if existing_user.get("password_hash"):
                user_payload["password_hash"] = existing_user["password_hash"]

            # Preserve other profile fields
            for field in ["profession", "age", "short_term_goal", "timezone", "insight_time"]:
                if existing_user.get(field):
                    user_payload[field] = existing_user[field]

            try:
                # Just upsert - no delete, no CASCADE
                storage.upsert_user(user_payload)
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"User update failed: {exc}") from exc
    else:
        # New user - create fresh profile
        user_payload = {
            "google_id": google_id,
            "email": email,
            "name": user_info.get("name") or email or "Unknown",
            "picture_url": user_info.get("picture"),
        }

        try:
            storage.upsert_user(user_payload)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"User save failed: {exc}") from exc

        # Send appropriate welcome email based on check-in status
        try:
            from datetime import datetime, timezone
            import pytz
            user_tz = pytz.timezone(user_payload.get("timezone", "UTC"))
            today_str = datetime.now(user_tz).strftime("%Y-%m-%d")
            existing_checkin = storage.get_checkin(google_id, today_str)

            if existing_checkin and existing_checkin.get("priority"):
                # User already checked in → send post-checkin welcome email
                email_sendgrid.send_welcome_email_post_checkin(to_email=email, name=user_payload["name"])
                print(f"✉️ Post-checkin welcome email sent to new user: {email}")
            else:
                # User hasn't checked in → send standard welcome email
                email_sendgrid.send_welcome_email(to_email=email, name=user_payload["name"])
                print(f"✉️ Welcome email sent to new user: {email}")
        except Exception as email_err:
            print(f"⚠️ Failed to send welcome email to {email}: {email_err}")

    # --- Refresh token: auto-detect first-time vs returning ---
    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        try:
            existing_token = storage.get_token(google_id)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Token lookup failed: {exc}") from exc
        if existing_token:
            refresh_token = existing_token.get("refresh_token")

    # No refresh token anywhere → first-time user, re-auth with consent
    if not refresh_token:
        state = _state_serializer().dumps({"nonce": secrets.token_urlsafe(16)})
        auth_url = _build_google_auth_url(state, force_consent=True)
        return RedirectResponse(auth_url)

    expires_in = int(token_data.get("expires_in", 0))
    expires_at = int(time.time()) + expires_in if expires_in else 0

    token_payload = {
        "user_id": google_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    try:
        storage.upsert_token(token_payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Token save failed: {exc}") from exc

    # Include email and name in redirect so frontend can cache them
    redirect_params = {
        "auth": "success",
        "user_id": google_id,
        "email": user_payload["email"],
        "name": user_payload["name"]
    }

    return RedirectResponse(
        _frontend_redirect("/dashboard", redirect_params)
    )



@router.put("/profile/{user_id}")
@router.post("/profile/{user_id}")  # Also support POST for frontend compatibility
def update_profile(user_id: str, profile: ProfileUpdate):
    """Update the current user's profile fields in the users table."""
    existing_user = storage.get_user(user_id)
    if not existing_user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = profile.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        storage.update_user_profile(user_id, update_data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Profile update failed: {exc}") from exc

    return {"message": "Profile updated", "updated_fields": list(update_data.keys())}


@router.post("/feedback")
def submit_feedback(feedback: FeedbackRequest):
    if not feedback.user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    feedback_payload = {
        "user_id": feedback.user_id,
        "date": feedback.date,
        "feedback_type": feedback.feedback_type,
        "rating": feedback.rating,
        "thoughts": feedback.thoughts,
    }

    try:
        storage.insert_feedback(feedback_payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Feedback save failed: {exc}") from exc

    return {"message": "Feedback submitted successfully"}


@router.get("/feedback/{user_id}")
def get_feedback(user_id: str, limit: int = 30):
    """Get feedback history for a user."""
    try:
        feedback_list = storage.get_feedback_by_user(user_id, limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Feedback fetch failed: {exc}") from exc

    return {"user_id": user_id, "feedback": feedback_list}


@router.post("/signup")
def manual_signup(signup_data: SignupRequest):
    """
    Manual signup with email and password.
    Creates a new user account without Google OAuth.
    """
    # Check if user already exists
    existing_user = storage.get_user_by_email(signup_data.email)
    if existing_user:
        # Check if it's an OAuth user or manual user
        token_data = None
        try:
            if existing_user.get("google_id"):
                token_data = storage.get_token(existing_user["google_id"])
        except Exception:
            pass

        if token_data and token_data.get("refresh_token"):
            raise HTTPException(
                status_code=400,
                detail="This email is already registered with Google Sign-In. Please sign in with Google."
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="This email is already registered. Please sign in."
            )

    # Hash password
    password_hash = hash_password(signup_data.password)

    # Create user (without google_id)
    user_payload = {
        "email": signup_data.email,
        "name": signup_data.name,
        "password_hash": password_hash,
    }

    try:
        # For manual signup, use email as user_id
        storage.upsert_user({
            "google_id": signup_data.email,  # Use email as unique identifier
            "email": signup_data.email,
            "name": signup_data.name,
            "password_hash": password_hash,
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"User creation failed: {exc}") from exc

    # Send appropriate welcome email based on check-in status
    try:
        from datetime import datetime, timezone
        import pytz
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        existing_checkin = storage.get_checkin(signup_data.email, today_str)

        if existing_checkin and existing_checkin.get("priority"):
            # User already checked in → send post-checkin welcome email
            email_sendgrid.send_welcome_email_post_checkin(to_email=signup_data.email, name=signup_data.name)
            print(f"✉️ Post-checkin welcome email sent to new user: {signup_data.email}")
        else:
            # User hasn't checked in → send standard welcome email
            email_sendgrid.send_welcome_email(to_email=signup_data.email, name=signup_data.name)
            print(f"✉️ Welcome email sent to new user: {signup_data.email}")
    except Exception as email_err:
        print(f"⚠️ Failed to send welcome email to {signup_data.email}: {email_err}")

    return {
        "message": "Account created successfully",
        "user_id": signup_data.email,
        "email": signup_data.email,
        "name": signup_data.name
    }


@router.post("/signin")
def manual_signin(signin_data: SigninRequest):
    """
    Manual signin with email and password.
    Returns user data if credentials are valid.
    """
    # Get user by email
    user = storage.get_user_by_email(signin_data.email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Check if user has password (not OAuth-only)
    if not user.get("password_hash"):
        raise HTTPException(
            status_code=400,
            detail="This account uses Google Sign-In. Please sign in with Google."
        )

    # Verify password
    if not verify_password(signin_data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Return user data
    return {
        "message": "Sign in successful",
        "user_id": user.get("google_id") or user.get("email"),
        "email": user["email"],
        "name": user["name"],
        "profession": user.get("profession"),
        "short_term_goal": user.get("short_term_goal"),
    }


@router.post("/forgot-password")
def forgot_password(request: ForgotPasswordRequest):
    """
    Request a password reset email.
    Checks if user exists and uses password auth (not OAuth).
    """
    # Get user by email
    user = storage.get_user_by_email(request.email)
    if not user:
        # Don't reveal if user exists or not for security
        return {"message": "If an account exists with this email, a password reset link has been sent."}

    # Check if user has password (not OAuth-only)
    if not user.get("password_hash"):
        # Check if user is OAuth user
        token_data = None
        try:
            if user.get("google_id"):
                token_data = storage.get_token(user["google_id"])
        except Exception:
            pass

        if token_data and token_data.get("refresh_token"):
            raise HTTPException(
                status_code=400,
                detail="This account uses Google Sign-In. No password is needed. Please sign in with Google."
            )

    # Generate reset token
    reset_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    # Get user_id for token (security: tie token to specific user account)
    user_id = user.get("google_id") or user.get("email")

    # Save reset token
    try:
        storage.create_password_reset_token(
            user_id=user_id,
            email=request.email,
            token=reset_token,
            expires_at=expires_at.isoformat()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create reset token: {exc}") from exc

    # Send password reset email via SendGrid
    email_sent = email_sendgrid.send_password_reset_email(
        to_email=request.email,
        reset_token=reset_token
    )

    if not email_sent:
        # Email failed but don't reveal details to user for security
        # Token was still saved, so user can use it if they have it
        pass

    return {
        "message": "If an account exists with this email, a password reset link has been sent."
    }


@router.post("/reset-password")
def reset_password(request: ResetPasswordRequest):
    """
    Reset password using a valid reset token.
    """
    # Get reset token
    token_data = storage.get_password_reset_token(request.token)
    if not token_data:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    # Check if token is expired
    expires_at = datetime.fromisoformat(token_data["expires_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=400, detail="Reset token has expired")

    # Get user by email
    email = token_data["email"]
    user = storage.get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # SECURITY: Verify token belongs to this specific user account
    # This prevents using old tokens after account deletion/recreation
    current_user_id = user.get("google_id") or user.get("email")
    token_user_id = token_data.get("user_id")

    if token_user_id != current_user_id:
        raise HTTPException(
            status_code=400,
            detail="Invalid reset token. This may happen if your account was recreated. Please request a new password reset."
        )

    # Hash new password
    new_password_hash = hash_password(request.new_password)

    # Update user password
    try:
        user_id = user.get("google_id")
        if not user_id:
            raise HTTPException(status_code=500, detail="User record missing google_id")
        storage.update_user_password(user_id, new_password_hash)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update password: {exc}") from exc

    # Mark token as used
    try:
        storage.mark_reset_token_used(request.token)
    except Exception:
        pass  # Token cleanup is not critical

    return {"message": "Password reset successful. You can now sign in with your new password."}


@router.post("/validate-email-token")
def validate_email_token(request: EmailAuthRequest):
    """
    Validate email authentication token and return user_id for auto-login.
    Used when users click dashboard links in emails.
    """
    # Get email auth token
    token_data = storage.get_email_auth_token(request.token)
    if not token_data:
        raise HTTPException(status_code=400, detail="Invalid or expired email token")

    # Check if token is expired
    expires_at = datetime.fromisoformat(token_data["expires_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=400, detail="Email token has expired")

    # Get user_id from token
    user_id = token_data.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid token data")

    # Verify user exists
    user = storage.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Mark token as used
    try:
        storage.mark_email_auth_token_used(request.token)
    except Exception:
        pass  # Token cleanup is not critical

    # Return user_id for auto-login
    return {
        "user_id": user_id,
        "email": user.get("email"),
        "name": user.get("name")
    }


@router.get("/me")
def get_current_user(user_id: Optional[str] = None):
    """
    Get the current authenticated user's profile.
    Frontend should pass user_id as query param since we don't use Bearer tokens.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id query parameter required")

    user = storage.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if user has calendar connected (has refresh_token in tokens table)
    calendar_connected = False
    try:
        token_data = storage.get_token(user_id)
        if token_data and token_data.get("refresh_token"):
            calendar_connected = True
    except Exception:
        pass  # If token lookup fails, just assume not connected

    # Check if user has Microsoft calendar connected
    microsoft_calendar_connected = is_microsoft_connected(user_id)

    # Return user profile with all fields including email
    return {
        "user_id": user.get("google_id"),
        "id": user.get("google_id"),
        "email": user.get("email"),
        "name": user.get("name"),
        "picture_url": user.get("picture_url"),
        "profession": user.get("profession"),
        "age": user.get("age"),
        "short_term_goal": user.get("short_term_goal"),
        "timezone": user.get("timezone", "UTC"),
        "insight_time": user.get("insight_time", "08:00"),
        "calendar_connected": calendar_connected,
        "microsoft_calendar_connected": microsoft_calendar_connected
    }


@router.post("/checkins")
def save_checkin(checkin: CheckinRequest, user_id: str):
    """
    Save daily check-in data (sleep, energy, priority).
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id query parameter required")

    # Verify user exists
    user = storage.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    checkin_payload = {
        "user_id": user_id,
        "date": checkin.date,
        "sleep_hours": checkin.sleep_hours,
        "energy_level": checkin.energy_level,
        "priority": checkin.priority,
        "completed_priority": checkin.completed_priority,
        "disruption": checkin.disruption,
        "disruption_detail": checkin.disruption_detail,
        "late_start": checkin.late_start,
        "started_at": checkin.started_at,
    }

    try:
        storage.upsert_checkin(checkin_payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Check-in save failed: {exc}") from exc

    return {"message": "Check-in saved successfully", "date": checkin.date}


@router.get("/checkins/{user_id}")
def get_checkin(user_id: str, date: str):
    """
    Get check-in data for a specific date.
    Query param: date (YYYY-MM-DD format)
    """
    if not date:
        raise HTTPException(status_code=400, detail="date query parameter required")

    try:
        checkin_data = storage.get_checkin(user_id, date)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Check-in fetch failed: {exc}") from exc

    if not checkin_data:
        return {"user_id": user_id, "date": date, "exists": False}

    return {
        "user_id": user_id,
        "date": date,
        "exists": True,
        "sleep_hours": checkin_data.get("sleep_hours"),
        "energy_level": checkin_data.get("energy_level"),
        "priority": checkin_data.get("priority"),
        "completed_priority": checkin_data.get("completed_priority"),
        "disruption": checkin_data.get("disruption"),
        "disruption_detail": checkin_data.get("disruption_detail"),
        "late_start": checkin_data.get("late_start"),
        "started_at": checkin_data.get("started_at"),
        "evening_completed_at": checkin_data.get("evening_completed_at"),
        "rest_of_day_plan": checkin_data.get("rest_of_day_plan"),
    }


@router.post("/checkins/evening")
def save_evening_checkin(evening_checkin: EveningCheckinRequest, user_id: str):
    """
    Save evening check-in data (completed priority, disruption).
    This endpoint updates the existing checkin record for the day.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id query parameter required")

    # Verify user exists
    user = storage.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Verify morning check-in exists (either regular check-in with priority OR late-day check-in)
    existing_checkin = storage.get_checkin(user_id, evening_checkin.date)

    # Debug logging
    print(f"\n{'='*60}")
    print(f"[Evening Check-in DEBUG] User: {user_id}")
    print(f"[Evening Check-in DEBUG] Date: {evening_checkin.date}")
    print(f"[Evening Check-in DEBUG] Existing check-in found: {existing_checkin is not None}")

    if existing_checkin:
        print(f"[Evening Check-in DEBUG] Check-in keys: {list(existing_checkin.keys())}")
        print(f"[Evening Check-in DEBUG] Priority value: {existing_checkin.get('priority')}")
        print(f"[Evening Check-in DEBUG] Late start value: {existing_checkin.get('late_start')}")
        print(f"[Evening Check-in DEBUG] Rest of day plan exists: {bool(existing_checkin.get('rest_of_day_plan'))}")
    print(f"{'='*60}\n")

    has_priority = existing_checkin and existing_checkin.get("priority")
    has_late_start = existing_checkin and existing_checkin.get("late_start")
    has_rest_of_day_plan = existing_checkin and existing_checkin.get("rest_of_day_plan")

    if not existing_checkin or (not has_priority and not has_late_start and not has_rest_of_day_plan):
        error_detail = "Morning check-in required before evening check-in"
        if existing_checkin:
            error_detail += f" (found check-in but missing required fields: priority={has_priority}, late_start={has_late_start}, plan={bool(has_rest_of_day_plan)})"
        raise HTTPException(
            status_code=400,
            detail=error_detail
        )

    # Validation removed: disruption can be true with null detail
    # This happens when user selects "Other" and hasn't typed the detail yet

    # Build evening check-in payload
    # Only set evening_completed_at when BOTH questions are answered
    is_fully_complete = (
        (evening_checkin.completed_priority is True or evening_checkin.completed_priority == 'partial') or
        (evening_checkin.completed_priority is False and evening_checkin.disruption is not None)
    )

    evening_payload = {
        "user_id": user_id,
        "date": evening_checkin.date,
        "completed_priority": evening_checkin.completed_priority,
        "disruption": evening_checkin.disruption,
        "disruption_detail": evening_checkin.disruption_detail,
    }

    # Set or clear completion timestamp
    if is_fully_complete:
        evening_payload["evening_completed_at"] = datetime.now(timezone.utc).isoformat()
    else:
        # IMPORTANT: Clear existing timestamp when saving incomplete data
        # This handles the case where user previously completed, then edits their answer
        evening_payload["evening_completed_at"] = None

    try:
        storage.upsert_checkin(evening_payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Evening check-in save failed: {exc}") from exc

    return {"message": "Evening check-in saved successfully", "date": evening_checkin.date}


@router.get("/checkins/evening/{user_id}")
def get_evening_checkin_status(user_id: str, date: str):
    """
    Check if evening check-in is completed for a specific date.
    Returns: { "completed": true/false, "completed_at": timestamp or null }
    """
    if not date:
        raise HTTPException(status_code=400, detail="date query parameter required")

    try:
        checkin_data = storage.get_checkin(user_id, date)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Check-in fetch failed: {exc}") from exc

    if not checkin_data:
        return {"user_id": user_id, "date": date, "completed": False, "completed_at": None}

    evening_completed = checkin_data.get("evening_completed_at") is not None

    return {
        "user_id": user_id,
        "date": date,
        "completed": evening_completed,
        "completed_at": checkin_data.get("evening_completed_at"),
    }


@router.post("/unsubscribe")
def unsubscribe_from_emails(request: UnsubscribeRequest):
    """
    Unsubscribe user from daily insight emails using a secure token.
    Sets email_notifications_enabled = False for the user.
    """
    # Get unsubscribe token
    token_data = storage.get_unsubscribe_token(request.token)
    if not token_data:
        raise HTTPException(status_code=400, detail="Invalid or expired unsubscribe link")

    # Check if token is expired
    expires_at = datetime.fromisoformat(token_data["expires_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=400, detail="This unsubscribe link has expired")

    # Get user_id from token
    user_id = token_data.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid token data")

    # Verify user exists
    user = storage.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update email preferences
    try:
        storage.update_email_preferences(user_id, enabled=False)
        print(f"📧 User {user.get('email')} unsubscribed from email notifications via token")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update email preferences: {exc}") from exc

    # Mark token as used
    try:
        storage.mark_unsubscribe_token_used(request.token)
    except Exception:
        pass  # Token cleanup is not critical

    return {
        "message": "You've been unsubscribed from daily insight emails. You can re-enable them anytime in your settings.",
        "success": True
    }


@router.get("/unsubscribe/{token}")
def unsubscribe_from_emails_get(token: str):
    """
    One-click unsubscribe from email link (GET request).
    Validates token and disables email notifications.
    """
    # Get unsubscribe token
    token_data = storage.get_unsubscribe_token(token)
    if not token_data:
        raise HTTPException(status_code=400, detail="Invalid or expired unsubscribe link")

    # Check if token is expired
    expires_at = datetime.fromisoformat(token_data["expires_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=400, detail="This unsubscribe link has expired")

    # Get user_id from token
    user_id = token_data.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid token data")

    # Verify user exists
    user = storage.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update email preferences
    try:
        storage.update_email_preferences(user_id, enabled=False)
        print(f"📧 User {user.get('email')} unsubscribed from email notifications via GET link")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update email preferences: {exc}") from exc

    # Mark token as used
    try:
        storage.mark_unsubscribe_token_used(token)
    except Exception:
        pass  # Token cleanup is not critical

    return {
        "message": "You've been unsubscribed from daily insight emails. You can re-enable them anytime in your settings.",
        "success": True
    }


@router.get("/email-preferences/{user_id}")
def get_email_preferences(user_id: str):
    """
    Get current email notification preferences for a user.
    Used by the preferences management page.
    """
    user = storage.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "user_id": user_id,
        "email_notifications_enabled": user.get("email_notifications_enabled", True),
        "email": user.get("email"),
        "name": user.get("name")
    }


@router.put("/email-preferences/{user_id}")
def update_email_preferences_endpoint(user_id: str, request: dict):
    """
    Update email notification preferences.
    Allows users to re-enable emails from the preferences page.

    Request body: { "email_notifications_enabled": true/false }
    """
    user = storage.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    enabled = request.get("email_notifications_enabled")
    if enabled is None:
        raise HTTPException(status_code=400, detail="email_notifications_enabled is required")

    try:
        storage.update_email_preferences(user_id, enabled=enabled)
        action = "enabled" if enabled else "disabled"
        print(f"📧 User {user.get('email')} {action} email notifications")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update preferences: {exc}") from exc

    return {
        "success": True,
        "message": f"Email notifications {'enabled' if enabled else 'disabled'}",
        "email_notifications_enabled": enabled
    }


@router.delete("/admin/delete-user/{user_id}")
def admin_delete_user(user_id: str, confirm: str):
    """
    ADMIN ONLY: Completely delete a user and all associated data.
    Requires confirm=DELETE_ALL to prevent accidental deletion.
    """
    if confirm != "DELETE_ALL":
        raise HTTPException(
            status_code=400,
            detail="Must pass confirm=DELETE_ALL to delete user"
        )

    try:
        deleted_items = []

        # Delete OAuth token
        try:
            storage.delete_token(user_id)
            deleted_items.append("token")
            print(f"[Admin] Deleted token for user {user_id}")
        except Exception as e:
            print(f"[Admin] Token delete failed (may not exist): {e}")

        # Delete checkins (use raw SQL since storage might not have delete_checkins)
        try:
            if storage._use_supabase():
                from db.supabase_client import supabase_client
                from core.config import settings
                supabase_client.table("checkins").delete().eq("user_id", user_id).execute()
            else:
                from db import local_db
                local_db.ensure_local_schema()
                with local_db._connect() as conn:
                    conn.execute("DELETE FROM checkins WHERE user_id = ?", (user_id,))
                    conn.commit()
            deleted_items.append("checkins")
            print(f"[Admin] Deleted checkins for user {user_id}")
        except Exception as e:
            print(f"[Admin] Checkins delete failed: {e}")

        # Delete insights cache (database)
        try:
            if storage._use_supabase():
                from db.supabase_client import supabase_client
                supabase_client.table("insights_cache").delete().eq("user_id", user_id).execute()
            else:
                from db import local_db
                with local_db._connect() as conn:
                    conn.execute("DELETE FROM insights_cache WHERE user_id = ?", (user_id,))
                    conn.commit()
            deleted_items.append("insights_cache")
            print(f"[Admin] Deleted insights cache from database for user {user_id}")
        except Exception as e:
            print(f"[Admin] Insights cache delete failed: {e}")

        # Clear in-memory cache (Python dict in recommendations.py)
        try:
            from api.recommendations import clear_user_cache
            cleared_count = clear_user_cache(user_id)
            if cleared_count > 0:
                deleted_items.append(f"in_memory_cache({cleared_count})")
        except Exception as e:
            print(f"[Admin] In-memory cache clear failed: {e}")

        # Delete calendar events
        try:
            if storage._use_supabase():
                from db.supabase_client import supabase_client
                from core.config import settings
                supabase_client.table(settings.SUPABASE_EVENTS_TABLE).delete().eq("user_id", user_id).execute()
            else:
                from db import local_db
                with local_db._connect() as conn:
                    conn.execute("DELETE FROM calendar_events WHERE user_id = ?", (user_id,))
                    conn.commit()
            deleted_items.append("calendar_events")
            print(f"[Admin] Deleted calendar events for user {user_id}")
        except Exception as e:
            print(f"[Admin] Calendar events delete failed: {e}")

        # Delete user (this also handles password reset tokens via storage.delete_user)
        storage.delete_user(user_id)
        deleted_items.append("user")
        print(f"[Admin] Deleted user {user_id}")

        return {
            "message": f"User {user_id} and all associated data deleted successfully",
            "user_id": user_id,
            "deleted": deleted_items
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete user: {exc}"
        ) from exc


# ─── Microsoft Calendar Integration ──────────────────────────────────

def _build_microsoft_auth_url(state: str) -> str:
    """Build Microsoft OAuth authorization URL."""
    params = {
        "client_id": settings.MICROSOFT_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
        "response_mode": "query",
        "scope": settings.MICROSOFT_SCOPES,
        "state": state,
    }
    return f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize?{urlencode(params)}"


@router.get("/microsoft/login")
def microsoft_login(request: Request, user_id: Optional[str] = None):
    """
    Initiate Microsoft OAuth flow for work calendar access.

    Query params:
        user_id: CelestiOS user ID (google_id) to associate the token with
    """
    if not settings.MICROSOFT_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Microsoft client ID not configured")

    if not user_id:
        raise HTTPException(status_code=400, detail="user_id parameter required")

    # Create state with user_id for callback
    state = _state_serializer().dumps({
        "nonce": secrets.token_urlsafe(16),
        "user_id": user_id,
        "provider": "microsoft"
    })

    auth_url = _build_microsoft_auth_url(state)

    accepts_html = "text/html" in request.headers.get("accept", "")
    if accepts_html:
        return RedirectResponse(auth_url)
    return {"auth_url": auth_url}


@router.get("/microsoft/callback")
async def microsoft_callback(code: str, state: Optional[str] = None):
    """
    Handle Microsoft OAuth callback.
    Exchanges authorization code for access token and stores it.
    """
    if not state:
        raise HTTPException(status_code=400, detail="Missing OAuth state")

    try:
        state_data = _state_serializer().loads(state, max_age=settings.OAUTH_STATE_MAX_AGE_SECONDS)
    except SignatureExpired as exc:
        raise HTTPException(status_code=400, detail="OAuth state expired") from exc
    except BadSignature as exc:
        raise HTTPException(status_code=400, detail="Invalid OAuth state") from exc

    user_id = state_data.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user_id in state")

    # Verify user exists
    user = storage.get_user(user_id)
    if not user:
        return RedirectResponse(_frontend_redirect("/integrations", {"microsoft": "user_not_found"}))

    # Exchange authorization code for tokens
    token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    data = {
        "client_id": settings.MICROSOFT_CLIENT_ID,
        "client_secret": settings.MICROSOFT_CLIENT_SECRET,
        "code": code,
        "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
        "grant_type": "authorization_code",
        "scope": settings.MICROSOFT_SCOPES
    }

    if not settings.MICROSOFT_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Microsoft client secret not configured")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data)
            token_data = response.json()

            if response.status_code != 200 or "error" in token_data:
                error_desc = token_data.get("error_description", "Unknown error")
                print(f"[Microsoft] Token exchange failed: {error_desc}")
                return RedirectResponse(_frontend_redirect("/settings", {"microsoft": "error"}))

            access_token = token_data.get("access_token")
            refresh_token = token_data.get("refresh_token")
            expires_in = token_data.get("expires_in", 3600)
            scope = token_data.get("scope", settings.MICROSOFT_SCOPES)

            if not access_token:
                return RedirectResponse(_frontend_redirect("/settings", {"microsoft": "error"}))

            # Store tokens in database
            expires_at = int(time.time()) + expires_in
            token_payload = {
                "user_id": user_id,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at,
                "scope": scope,
                "connected_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }

            print(f"[Microsoft] Attempting to save token for user {user_id}")
            print(f"[Microsoft] Token payload keys: {list(token_payload.keys())}")

            try:
                storage.store_microsoft_token(token_payload)
                print(f"[Microsoft] ✅ Token save call completed")

                # Verify token was actually saved
                saved_token = storage.get_microsoft_token(user_id)
                if saved_token:
                    print(f"[Microsoft] ✅ Token verified in database for user {user_id}")
                else:
                    print(f"[Microsoft] ❌ WARNING: Token save succeeded but retrieval failed for user {user_id}")
            except Exception as exc:
                print(f"[Microsoft] ❌ ERROR saving token: {exc}")
                import traceback
                traceback.print_exc()
                raise

            print(f"[Microsoft] Calendar connected successfully for user {user_id}")

            # Redirect to integrations page with success message
            return RedirectResponse(_frontend_redirect("/integrations", {"microsoft": "connected"}))

    except httpx.HTTPError as exc:
        print(f"[Microsoft] HTTP error during token exchange: {exc}")
        return RedirectResponse(_frontend_redirect("/integrations", {"microsoft": "error"}))
    except Exception as exc:
        print(f"[Microsoft] Unexpected error: {exc}")
        return RedirectResponse(_frontend_redirect("/integrations", {"microsoft": "error"}))


@router.get("/microsoft/status")
async def microsoft_status(user_id: str):
    """
    Check if user has Microsoft work calendar connected.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id query parameter required")

    try:
        connected = is_microsoft_connected(user_id)
        return {"connected": connected}
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to check Microsoft calendar status: {exc}"
        ) from exc


@router.post("/microsoft/disconnect")
async def microsoft_disconnect(user_id: str):
    """
    Disconnect Microsoft work calendar.
    Deletes stored OAuth tokens.
    """
    try:
        # Verify user exists
        user = storage.get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Delete Microsoft token
        storage.delete_microsoft_token(user_id)
        print(f"[Microsoft] Calendar disconnected for user {user_id}")

        return {"message": "Microsoft calendar disconnected successfully"}

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to disconnect Microsoft calendar: {exc}"
        ) from exc


@router.get("/microsoft/status")
async def microsoft_status(user_id: str):
    """
    Check if user has connected their Microsoft work calendar.

    Returns:
        connected: bool - True if Microsoft calendar is connected
        expires_at: int - Unix timestamp when token expires (if connected)
    """
    try:
        token_data = storage.get_microsoft_token(user_id)

        if not token_data:
            return {"connected": False}

        return {
            "connected": True,
            "expires_at": token_data.get("expires_at"),
            "connected_at": token_data.get("connected_at"),
            "scope": token_data.get("scope")
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to check Microsoft status: {exc}"
        ) from exc
