"""
Check-in functionality tests - covers morning check-in save/load and data persistence.
"""
import pytest
from datetime import date, timedelta


@pytest.mark.checkin
@pytest.mark.critical
class TestMorningCheckin:
    """Test morning check-in save and retrieve functionality."""

    def test_save_checkin_success(self, client, test_user_created, today_str):
        """Test saving a new check-in."""
        checkin_data = {
            "user_id": test_user_created["user_id"],
            "date": today_str,
            "sleep_hours": "7",
            "energy_level": "medium",
            "priority": "Complete test suite"
        }

        response = client.post("/auth/checkins", json=checkin_data)

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Check-in saved successfully"

    def test_save_checkin_update_existing(self, client, test_user_created, today_str):
        """Test updating an existing check-in (upsert behavior)."""
        user_id = test_user_created["user_id"]

        # Save initial check-in
        initial_data = {
            "user_id": user_id,
            "date": today_str,
            "sleep_hours": "6",
            "energy_level": "low",
            "priority": "Initial priority"
        }
        client.post("/auth/checkins", json=initial_data)

        # Update check-in
        updated_data = {
            "user_id": user_id,
            "date": today_str,
            "sleep_hours": "8",
            "energy_level": "high",
            "priority": "Updated priority"
        }
        response = client.post("/auth/checkins", json=updated_data)

        assert response.status_code == 200

        # Verify update persisted
        get_response = client.get(f"/auth/checkins/{user_id}?date={today_str}")
        assert get_response.status_code == 200
        data = get_response.json()
        assert data["sleep_hours"] == "8"
        assert data["energy_level"] == "high"
        assert data["priority"] == "Updated priority"

    def test_get_checkin_exists(self, client, test_user_created, today_str):
        """Test retrieving an existing check-in."""
        user_id = test_user_created["user_id"]

        # Save check-in
        checkin_data = {
            "user_id": user_id,
            "date": today_str,
            "sleep_hours": "7",
            "energy_level": "medium",
            "priority": "Test priority"
        }
        client.post("/auth/checkins", json=checkin_data)

        # Retrieve check-in
        response = client.get(f"/auth/checkins/{user_id}?date={today_str}")

        assert response.status_code == 200
        data = response.json()
        assert data["exists"] is True
        assert data["sleep_hours"] == "7"
        assert data["energy_level"] == "medium"
        assert data["priority"] == "Test priority"
        assert data["date"] == today_str

    def test_get_checkin_not_exists(self, client, test_user_created, today_str):
        """Test retrieving a non-existent check-in."""
        response = client.get(f"/auth/checkins/{test_user_created['user_id']}?date={today_str}")

        assert response.status_code == 200
        data = response.json()
        assert data["exists"] is False

    def test_get_checkin_different_date(self, client, test_user_created, today_str):
        """Test that check-ins are date-specific."""
        user_id = test_user_created["user_id"]
        yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')

        # Save check-in for today
        today_data = {
            "user_id": user_id,
            "date": today_str,
            "sleep_hours": "7",
            "energy_level": "medium",
            "priority": "Today's priority"
        }
        client.post("/auth/checkins", json=today_data)

        # Save check-in for yesterday
        yesterday_data = {
            "user_id": user_id,
            "date": yesterday,
            "sleep_hours": "6",
            "energy_level": "low",
            "priority": "Yesterday's priority"
        }
        client.post("/auth/checkins", json=yesterday_data)

        # Retrieve today's check-in
        today_response = client.get(f"/auth/checkins/{user_id}?date={today_str}")
        assert today_response.json()["priority"] == "Today's priority"

        # Retrieve yesterday's check-in
        yesterday_response = client.get(f"/auth/checkins/{user_id}?date={yesterday}")
        assert yesterday_response.json()["priority"] == "Yesterday's priority"

    def test_checkin_user_isolation(self, client, test_user_created, test_user_with_google, today_str):
        """Test that check-ins are user-specific."""
        # Save check-in for user 1
        user1_data = {
            "user_id": test_user_created["user_id"],
            "date": today_str,
            "sleep_hours": "7",
            "energy_level": "medium",
            "priority": "User 1 priority"
        }
        client.post("/auth/checkins", json=user1_data)

        # Save check-in for user 2
        user2_data = {
            "user_id": test_user_with_google["google_id"],
            "date": today_str,
            "sleep_hours": "8",
            "energy_level": "high",
            "priority": "User 2 priority"
        }
        client.post("/auth/checkins", json=user2_data)

        # Verify user 1's check-in
        user1_response = client.get(f"/auth/checkins/{test_user_created['user_id']}?date={today_str}")
        assert user1_response.json()["priority"] == "User 1 priority"

        # Verify user 2's check-in
        user2_response = client.get(f"/auth/checkins/{test_user_with_google['google_id']}?date={today_str}")
        assert user2_response.json()["priority"] == "User 2 priority"


@pytest.mark.checkin
class TestCheckinValidation:
    """Test check-in validation and edge cases."""

    def test_save_checkin_missing_user_id(self, client, today_str):
        """Test save check-in fails without user_id."""
        response = client.post("/auth/checkins", json={
            "date": today_str,
            "sleep_hours": "7",
            "priority": "Test"
        })

        assert response.status_code == 422  # Validation error

    def test_save_checkin_missing_date(self, client, test_user_created):
        """Test save check-in fails without date."""
        response = client.post("/auth/checkins", json={
            "user_id": test_user_created["user_id"],
            "sleep_hours": "7",
            "priority": "Test"
        })

        assert response.status_code == 422  # Validation error

    def test_save_checkin_partial_data(self, client, test_user_created, today_str):
        """Test saving check-in with partial data (only priority)."""
        response = client.post("/auth/checkins", json={
            "user_id": test_user_created["user_id"],
            "date": today_str,
            "priority": "Just priority"
        })

        assert response.status_code == 200

        # Verify partial save worked
        get_response = client.get(f"/auth/checkins/{test_user_created['user_id']}?date={today_str}")
        data = get_response.json()
        assert data["priority"] == "Just priority"
        assert data.get("sleep_hours") is None
        assert data.get("energy_level") is None

    def test_get_checkin_invalid_user_id(self, client, today_str):
        """Test get check-in with non-existent user."""
        response = client.get(f"/auth/checkins/nonexistent_user?date={today_str}")

        assert response.status_code == 200
        assert response.json()["exists"] is False


@pytest.mark.checkin
@pytest.mark.regression
class TestCheckinPersistence:
    """
    REGRESSION TEST: Check-in data must persist across sessions.
    This prevents the bug where data disappeared in new incognito windows.
    """

    def test_checkin_persists_across_sessions(self, client, test_user_created, today_str):
        """
        Test that check-in data persists in backend, not just localStorage.
        Simulates new incognito window by making separate requests.
        """
        user_id = test_user_created["user_id"]

        # Session 1: Save check-in
        save_data = {
            "user_id": user_id,
            "date": today_str,
            "sleep_hours": "7",
            "energy_level": "medium",
            "priority": "Complete work"
        }
        save_response = client.post("/auth/checkins", json=save_data)
        assert save_response.status_code == 200

        # Session 2: Retrieve check-in (simulating new incognito window)
        get_response = client.get(f"/auth/checkins/{user_id}?date={today_str}")
        assert get_response.status_code == 200

        data = get_response.json()
        assert data["exists"] is True
        assert data["sleep_hours"] == "7"
        assert data["energy_level"] == "medium"
        assert data["priority"] == "Complete work"
