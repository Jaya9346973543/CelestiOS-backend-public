CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    google_id TEXT UNIQUE,
    email TEXT NOT NULL,
    name TEXT NOT NULL,
    picture_url TEXT,
    password_hash TEXT,
    age INTEGER,
    profession TEXT,
    short_term_goal TEXT,
    timezone TEXT DEFAULT 'UTC',
    insight_time TEXT DEFAULT '08:00',
    email_notifications_enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tokens (
    user_id TEXT PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at INTEGER,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS calendar_events (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    google_event_id TEXT UNIQUE NOT NULL,
    summary TEXT,
    description TEXT,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    status TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    feedback_type TEXT NOT NULL DEFAULT 'end_of_day',
    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    thoughts TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    email TEXT NOT NULL,
    token TEXT UNIQUE NOT NULL,
    token_type TEXT NOT NULL DEFAULT 'password_reset',
    expires_at TEXT NOT NULL,
    used INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS checkins (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    sleep_hours TEXT,
    energy_level TEXT,
    priority TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    -- Evening check-in fields
    completed_priority INTEGER,
    disruption INTEGER,
    disruption_detail TEXT,
    late_start INTEGER,
    started_at TEXT,
    evening_completed_at TEXT,
    UNIQUE(user_id, date)
);

CREATE TABLE IF NOT EXISTS insights_cache (
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    detailed_insights TEXT NOT NULL,
    quick_insights TEXT NOT NULL,
    day_type TEXT NOT NULL,
    cached_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, date)
);

-- Health Integration Tables (Added 2026-04-18)

CREATE TABLE IF NOT EXISTS health_connections (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('oura', 'fitbit', 'garmin', 'apple_health')),
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at INTEGER,
    scope TEXT,
    provider_user_id TEXT,
    connected_at TEXT DEFAULT (datetime('now')),
    last_synced_at TEXT,
    UNIQUE(user_id, provider),
    FOREIGN KEY(user_id) REFERENCES users(google_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS health_data (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('oura', 'fitbit', 'garmin', 'apple_health')),
    sleep_score INTEGER CHECK (sleep_score >= 0 AND sleep_score <= 100),
    sleep_duration_minutes INTEGER,
    deep_sleep_minutes INTEGER,
    rem_sleep_minutes INTEGER,
    light_sleep_minutes INTEGER,
    awake_time_minutes INTEGER,
    sleep_efficiency INTEGER CHECK (sleep_efficiency >= 0 AND sleep_efficiency <= 100),
    readiness_score INTEGER CHECK (readiness_score >= 0 AND readiness_score <= 100),
    recovery_score INTEGER CHECK (recovery_score >= 0 AND recovery_score <= 100),
    body_battery INTEGER CHECK (body_battery >= 0 AND body_battery <= 100),
    resting_heart_rate INTEGER,
    avg_heart_rate INTEGER,
    max_heart_rate INTEGER,
    min_heart_rate INTEGER,
    hrv_avg REAL,
    hrv_rmssd REAL,
    activity_score INTEGER CHECK (activity_score >= 0 AND activity_score <= 100),
    steps INTEGER,
    active_calories INTEGER,
    total_calories INTEGER,
    active_minutes INTEGER,
    stress_avg REAL,
    spo2_avg REAL,
    raw_data TEXT,
    synced_at TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id, date, provider),
    FOREIGN KEY(user_id) REFERENCES users(google_id) ON DELETE CASCADE
);

-- Microsoft Calendar Integration (Added 2026-05-04)

CREATE TABLE IF NOT EXISTS microsoft_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at INTEGER NOT NULL,
    scope TEXT,
    connected_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(user_id) REFERENCES users(google_id) ON DELETE CASCADE
);
