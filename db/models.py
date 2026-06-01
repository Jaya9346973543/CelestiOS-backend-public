from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Any
from datetime import datetime

# User Model
class UserBase(BaseModel):
    email: EmailStr
    name: str
    picture_url: Optional[str] = None

class UserCreate(UserBase):
    google_id: str
    
class UserInDB(UserBase):
    id: str # UUID from Supabase auth
    created_at: datetime
    google_id: str

# Token Model
class TokenData(BaseModel):
    user_id: str
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: int
    updated_at: datetime

# Calendar Event Model
class CalendarEventCreate(BaseModel):
    user_id: str
    google_event_id: str
    summary: str
    description: Optional[str] = None
    start_time: datetime
    end_time: datetime
    status: str = "confirmed"

class CalendarEventInDB(CalendarEventCreate):
    id: str # UUID
    created_at: datetime

# Recommendation / Insight Model
class RecommendationLog(BaseModel):
    user_id: str
    date: str # ISO Date string like YYYY-MM-DD
    insights: str # LLM text output
    created_at: datetime
    
# Feedback Model
class DailyFeedback(BaseModel):
    user_id: str
    date: str
    feedback_type: str = "end_of_day"
    rating: int = Field(..., ge=1, le=5)
    thoughts: Optional[str] = None

# Health Integration Models

class HealthConnectionCreate(BaseModel):
    user_id: str
    provider: str  # 'oura', 'fitbit', 'garmin', 'apple_health'
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[int] = None  # Unix timestamp
    scope: Optional[str] = None
    provider_user_id: Optional[str] = None

class HealthConnectionInDB(HealthConnectionCreate):
    id: str  # UUID
    connected_at: datetime
    last_synced_at: Optional[datetime] = None

class HealthDataCreate(BaseModel):
    user_id: str
    date: str  # ISO date string (YYYY-MM-DD)
    provider: str  # 'oura', 'fitbit', 'garmin', 'apple_health'

    # Sleep metrics
    sleep_score: Optional[int] = Field(None, ge=0, le=100)
    sleep_duration_minutes: Optional[int] = None
    deep_sleep_minutes: Optional[int] = None
    rem_sleep_minutes: Optional[int] = None
    light_sleep_minutes: Optional[int] = None
    awake_time_minutes: Optional[int] = None
    sleep_efficiency: Optional[int] = Field(None, ge=0, le=100)

    # Readiness & recovery
    readiness_score: Optional[int] = Field(None, ge=0, le=100)
    recovery_score: Optional[int] = Field(None, ge=0, le=100)
    body_battery: Optional[int] = Field(None, ge=0, le=100)

    # Heart rate
    resting_heart_rate: Optional[int] = None
    avg_heart_rate: Optional[int] = None
    max_heart_rate: Optional[int] = None
    min_heart_rate: Optional[int] = None

    # HRV
    hrv_avg: Optional[float] = None
    hrv_rmssd: Optional[float] = None

    # Activity
    activity_score: Optional[int] = Field(None, ge=0, le=100)
    steps: Optional[int] = None
    active_calories: Optional[int] = None
    total_calories: Optional[int] = None
    active_minutes: Optional[int] = None

    # Other metrics
    stress_avg: Optional[float] = None
    spo2_avg: Optional[float] = None

    # Metadata
    raw_data: Optional[dict] = None

class HealthDataInDB(HealthDataCreate):
    id: str  # UUID
    synced_at: datetime

# Microsoft Calendar Integration Models

class MicrosoftTokenCreate(BaseModel):
    user_id: str
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: int  # Unix timestamp
    scope: Optional[str] = None

class MicrosoftTokenInDB(MicrosoftTokenCreate):
    id: str  # UUID
    connected_at: datetime
    updated_at: datetime
