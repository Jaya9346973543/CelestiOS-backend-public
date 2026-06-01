from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from typing import Optional
import httpx
from datetime import datetime, timezone
from urllib.parse import urlencode
from core.config import settings
from db.storage import save_health_connection, get_health_connection, delete_health_connection
from services.oura_client import OuraClient
from services.fitbit_client import FitbitClient
import secrets
import logging
import base64

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory state storage (replace with Redis in production)
_oauth_states = {}


# ============================================
# Helper Functions
# ============================================

def _frontend_redirect(path: str, params: Optional[dict] = None) -> str:
    """Build frontend URL with optional query params."""
    base_url = settings.FRONTEND_URL.rstrip("/")
    target = f"{base_url}{path}"
    if params:
        return f"{target}?{urlencode(params)}"
    return target


# ============================================
# Oura OAuth Endpoints
# ============================================

@router.get("/auth/oura/login")
async def oura_login(user_id: str):
    """Initiate Oura OAuth flow."""
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {"user_id": user_id, "provider": "oura"}

    auth_url = (
        f"{settings.OURA_API_BASE_URL}/oauth/authorize"
        f"?response_type=code"
        f"&client_id={settings.OURA_CLIENT_ID}"
        f"&redirect_uri={settings.OURA_REDIRECT_URI}"
        f"&scope=daily"
        f"&state={state}"
    )

    return RedirectResponse(url=auth_url)


@router.get("/auth/oura/callback")
async def oura_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None)
):
    """Handle Oura OAuth callback."""
    if error:
        logger.error(f"Oura OAuth error: {error}")
        return RedirectResponse(url=_frontend_redirect("/integrations", {"error": error}))

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    # Validate state
    state_data = _oauth_states.pop(state, None)
    if not state_data:
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    user_id = state_data["user_id"]

    # Exchange code for access token
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            f"{settings.OURA_API_BASE_URL}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.OURA_REDIRECT_URI,
                "client_id": settings.OURA_CLIENT_ID,
                "client_secret": settings.OURA_CLIENT_SECRET,
            }
        )

        if token_response.status_code != 200:
            logger.error(f"Oura token exchange failed: {token_response.text}")
            raise HTTPException(status_code=400, detail="Failed to exchange code for token")

        token_data = token_response.json()

    # Save connection to database
    connection_payload = {
        "user_id": user_id,
        "provider": "oura",
        "access_token": token_data["access_token"],
        "refresh_token": token_data.get("refresh_token"),
        "expires_at": int(datetime.now(timezone.utc).timestamp()) + token_data.get("expires_in", 86400),
        "scope": "daily",
        "connected_at": datetime.now(timezone.utc).isoformat(),
    }

    save_health_connection(connection_payload)

    # Auto-sync last 7 days of health data
    try:
        client = OuraClient(user_id)
        await client.sync_recent_days(days=7)
        logger.info(f"Auto-synced 7 days of Oura data for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to auto-sync Oura data: {str(e)}")
        # Don't fail OAuth if sync fails - connection is still saved

    # Redirect to integrations page with success (uses FRONTEND_URL from config)
    return RedirectResponse(url=_frontend_redirect("/integrations", {"connected": "oura"}))


# ============================================
# Fitbit OAuth Endpoints
# ============================================

@router.get("/auth/fitbit/login")
async def fitbit_login(user_id: str):
    """Initiate Fitbit OAuth flow."""
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {"user_id": user_id, "provider": "fitbit"}

    # Fitbit scopes: sleep, heartrate, activity, profile
    auth_url = (
        "https://www.fitbit.com/oauth2/authorize"
        f"?response_type=code"
        f"&client_id={settings.FITBIT_CLIENT_ID}"
        f"&redirect_uri={settings.FITBIT_REDIRECT_URI}"
        f"&scope=sleep%20heartrate%20activity%20profile"
        f"&state={state}"
    )

    return RedirectResponse(url=auth_url)


@router.get("/auth/fitbit/callback")
async def fitbit_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None)
):
    """Handle Fitbit OAuth callback."""
    if error:
        logger.error(f"Fitbit OAuth error: {error}")
        return RedirectResponse(url=_frontend_redirect("/integrations", {"error": error}))

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    # Validate state
    state_data = _oauth_states.pop(state, None)
    if not state_data:
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    user_id = state_data["user_id"]

    # Fitbit requires Basic auth with base64 encoded client_id:client_secret
    credentials = f"{settings.FITBIT_CLIENT_ID}:{settings.FITBIT_CLIENT_SECRET}"
    b64_credentials = base64.b64encode(credentials.encode()).decode()

    # Exchange code for access token
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://api.fitbit.com/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.FITBIT_REDIRECT_URI,
            },
            headers={
                "Authorization": f"Basic {b64_credentials}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
        )

        if token_response.status_code != 200:
            logger.error(f"Fitbit token exchange failed: {token_response.text}")
            raise HTTPException(status_code=400, detail="Failed to exchange code for token")

        token_data = token_response.json()

    # Save connection to database
    connection_payload = {
        "user_id": user_id,
        "provider": "fitbit",
        "access_token": token_data["access_token"],
        "refresh_token": token_data.get("refresh_token"),
        "expires_at": int(datetime.now(timezone.utc).timestamp()) + token_data.get("expires_in", 28800),
        "scope": token_data.get("scope"),
        "provider_user_id": token_data.get("user_id"),
        "connected_at": datetime.now(timezone.utc).isoformat(),
    }

    save_health_connection(connection_payload)

    # Auto-sync last 7 days of health data
    try:
        client = FitbitClient(user_id)
        await client.sync_recent_days(days=7)
        logger.info(f"Auto-synced 7 days of Fitbit data for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to auto-sync Fitbit data: {str(e)}")
        # Don't fail OAuth if sync fails - connection is still saved

    # Redirect to integrations page with success (uses FRONTEND_URL from config)
    return RedirectResponse(url=_frontend_redirect("/integrations", {"connected": "fitbit"}))


# ============================================
# Health Data Endpoints
# ============================================

@router.delete("/api/health/disconnect")
async def disconnect_health_device(user_id: str, provider: str):
    """Disconnect a health device."""
    try:
        delete_health_connection(user_id, provider)
        return {"message": f"{provider.capitalize()} disconnected successfully"}
    except Exception as e:
        logger.error(f"Failed to disconnect {provider}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to disconnect device")


@router.post("/api/health/sync")
async def sync_health_data(user_id: str, provider: str, date: Optional[str] = None):
    """
    Sync health data for a specific date (defaults to today).
    Supports: oura, fitbit
    """
    if provider not in ["oura", "fitbit"]:
        raise HTTPException(status_code=400, detail=f"Provider {provider} not yet supported")

    try:
        # Create appropriate client based on provider
        if provider == "oura":
            client = OuraClient(user_id)
        elif provider == "fitbit":
            client = FitbitClient(user_id)

        # Default to today if no date provided
        if not date:
            date = datetime.now(timezone.utc).date().isoformat()

        health_data = await client.sync_daily_data(date)

        return {
            "message": "Health data synced successfully",
            "provider": provider,
            "date": date,
            "readiness_score": health_data.get("readiness_score"),
            "sleep_score": health_data.get("sleep_score"),
            "activity_score": health_data.get("activity_score")
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to sync {provider} data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to sync health data: {str(e)}")


@router.post("/api/health/sync/recent")
async def sync_recent_health_data(user_id: str, provider: str, days: int = 7):
    """
    Sync health data for the last N days (default: 7).
    Supports: oura, fitbit
    """
    if provider not in ["oura", "fitbit"]:
        raise HTTPException(status_code=400, detail=f"Provider {provider} not yet supported")

    if days < 1 or days > 90:
        raise HTTPException(status_code=400, detail="Days must be between 1 and 90")

    try:
        # Create appropriate client based on provider
        if provider == "oura":
            client = OuraClient(user_id)
        elif provider == "fitbit":
            client = FitbitClient(user_id)

        synced_dates = await client.sync_recent_days(days)

        return {
            "message": f"Synced {len(synced_dates)} days of health data",
            "provider": provider,
            "synced_dates": synced_dates,
            "days_requested": days
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to sync {provider} recent data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to sync health data: {str(e)}")


@router.get("/api/health/status")
async def get_health_connection_status(user_id: str, provider: str):
    """Get connection status for a health device."""
    connection = get_health_connection(user_id, provider)

    if not connection:
        return {
            "connected": False,
            "provider": provider
        }

    return {
        "connected": True,
        "provider": provider,
        "connected_at": connection.get("connected_at"),
        "last_synced_at": connection.get("last_synced_at"),
        "scope": connection.get("scope")
    }


@router.get("/api/health/latest")
async def get_latest_health_data_endpoint(user_id: str, date: str):
    """
    Get the latest health data for a user on a specific date.
    Returns None if no data exists.
    """
    from db.storage import get_latest_health_data

    try:
        health_data = get_latest_health_data(user_id, date)

        if not health_data:
            return {
                "exists": False,
                "data": None
            }

        return {
            "exists": True,
            "data": {
                "provider": health_data.get("provider"),
                "readiness_score": health_data.get("readiness_score"),
                "sleep_score": health_data.get("sleep_score"),
                "sleep_duration_minutes": health_data.get("sleep_duration_minutes"),
                "sleep_duration_hours": health_data.get("sleep_duration_minutes") / 60 if health_data.get("sleep_duration_minutes") else None,
                "resting_heart_rate": health_data.get("resting_heart_rate"),
                "date": health_data.get("date")
            }
        }
    except Exception as e:
        logger.error(f"[Health] Failed to fetch health data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch health data: {str(e)}")


@router.post("/api/health/dummy-oura")
async def create_dummy_oura_data(user_id: str, date: Optional[str] = None):
    """
    Create dummy Oura health data for testing/demo purposes.
    This simulates having an Oura ring connected with realistic data.
    """
    from db.storage import save_health_data
    from datetime import date as date_module

    if not date:
        date = date_module.today().isoformat()

    # Realistic dummy Oura data
    dummy_data = {
        "user_id": user_id,
        "date": date,
        "provider": "oura",
        "readiness_score": 58,  # Low readiness for burnout detection testing
        "sleep_score": 72,
        "activity_score": 65,
        "sleep_duration_minutes": 360,  # 6 hours
        "deep_sleep_minutes": 85,
        "rem_sleep_minutes": 95,
        "light_sleep_minutes": 180,
        "resting_heart_rate": 62,
        "hrv": 38,
        "body_temperature_delta": -0.2,
        "synced_at": datetime.now(timezone.utc).isoformat()
    }

    try:
        save_health_data(dummy_data)
        logger.info(f"[Dummy Oura] Created dummy data for user {user_id} on {date}")

        return {
            "message": "Dummy Oura data created successfully",
            "data": {
                "readiness_score": dummy_data["readiness_score"],
                "sleep_duration_hours": dummy_data["sleep_duration_minutes"] / 60,
                "date": date
            }
        }
    except Exception as e:
        logger.error(f"[Dummy Oura] Failed to create dummy data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create dummy data: {str(e)}")
