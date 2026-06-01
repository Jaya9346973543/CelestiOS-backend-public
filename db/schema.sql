create extension if not exists pgcrypto;

create table if not exists public.users (
    id uuid primary key default gen_random_uuid(),
    google_id text unique,
    email text not null,
    name text not null,
    picture_url text,
    password_hash text,
    age integer,
    profession varchar(255),
    short_term_goal varchar(255),
    timezone varchar(50) default 'UTC',
    insight_time varchar(20) default '08:00',
    email_notifications_enabled boolean default true,
    created_at timestamptz default now()
);

create table if not exists public.tokens (
    user_id text primary key,
    access_token text not null,
    refresh_token text,
    expires_at bigint,
    updated_at timestamptz default now()
);

create table if not exists public.calendar_events (
    id uuid primary key default gen_random_uuid(),
    user_id text not null,
    google_event_id text unique not null,
    summary text,
    description text,
    start_time timestamptz not null,
    end_time timestamptz not null,
    status text,
    created_at timestamptz default now()
);

create index if not exists calendar_events_user_id_idx
    on public.calendar_events (user_id);

create index if not exists calendar_events_start_time_idx
    on public.calendar_events (start_time);

create table if not exists public.feedback (
    id uuid primary key default gen_random_uuid(),
    user_id text not null,
    date text not null,
    feedback_type text not null default 'end_of_day',
    rating integer not null check (rating >= 1 and rating <= 5),
    thoughts text,
    created_at timestamptz default now()
);

create index if not exists feedback_user_id_idx
    on public.feedback (user_id);

create table if not exists public.password_reset_tokens (
    id uuid primary key default gen_random_uuid(),
    user_id text not null,
    email text not null,
    token text unique not null,
    token_type text not null default 'password_reset',
    expires_at timestamptz not null,
    used boolean default false,
    created_at timestamptz default now()
);

create index if not exists password_reset_tokens_email_idx
    on public.password_reset_tokens (email);

create index if not exists password_reset_tokens_token_idx
    on public.password_reset_tokens (token);

create table if not exists public.checkins (
    id uuid primary key default gen_random_uuid(),
    user_id text not null,
    date text not null,
    sleep_hours text,
    energy_level text,
    priority text,
    created_at timestamptz default now(),
    -- Evening check-in fields
    completed_priority boolean,
    disruption boolean,
    disruption_detail text,
    late_start boolean,
    started_at text,
    evening_completed_at timestamptz,
    unique(user_id, date)
);

create index if not exists checkins_user_id_idx
    on public.checkins (user_id);

create index if not exists checkins_date_idx
    on public.checkins (date);

create table if not exists public.insights_cache (
    user_id text not null,
    date text not null,
    detailed_insights text not null,
    quick_insights text not null,
    day_type text not null,
    cached_at timestamptz default now(),
    primary key (user_id, date)
);

create index if not exists insights_cache_user_id_idx
    on public.insights_cache (user_id);

create index if not exists insights_cache_date_idx
    on public.insights_cache (date);

-- Health Integration Tables (Added 2026-04-18)

create table if not exists public.health_connections (
    id uuid primary key default gen_random_uuid(),
    user_id text not null references public.users(google_id) on delete cascade,
    provider text not null check (provider in ('oura', 'fitbit', 'garmin', 'apple_health')),
    access_token text not null,
    refresh_token text,
    expires_at bigint,
    scope text,
    provider_user_id text,
    connected_at timestamptz default now(),
    last_synced_at timestamptz,
    unique(user_id, provider)
);

create index if not exists health_connections_user_id_idx
    on public.health_connections (user_id);

create index if not exists health_connections_provider_idx
    on public.health_connections (provider);

create index if not exists health_connections_last_synced_idx
    on public.health_connections (last_synced_at);

create table if not exists public.health_data (
    id uuid primary key default gen_random_uuid(),
    user_id text not null references public.users(google_id) on delete cascade,
    date date not null,
    provider text not null check (provider in ('oura', 'fitbit', 'garmin', 'apple_health')),
    sleep_score integer check (sleep_score >= 0 and sleep_score <= 100),
    sleep_duration_minutes integer,
    deep_sleep_minutes integer,
    rem_sleep_minutes integer,
    light_sleep_minutes integer,
    awake_time_minutes integer,
    sleep_efficiency integer check (sleep_efficiency >= 0 and sleep_efficiency <= 100),
    readiness_score integer check (readiness_score >= 0 and readiness_score <= 100),
    recovery_score integer check (recovery_score >= 0 and recovery_score <= 100),
    body_battery integer check (body_battery >= 0 and body_battery <= 100),
    resting_heart_rate integer,
    avg_heart_rate integer,
    max_heart_rate integer,
    min_heart_rate integer,
    hrv_avg real,
    hrv_rmssd real,
    activity_score integer check (activity_score >= 0 and activity_score <= 100),
    steps integer,
    active_calories integer,
    total_calories integer,
    active_minutes integer,
    stress_avg real,
    spo2_avg real,
    raw_data jsonb,
    synced_at timestamptz default now(),
    unique(user_id, date, provider)
);

create index if not exists health_data_user_id_idx
    on public.health_data (user_id);

create index if not exists health_data_user_date_idx
    on public.health_data (user_id, date desc);

create index if not exists health_data_provider_idx
    on public.health_data (provider);

create index if not exists health_data_date_idx
    on public.health_data (date desc);