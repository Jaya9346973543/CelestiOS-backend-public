"""
Shared test fixtures and configuration for pytest.
"""
import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
import tempfile
from pathlib import Path

# Set test environment variables BEFORE importing app
os.environ["TESTING"] = "true"
os.environ["LOCAL_DB_PATH"] = ":memory:"  # Use in-memory SQLite for tests
os.environ["ENABLE_LOCAL_FALLBACK"] = "true"
os.environ["SUPABASE_URL"] = ""  # Disable Supabase in tests
os.environ["SUPABASE_KEY"] = ""
os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-client-secret"
os.environ["GOOGLE_REDIRECT_URI"] = "http://localhost:8000/auth/callback"
os.environ["FRONTEND_URL"] = "http://localhost:8000"
os.environ["SENDGRID_API_KEY"] = ""  # Disable email sending in tests

from main import app
from db import storage, local_db


@pytest.fixture(scope="function")
def test_db():
    """
    Create a fresh in-memory database for each test.
    """
    # Reset the schema initialization flag
    local_db._schema_initialized = False

    # Initialize schema
    local_db.ensure_local_schema()

    yield local_db

    # Cleanup after test
    local_db._schema_initialized = False


@pytest.fixture(scope="function")
def client(test_db):
    """
    FastAPI test client with fresh database for each test.
    """
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def test_user_data():
    """
    Sample user data for testing.
    """
    return {
        "email": "testuser@example.com",
        "password": "TestPassword123!",
        "name": "Test User"
    }


@pytest.fixture
def test_user_created(client, test_user_data):
    """
    Create a test user via signup endpoint and return the user data.
    """
    response = client.post("/auth/signup", json=test_user_data)
    assert response.status_code == 200
    return {
        **test_user_data,
        "user_id": response.json()["user_id"]
    }


@pytest.fixture
def test_user_with_google(test_db):
    """
    Create a test user with Google OAuth (no password).
    """
    user_data = {
        "google_id": "google_123456789",
        "email": "googleuser@example.com",
        "name": "Google User",
        "picture_url": "https://example.com/pic.jpg"
    }
    storage.upsert_user(user_data)

    # Add refresh token to simulate connected calendar
    token_data = {
        "user_id": "google_123456789",
        "access_token": "test_access_token",
        "refresh_token": "test_refresh_token",
        "expires_at": 9999999999,
        "updated_at": "2026-03-30T00:00:00Z"
    }
    storage.upsert_token(token_data)

    return user_data


@pytest.fixture
def test_user_merged(test_db):
    """
    Create a test user with both password AND Google (merged account).
    """
    from api.auth import hash_password

    user_data = {
        "google_id": "merged_google_123",
        "email": "merged@example.com",
        "name": "Merged User",
        "password_hash": hash_password("MergedPassword123!"),
        "picture_url": "https://example.com/merged.jpg"
    }
    storage.upsert_user(user_data)

    # Add refresh token
    token_data = {
        "user_id": "merged_google_123",
        "access_token": "test_access_token",
        "refresh_token": "test_refresh_token",
        "expires_at": 9999999999,
        "updated_at": "2026-03-30T00:00:00Z"
    }
    storage.upsert_token(token_data)

    return {
        **user_data,
        "password": "MergedPassword123!"  # For testing signin
    }


@pytest.fixture
def mock_google_oauth():
    """
    Mock Google OAuth responses.
    """
    with patch('httpx.AsyncClient') as mock_client:
        # Mock token exchange
        mock_token_response = Mock()
        mock_token_response.status_code = 200
        mock_token_response.json.return_value = {
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "expires_in": 3600
        }

        # Mock userinfo
        mock_userinfo_response = Mock()
        mock_userinfo_response.status_code = 200
        mock_userinfo_response.json.return_value = {
            "sub": "google_oauth_test_123",
            "email": "oauth@example.com",
            "name": "OAuth Test User",
            "picture": "https://example.com/oauth.jpg"
        }

        # Configure mock client
        mock_instance = mock_client.return_value.__aenter__.return_value
        mock_instance.post.return_value = mock_token_response
        mock_instance.get.return_value = mock_userinfo_response

        yield {
            "client": mock_client,
            "google_id": "google_oauth_test_123",
            "email": "oauth@example.com",
            "name": "OAuth Test User"
        }


@pytest.fixture
def mock_sendgrid():
    """
    Mock SendGrid email sending.
    """
    with patch('services.email_sendgrid.send_password_reset_email') as mock_send:
        mock_send.return_value = True
        yield mock_send


@pytest.fixture
def test_checkin_data():
    """
    Sample check-in data.
    """
    return {
        "date": "2026-03-30",
        "sleep_hours": "7",
        "energy_level": "medium",
        "priority": "Finish test suite"
    }


@pytest.fixture
def today_str():
    """
    Today's date in YYYY-MM-DD format.
    """
    from datetime import date
    return date.today().strftime('%Y-%m-%d')
