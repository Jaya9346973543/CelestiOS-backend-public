-- Migration: Add health integration tables
-- Date: 2026-04-18
-- Purpose: Store OAuth tokens and health metrics from connected devices (Oura, Fitbit, Garmin, Apple Health)

-- ============================================
-- Table: health_connections
-- Stores OAuth tokens for connected health devices
-- ============================================

CREATE TABLE IF NOT EXISTS public.health_connections (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id text NOT NULL REFERENCES public.users(google_id) ON DELETE CASCADE,
    provider text NOT NULL CHECK (provider IN ('oura', 'fitbit', 'garmin', 'apple_health')),
    access_token text NOT NULL,
    refresh_token text,
    expires_at bigint, -- Unix timestamp (seconds since epoch)
    scope text, -- Comma-separated list of granted scopes
    provider_user_id text, -- User ID from the provider (e.g., Oura user ID)
    connected_at timestamptz DEFAULT now(),
    last_synced_at timestamptz,
    UNIQUE(user_id, provider)
);

-- Add indexes for health_connections
CREATE INDEX IF NOT EXISTS health_connections_user_id_idx ON public.health_connections (user_id);
CREATE INDEX IF NOT EXISTS health_connections_provider_idx ON public.health_connections (provider);
CREATE INDEX IF NOT EXISTS health_connections_last_synced_idx ON public.health_connections (last_synced_at);

-- ============================================
-- Table: health_data
-- Stores daily aggregated health metrics
-- ============================================

CREATE TABLE IF NOT EXISTS public.health_data (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id text NOT NULL REFERENCES public.users(google_id) ON DELETE CASCADE,
    date date NOT NULL,
    provider text NOT NULL CHECK (provider IN ('oura', 'fitbit', 'garmin', 'apple_health')),

    -- Sleep Metrics
    sleep_score integer CHECK (sleep_score >= 0 AND sleep_score <= 100),
    sleep_duration_minutes integer,
    deep_sleep_minutes integer,
    rem_sleep_minutes integer,
    light_sleep_minutes integer,
    awake_time_minutes integer,
    sleep_efficiency integer CHECK (sleep_efficiency >= 0 AND sleep_efficiency <= 100),

    -- Readiness & Recovery Metrics (primary indicator of energy)
    readiness_score integer CHECK (readiness_score >= 0 AND readiness_score <= 100),
    recovery_score integer CHECK (recovery_score >= 0 AND recovery_score <= 100),
    body_battery integer CHECK (body_battery >= 0 AND body_battery <= 100), -- Garmin's metric

    -- Heart Rate Metrics
    resting_heart_rate integer,
    avg_heart_rate integer,
    max_heart_rate integer,
    min_heart_rate integer,

    -- HRV (Heart Rate Variability)
    hrv_avg real, -- Average HRV in milliseconds
    hrv_rmssd real, -- Root mean square of successive differences

    -- Activity Metrics
    activity_score integer CHECK (activity_score >= 0 AND activity_score <= 100),
    steps integer,
    active_calories integer,
    total_calories integer,
    active_minutes integer,

    -- Stress & Other
    stress_avg real, -- Average stress level (provider-specific scale)
    spo2_avg real, -- Blood oxygen saturation percentage

    -- Metadata
    raw_data jsonb, -- Full API response for debugging and future features
    synced_at timestamptz DEFAULT now(),

    UNIQUE(user_id, date, provider)
);

-- Add indexes for health_data
CREATE INDEX IF NOT EXISTS health_data_user_id_idx ON public.health_data (user_id);
CREATE INDEX IF NOT EXISTS health_data_user_date_idx ON public.health_data (user_id, date DESC);
CREATE INDEX IF NOT EXISTS health_data_provider_idx ON public.health_data (provider);
CREATE INDEX IF NOT EXISTS health_data_date_idx ON public.health_data (date DESC);

-- Add comment to tables
COMMENT ON TABLE public.health_connections IS 'OAuth tokens and connection status for health devices (Oura, Fitbit, Garmin, Apple Health)';
COMMENT ON TABLE public.health_data IS 'Daily aggregated health metrics from connected devices. Used for energy-aware scheduling and personalized insights.';

-- Note: Data retention policy enforced by application logic (90 days for historical data, immediate deletion on disconnect)
