"""Oura Ring API Client - fetches health data from Oura Cloud API v2."""
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from core.config import settings
from db.storage import save_health_connection, get_health_connection, save_health_data
import logging

logger = logging.getLogger(__name__)


class OuraClient:
    """Client for interacting with Oura Cloud API v2."""

    BASE_URL = "https://api.ouraring.com/v2/usercollection"

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.connection = get_health_connection(user_id, "oura")
        if not self.connection:
            raise ValueError(f"No Oura connection found for user {user_id}")

    async def _get_valid_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        # Check if token is expired or about to expire (within 5 minutes)
        expires_at = self.connection.get("expires_at", 0)
        current_time = int(datetime.now(timezone.utc).timestamp())

        if expires_at - current_time < 300:  # Less than 5 minutes until expiry
            await self._refresh_token()

        return self.connection["access_token"]

    async def _refresh_token(self) -> None:
        """Refresh the Oura access token."""
        refresh_token = self.connection.get("refresh_token")
        if not refresh_token:
            raise ValueError("No refresh token available")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.OURA_API_BASE_URL}/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": settings.OURA_CLIENT_ID,
                    "client_secret": settings.OURA_CLIENT_SECRET,
                }
            )

            if response.status_code != 200:
                logger.error(f"Token refresh failed: {response.text}")
                raise Exception("Failed to refresh Oura token")

            token_data = response.json()

            # Update connection with new tokens
            updated_connection = {
                **self.connection,
                "access_token": token_data["access_token"],
                "refresh_token": token_data.get("refresh_token", refresh_token),
                "expires_at": int(datetime.now(timezone.utc).timestamp()) + token_data.get("expires_in", 86400),
            }

            save_health_connection(updated_connection)
            self.connection = updated_connection

    async def _make_request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make authenticated request to Oura API."""
        token = await self._get_valid_token()

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/{endpoint}",
                params=params,
                headers={"Authorization": f"Bearer {token}"}
            )

            if response.status_code != 200:
                logger.error(f"Oura API request failed: {response.text}")
                raise Exception(f"Oura API error: {response.status_code}")

            return response.json()

    async def fetch_daily_readiness(self, start_date: str, end_date: str) -> list:
        """Fetch daily readiness data for date range."""
        data = await self._make_request("daily_readiness", {
            "start_date": start_date,
            "end_date": end_date
        })
        return data.get("data", [])

    async def fetch_daily_sleep(self, start_date: str, end_date: str) -> list:
        """Fetch daily sleep data for date range."""
        data = await self._make_request("daily_sleep", {
            "start_date": start_date,
            "end_date": end_date
        })
        return data.get("data", [])

    async def fetch_daily_activity(self, start_date: str, end_date: str) -> list:
        """Fetch daily activity data for date range."""
        data = await self._make_request("daily_activity", {
            "start_date": start_date,
            "end_date": end_date
        })
        return data.get("data", [])

    async def fetch_heart_rate(self, start_datetime: str, end_datetime: str) -> list:
        """Fetch heart rate data for datetime range."""
        data = await self._make_request("heartrate", {
            "start_datetime": start_datetime,
            "end_datetime": end_datetime
        })
        return data.get("data", [])

    async def sync_daily_data(self, date: str) -> Dict[str, Any]:
        """
        Sync all daily health data for a specific date.
        Returns the aggregated health data saved to database.
        """
        # Fetch all data types for the date
        readiness_data = await self.fetch_daily_readiness(date, date)
        sleep_data = await self.fetch_daily_sleep(date, date)
        activity_data = await self.fetch_daily_activity(date, date)

        # Get first record from each (should only be one per day)
        readiness = readiness_data[0] if readiness_data else {}
        sleep = sleep_data[0] if sleep_data else {}
        activity = activity_data[0] if activity_data else {}

        # Map Oura data to our health_data schema
        health_payload = {
            "user_id": self.user_id,
            "date": date,
            "provider": "oura",

            # Sleep metrics from sleep data
            "sleep_score": sleep.get("score"),
            "sleep_duration_minutes": sleep.get("contributors", {}).get("total_sleep_duration"),
            "deep_sleep_minutes": sleep.get("contributors", {}).get("deep_sleep_duration"),
            "rem_sleep_minutes": sleep.get("contributors", {}).get("rem_sleep_duration"),
            "light_sleep_minutes": sleep.get("contributors", {}).get("light_sleep_duration"),
            "awake_time_minutes": sleep.get("contributors", {}).get("awake_time"),
            "sleep_efficiency": sleep.get("contributors", {}).get("sleep_efficiency"),

            # Readiness score (key metric for energy-aware scheduling)
            "readiness_score": readiness.get("score"),

            # Heart rate and HRV from readiness contributors
            "resting_heart_rate": readiness.get("contributors", {}).get("resting_heart_rate"),
            "hrv_avg": readiness.get("contributors", {}).get("hrv_balance"),

            # Activity metrics
            "activity_score": activity.get("score"),
            "steps": activity.get("steps"),
            "active_calories": activity.get("active_calories"),
            "total_calories": activity.get("total_calories"),
            "active_minutes": activity.get("equivalent_walking_distance"),  # Oura uses different metric

            # Store raw API responses for debugging and future use
            "raw_data": {
                "readiness": readiness,
                "sleep": sleep,
                "activity": activity
            }
        }

        # Save to database
        save_health_data(health_payload)

        logger.info(f"Synced Oura data for user {self.user_id} on {date}")
        return health_payload

    async def sync_recent_days(self, days: int = 7) -> list:
        """
        Sync health data for the last N days.
        Returns list of synced dates.
        """
        synced_dates = []
        today = datetime.now(timezone.utc).date()

        for i in range(days):
            target_date = today - timedelta(days=i)
            date_str = target_date.isoformat()

            try:
                await self.sync_daily_data(date_str)
                synced_dates.append(date_str)
            except Exception as e:
                logger.error(f"Failed to sync Oura data for {date_str}: {str(e)}")

        return synced_dates
