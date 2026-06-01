-- Migration: Add password authentication support
-- Run this on existing Supabase databases

-- 1. Add password_hash column to users table (optional, for manual signup users)
ALTER TABLE public.users
ADD COLUMN IF NOT EXISTS password_hash TEXT;

-- 2. Make google_id nullable (OAuth users have google_id, manual signup users don't)
ALTER TABLE public.users
ALTER COLUMN google_id DROP NOT NULL;

-- 3. Create password_reset_tokens table
CREATE TABLE IF NOT EXISTS public.password_reset_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL,
    token TEXT UNIQUE NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Create indexes for faster lookups
CREATE INDEX IF NOT EXISTS password_reset_tokens_email_idx
    ON public.password_reset_tokens (email);

CREATE INDEX IF NOT EXISTS password_reset_tokens_token_idx
    ON public.password_reset_tokens (token);
