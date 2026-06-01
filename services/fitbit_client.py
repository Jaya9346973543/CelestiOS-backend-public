"""Fitbit API Client - fetches health data from Fitbit Web API."""
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from core.config import settings
from db.storage import save_health_connection, get_health_connection, save_health_data
import logging
import base64

logger = logging.getLogger(__name__)


class FitbitClient:
    """Client for interacting with Fitbit Web API."""

    BASE_URL = "https://api.fitbit.com"

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.connection = get_health_connection(user_id, "fitbit")
        if not self.connection:
            raise ValueError(f"No Fitbit connection found for user {user_id}")

    async def _get_valid_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        # Check if token is expired or about to expire (within 5 minutes)
        expires_at = self.connection.get("expires_at", 0)
        current_time = int(datetime.now(timezone.utc).timestamp())

        if expires_at - current_time < 300:  # Less than 5 minutes until expiry
            await self._refresh_token()

        return self.connection["access_token"]

    async def _refresh_token(self) -> None:
        """Refresh the Fitbit access token."""
        refresh_token = self.connection.get("refresh_token")
        if not refresh_token:
            raise ValueError("No refresh token available")

        # Fitbit requires Basic auth with base64 encoded client_id:client_secret
        credentials = f"{settings.FITBIT_CLIENT_ID}:{settings.FITBIT_CLIENT_SECRET}"
        b64_credentials = base64.b64encode(credentials.encode()).decode()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/oauth2/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={
                    "Authorization": f"Basic {b64_credentials}",
                    "Content-Type": "application/x-www-form-urlencoded"
                }
            )

            if response.status_code != 200:
                logger.error(f"Token refresh failed: {response.text}")
                raise Exception("Failed to refresh Fitbit token")

            token_data = response.json()

            # Update connection with new tokens
            updated_connection = {
                **self.connection,
                "access_token": token_data["access_token"],
                "refresh_token": token_data.get("refresh_token", refresh_token),
                "expires_at": int(datetime.now(timezone.utc).timestamp()) + token_data.get("expires_in", 28800),
            }

            save_health_connection(updated_connection)
            self.connection = updated_connection

    async def _make_request(self, endpoint: str) -> Dict[str, Any]:
        """Make authenticated request to Fitbit API."""
        token = await self._get_valid_token()

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}{endpoint}",
                headers={"Authorization": f"Bearer {token}"}
            )

            if response.status_code != 200:
                logger.error(f"Fitbit API request failed: {response.text}")
                raise Exception(f"Fitbit API error: {response.status_code}")

            return response.json()

    async def fetch_sleep(self, date: str) -> Dict[str, Any]:
        """Fetch sleep data for a specific date."""
        return await self._make_request(f"/1.2/user/-/sleep/date/{date}.json")

    async def fetch_heart_rate(self, date: str) -> Dict[str, Any]:
        """Fetch heart rate data for a specific date."""
        return await self._make_request(f"/1/user/-/activities/heart/date/{date}/1d.json")

    async def fetch_hrv(self, date: str) -> Dict[str, Any]:
        """Fetch HRV data for a specific date."""
        try:
            return await self._make_request(f"/1/user/-/hrv/date/{date}.json")
        except Exception as e:
            logger.warning(f"HRV data not available for {date}: {str(e)}")
            return {}

    async def fetch_activity(self, date: str) -> Dict[str, Any]:
        """Fetch activity summary for a specific date."""
        return await self._make_request(f"/1/user/-/activities/date/{date}.json")

    def _derive_readiness_score(self, sleep_data: dict, hr_data: dict, hrv_data: dict) -> Optional[int]:
        """
        Derive a readiness-like score from Fitbit data.
        Fitbit doesn't have a native "readiness score" like Oura, so we calculate one.

        Scoring logic (0-100):
        - Sleep quality (0-40 points): Based on sleep efficiency and duration
        - Resting heart rate (0-30 points): Lower is better (relative to baseline)
        - HRV (0-30 points): Higher is better
        """
        score = 0

        # Sleep quality component (0-40 points)
        sleep_summary = sleep_data.get("sleep", [{}])[0] if sleep_data.get("sleep") else {}
        sleep_efficiency = sleep_summary.get("efficiency", 0)
        sleep_minutes = sleep_summary.get("duration", 0) / 60000  # Convert ms to minutes

        # Sleep efficiency contributes up to 25 points
        score += min(25, (sleep_efficiency / 100) * 25)

        # Sleep duration contributes up to 15 points (optimal: 7-9 hours)
        if 420 <= sleep_minutes <= 540:  # 7-9 hours
            score += 15
        elif 360 <= sleep_minutes < 420 or 540 < sleep_minutes <= 600:
            score += 10
        else:
            score += 5

        # Resting heart rate component (0-30 points)
        # Assume typical RHR baseline of 60 bpm
        rhr = hr_data.get("activities-heart", [{}])[0].get("value", {}).get("restingHeartRate")
        if rhr:
            if rhr < 60:
                score += 30
            elif rhr < 70:
                score += 20
            elif rhr < 80:
                score += 10
            else:
                score += 5

        # HRV component (0-30 points)
        hrv_avg = hrv_data.get("hrv", [{}])[0].get("value", {}).get("dailyRmssd")
        if hrv_avg:
            if hrv_avg > 50:
                score += 30
            elif hrv_avg > 30:
                score += 20
            elif hrv_avg > 20:
                score += 10
            else:
                score += 5

        return min(100, int(score)) if score > 0 else None

    async def sync_daily_data(self, date: str) -> Dict[str, Any]:
        """
        Sync all daily health data for a specific date.
        Returns the aggregated health data saved to database.
        """
        # Fetch all data types for the date
        sleep_data = await self.fetch_sleep(date)
        hr_data = await self.fetch_heart_rate(date)
        hrv_data = await self.fetch_hrv(date)
        activity_data = await self.fetch_activity(date)

        # Extract main sleep record (Fitbit can have multiple sleep periods per day)
        main_sleep = sleep_data.get("sleep", [{}])[0] if sleep_data.get("sleep") else {}
        sleep_summary = sleep_data.get("summary", {})

        # Extract heart rate data
        hr_summary = hr_data.get("activities-heart", [{}])[0].get("value", {}) if hr_data.get("activities-heart") else {}
        resting_hr = hr_summary.get("restingHeartRate")

        # Extract HRV data
        hrv_summary = hrv_data.get("hrv", [{}])[0].get("value", {}) if hrv_data.get("hrv") else {}
        hrv_rmssd = hrv_summary.get("dailyRmssd")

        # Extract activity data
        activity_summary = activity_data.get("summary", {})

        # Derive readiness score
        readiness_score = self._derive_readiness_score(sleep_data, hr_data, hrv_data)

        # Map Fitbit data to our health_data schema
        health_payload = {
            "user_id": self.user_id,
            "date": date,
            "provider": "fitbit",

            # Sleep metrics
            "sleep_score": main_sleep.get("efficiency"),  # Fitbit sleep score/efficiency
            "sleep_duration_minutes": main_sleep.get("duration", 0) // 60000,  # Convert ms to minutes
            "deep_sleep_minutes": main_sleep.get("levels", {}).get("summary", {}).get("deep", {}).get("minutes"),
            "rem_sleep_minutes": main_sleep.get("levels", {}).get("summary", {}).get("rem", {}).get("minutes"),
            "light_sleep_minutes": main_sleep.get("levels", {}).get("summary", {}).get("light", {}).get("minutes"),
            "awake_time_minutes": main_sleep.get("levels", {}).get("summary", {}).get("wake", {}).get("minutes"),
            "sleep_efficiency": main_sleep.get("efficiency"),

            # Derived readiness score (Fitbit doesn't have native readiness)
            "readiness_score": readiness_score,

            # Heart rate and HRV
            "resting_heart_rate": resting_hr,
            "hrv_rmssd": hrv_rmssd,

            # Activity metrics
            "steps": activity_summary.get("steps"),
            "active_calories": activity_summary.get("caloriesOut"),
            "total_calories": activity_summary.get("caloriesOut"),
            "active_minutes": activity_summary.get("veryActiveMinutes", 0) + activity_summary.get("fairlyActiveMinutes", 0),

            # Store raw API responses for debugging
            "raw_data": {
                "sleep": sleep_data,
                "heart_rate": hr_data,
                "hrv": hrv_data,
                "activity": activity_data
            }
        }

        # Save to database
        save_health_data(health_payload)

        logger.info(f"Synced Fitbit data for user {self.user_id} on {date}")
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
                logger.error(f"Failed to sync Fitbit data for {date_str}: {str(e)}")

        return synced_dates
