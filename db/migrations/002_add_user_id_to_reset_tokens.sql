-- Migration: Add user_id column to password_reset_tokens
-- Date: 2026-03-30
-- Purpose: Security fix - tie reset tokens to specific user accounts, not just emails

-- For Supabase (PostgreSQL)
DO $$
BEGIN
    -- Add user_id column if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'password_reset_tokens'
        AND column_name = 'user_id'
    ) THEN
        ALTER TABLE public.password_reset_tokens
        ADD COLUMN user_id text;

        -- Set user_id for existing rows (lookup by email)
        UPDATE public.password_reset_tokens prt
        SET user_id = u.google_id
        FROM public.users u
        WHERE prt.email = u.email
        AND prt.user_id IS NULL;

        -- Delete orphaned tokens (no matching user)
        DELETE FROM public.password_reset_tokens
        WHERE user_id IS NULL;

        -- Make user_id required
        ALTER TABLE public.password_reset_tokens
        ALTER COLUMN user_id SET NOT NULL;

        -- Add index for faster lookups
        CREATE INDEX IF NOT EXISTS password_reset_tokens_user_id_idx
        ON public.password_reset_tokens (user_id);
    END IF;
END $$;

-- For SQLite (local development)
-- SQLite doesn't support ALTER COLUMN NOT NULL, so we recreate the table

-- Note: If using SQLite, manually run these commands:
-- 1. Backup existing tokens
-- 2. Drop old table
-- 3. Create new table with user_id (schema_sqlite.sql)
-- 4. Restore tokens (if needed, with user_id populated)
