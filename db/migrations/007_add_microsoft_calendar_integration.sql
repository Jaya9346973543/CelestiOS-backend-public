-- Migration: Add Microsoft Calendar Integration Support
-- Description: Adds microsoft_tokens table for storing OAuth tokens to access work calendars via MS Graph API
-- Date: 2026-05-04

-- Create microsoft_tokens table for Supabase (PostgreSQL)
create table if not exists microsoft_tokens (
    id uuid primary key default gen_random_uuid(),
    user_id text not null unique references users(google_id) on delete cascade,
    access_token text not null,
    refresh_token text,
    expires_at bigint not null,
    scope text,
    connected_at timestamp default now(),
    updated_at timestamp default now()
);

-- Add index on user_id for faster lookups
create index if not exists idx_microsoft_tokens_user_id on microsoft_tokens(user_id);

-- Add comment for documentation
comment on table microsoft_tokens is 'Stores Microsoft OAuth tokens for work calendar access via Graph API';
