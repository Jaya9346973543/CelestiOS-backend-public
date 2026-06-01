import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Celestios-Backend"
    FRONTEND_URL: str = "https://celesti.life"  # Production default
    SECRET_KEY: str  # No default = required at startup
    OAUTH_STATE_MAX_AGE_SECONDS: int = 600

    # Supabase
    SUPABASE_URL: str
    SUPABASE_KEY: str
    SUPABASE_DB_URL: str
    SUPABASE_USERS_TABLE: str = "users"
    SUPABASE_TOKENS_TABLE: str = "tokens"
    SUPABASE_EVENTS_TABLE: str = "calendar_events"
    AUTO_MIGRATE_SCHEMA: bool = False
    LOCAL_DB_PATH: str = "db/local.sqlite3"
    ENABLE_LOCAL_FALLBACK: bool = True

    # Google OAuth
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str = "https://celesti.life/auth/callback"  # Production default
    GOOGLE_SCOPES: str = "openid email profile https://www.googleapis.com/auth/calendar.readonly"

    # Oura OAuth
    OURA_CLIENT_ID: str
    OURA_CLIENT_SECRET: str
    OURA_REDIRECT_URI: str = "https://celestios-backend-application.onrender.com/auth/oura/callback"
    OURA_API_BASE_URL: str = "https://api.ouraring.com"

    # Fitbit OAuth
    FITBIT_CLIENT_ID: str
    FITBIT_CLIENT_SECRET: str
    FITBIT_REDIRECT_URI: str = "https://celestios-backend-application.onrender.com/auth/fitbit/callback"
    FITBIT_API_BASE_URL: str = "https://api.fitbit.com"

    # Microsoft OAuth
    MICROSOFT_CLIENT_ID: str
    MICROSOFT_CLIENT_SECRET: str
    MICROSOFT_REDIRECT_URI: str = "https://celestios-backend-application.onrender.com/auth/microsoft/callback"
    MICROSOFT_SCOPES: str = "openid email profile Calendars.ReadWrite offline_access"

    # OpenAI
    OPENAI_API_KEY: str

    # SendGrid (Email Service)
    SENDGRID_API_KEY: str = ""
    SENDGRID_FROM_EMAIL: str = "noreply@celestios.com"
    SENDGRID_FROM_NAME: str = "celesti"
    ENABLE_EMAIL_SENDING: bool = True  # Set to False in local .env to disable emails

    # SMTP (GoDaddy - Legacy, prefer SendGrid)
    SMTP_SERVER: str = ""
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SENDER_EMAIL: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )


settings = Settings()
