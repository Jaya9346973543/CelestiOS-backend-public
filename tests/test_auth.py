"""
Authentication tests - covers signup, signin, OAuth, password reset.
Includes regression tests for today's security fixes.
"""
import pytest
from unittest.mock import patch


@pytest.mark.auth
@pytest.mark.critical
class TestManualAuth:
    """Test manual email/password authentication."""

    def test_signup_success(self, client, test_user_data):
        """Test successful user signup with email and password."""
        response = client.post("/auth/signup", json=test_user_data)

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Account created successfully"
        assert data["user_id"] == test_user_data["email"]
        assert data["email"] == test_user_data["email"]
        assert data["name"] == test_user_data["name"]

    def test_signup_duplicate_email(self, client, test_user_created):
        """Test that duplicate email signup is rejected."""
        # Try to signup again with same email
        response = client.post("/auth/signup", json={
            "email": test_user_created["email"],
            "password": "DifferentPass123!",
            "name": "Different Name"
        })

        assert response.status_code == 400
        assert "already registered" in response.json()["detail"].lower()

    def test_signin_success(self, client, test_user_created):
        """Test successful signin with correct credentials."""
        response = client.post("/auth/signin", json={
            "email": test_user_created["email"],
            "password": test_user_created["password"]
        })

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Sign in successful"
        assert data["user_id"] == test_user_created["user_id"]
        assert data["email"] == test_user_created["email"]

    def test_signin_wrong_password(self, client, test_user_created):
        """Test signin fails with wrong password."""
        response = client.post("/auth/signin", json={
            "email": test_user_created["email"],
            "password": "WrongPassword123!"
        })

        assert response.status_code == 401
        assert "invalid" in response.json()["detail"].lower()

    def test_signin_nonexistent_user(self, client):
        """Test signin fails for non-existent user."""
        response = client.post("/auth/signin", json={
            "email": "nonexistent@example.com",
            "password": "AnyPassword123!"
        })

        assert response.status_code == 401
        assert "invalid" in response.json()["detail"].lower()

    def test_signin_google_only_account_rejects_password(self, client, test_user_with_google):
        """Test that Google-only accounts cannot signin with password."""
        response = client.post("/auth/signin", json={
            "email": test_user_with_google["email"],
            "password": "AnyPassword123!"
        })

        assert response.status_code == 400
        assert "google sign-in" in response.json()["detail"].lower()


@pytest.mark.auth
@pytest.mark.critical
@pytest.mark.regression
class TestOAuthSecurity:
    """
    CRITICAL: Tests for OAuth security fixes implemented today.
    These must NEVER break.
    """

    def test_google_signup_blocks_existing_password_account(self, client, test_user_created, mock_google_oauth):
        """
        REGRESSION TEST: User with password account tries "Sign up with Google".
        Should be BLOCKED.

        This was Bug #1 from today's fixes.
        """
        # Mock Google OAuth to return same email as password account
        with patch('httpx.AsyncClient') as mock_client:
            mock_token_response = mock_client.return_value.__aenter__.return_value.post.return_value
            mock_token_response.status_code = 200
            mock_token_response.json.return_value = {
                "access_token": "test_token",
                "refresh_token": "test_refresh",
                "expires_in": 3600
            }

            mock_userinfo_response = mock_client.return_value.__aenter__.return_value.get.return_value
            mock_userinfo_response.status_code = 200
            mock_userinfo_response.json.return_value = {
                "sub": "different_google_id_456",
                "email": test_user_created["email"],  # SAME email as password account
                "name": "Test User",
                "picture": "https://example.com/pic.jpg"
            }

            # Simulate OAuth callback with intent='signup'
            response = client.get(
                "/auth/callback",
                params={
                    "code": "test_auth_code",
                    "state": "test_state"  # In real scenario, this contains intent
                },
                follow_redirects=False
            )

            # Should redirect to signin with error
            assert response.status_code == 307  # Redirect
            assert "signin.html" in response.headers["location"]
            assert "email_has_password" in response.headers["location"]

    def test_google_signin_blocks_existing_password_account(self, client, test_user_created, mock_google_oauth):
        """
        REGRESSION TEST: User with password account tries "Sign in with Google".
        Should be BLOCKED.

        This was Bug #1 from today's fixes.
        """
        # Similar to above test - OAuth with intent='signin' should also be blocked
        # (Implementation would be similar to test above)
        pass  # TODO: Implement when OAuth state handling is added

    def test_merged_account_allows_google_signin(self, client, test_user_merged):
        """
        REGRESSION TEST: User who merged accounts can "Sign in with Google".
        Should be ALLOWED.

        This was Bug #2 from today's fixes.
        """
        # Mock OAuth returning the SAME Google ID as merged account
        with patch('httpx.AsyncClient') as mock_client:
            mock_token_response = mock_client.return_value.__aenter__.return_value.post.return_value
            mock_token_response.status_code = 200
            mock_token_response.json.return_value = {
                "access_token": "test_token",
                "refresh_token": "test_refresh",
                "expires_in": 3600
            }

            mock_userinfo_response = mock_client.return_value.__aenter__.return_value.get.return_value
            mock_userinfo_response.status_code = 200
            mock_userinfo_response.json.return_value = {
                "sub": test_user_merged["google_id"],  # SAME Google ID
                "email": test_user_merged["email"],
                "name": test_user_merged["name"],
                "picture": test_user_merged.get("picture_url")
            }

            # OAuth callback should succeed
            response = client.get(
                "/auth/callback",
                params={"code": "test_code", "state": "test_state"},
                follow_redirects=False
            )

            # Should allow signin (redirect to dashboard)
            assert response.status_code == 307
            assert "dashboard" in response.headers["location"]
            assert "auth=success" in response.headers["location"]

    def test_merged_account_allows_password_signin(self, client, test_user_merged):
        """
        REGRESSION TEST: User who merged accounts can still signin with password.
        """
        response = client.post("/auth/signin", json={
            "email": test_user_merged["email"],
            "password": test_user_merged["password"]
        })

        assert response.status_code == 200
        assert response.json()["message"] == "Sign in successful"


@pytest.mark.auth
class TestPasswordReset:
    """Test password reset flow."""

    def test_forgot_password_success(self, client, test_user_created, mock_sendgrid):
        """Test password reset request for valid user."""
        response = client.post("/auth/forgot-password", json={
            "email": test_user_created["email"]
        })

        assert response.status_code == 200
        assert "reset link" in response.json()["message"].lower()
        # Verify email was "sent" (mocked)
        assert mock_sendgrid.called

    def test_forgot_password_nonexistent_email(self, client, mock_sendgrid):
        """Test password reset for non-existent email (should not reveal)."""
        response = client.post("/auth/forgot-password", json={
            "email": "nonexistent@example.com"
        })

        # Should return success message (don't reveal if user exists)
        assert response.status_code == 200
        assert "reset link" in response.json()["message"].lower()

    def test_forgot_password_google_only_account(self, client, test_user_with_google):
        """Test password reset rejected for Google-only accounts."""
        response = client.post("/auth/forgot-password", json={
            "email": test_user_with_google["email"]
        })

        assert response.status_code == 400
        assert "google sign-in" in response.json()["detail"].lower()

    def test_reset_password_success(self, client, test_user_created, test_db):
        """Test successful password reset with valid token."""
        from db import storage
        import secrets
        from datetime import datetime, timedelta

        # Create reset token
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        storage.create_password_reset_token(
            user_id=test_user_created["user_id"],
            email=test_user_created["email"],
            token=token,
            expires_at=expires_at
        )

        # Reset password
        new_password = "NewPassword123!"
        response = client.post("/auth/reset-password", json={
            "token": token,
            "new_password": new_password
        })

        assert response.status_code == 200
        assert "successful" in response.json()["message"].lower()

        # Verify can signin with new password
        signin_response = client.post("/auth/signin", json={
            "email": test_user_created["email"],
            "password": new_password
        })
        assert signin_response.status_code == 200

    def test_reset_password_invalid_token(self, client):
        """Test password reset fails with invalid token."""
        response = client.post("/auth/reset-password", json={
            "token": "invalid_token_xyz",
            "new_password": "NewPassword123!"
        })

        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()


@pytest.mark.auth
class TestUserProfile:
    """Test user profile retrieval and updates."""

    def test_get_current_user(self, client, test_user_created):
        """Test GET /auth/me returns user profile."""
        response = client.get(f"/auth/me?user_id={test_user_created['user_id']}")

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user_created["email"]
        assert data["name"] == test_user_created["name"]
        assert "calendar_connected" in data

    def test_get_current_user_with_calendar(self, client, test_user_with_google):
        """Test calendar_connected flag for user with Google connected."""
        response = client.get(f"/auth/me?user_id={test_user_with_google['google_id']}")

        assert response.status_code == 200
        data = response.json()
        assert data["calendar_connected"] is True

    def test_update_profile(self, client, test_user_created):
        """Test profile update."""
        response = client.put(
            f"/auth/profile/{test_user_created['user_id']}",
            json={
                "name": "Updated Name",
                "profession": "Software Engineer",
                "timezone": "America/New_York",
                "insight_time": "09:30"
            }
        )

        assert response.status_code == 200
        assert "updated" in response.json()["message"].lower()

        # Verify update persisted
        get_response = client.get(f"/auth/me?user_id={test_user_created['user_id']}")
        assert get_response.json()["name"] == "Updated Name"
        assert get_response.json()["profession"] == "Software Engineer"


@pytest.mark.auth
class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_signup_weak_password(self, client):
        """Test signup rejects weak password."""
        response = client.post("/auth/signup", json={
            "email": "test@example.com",
            "password": "weak",
            "name": "Test User"
        })

        assert response.status_code == 422  # Validation error

    def test_signup_invalid_email(self, client):
        """Test signup rejects invalid email format."""
        response = client.post("/auth/signup", json={
            "email": "not-an-email",
            "password": "ValidPass123!",
            "name": "Test User"
        })

        assert response.status_code == 422  # Validation error

    def test_signin_missing_fields(self, client):
        """Test signin rejects missing fields."""
        response = client.post("/auth/signin", json={
            "email": "test@example.com"
            # Missing password
        })

        assert response.status_code == 422  # Validation error
