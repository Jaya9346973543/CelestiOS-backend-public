-- Migration: Add insights_cache table to avoid duplicate OpenAI calls
-- Date: 2026-03-30
-- Purpose: Cache AI-generated insights to prevent calling OpenAI twice for same data

-- Create insights_cache table
CREATE TABLE IF NOT EXISTS public.insights_cache (
    user_id text NOT NULL,
    date text NOT NULL,
    detailed_insights text NOT NULL,
    quick_insights text NOT NULL,
    day_type text NOT NULL,
    cached_at timestamptz DEFAULT now(),
    PRIMARY KEY (user_id, date)
);

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS insights_cache_user_id_idx ON public.insights_cache (user_id);
CREATE INDEX IF NOT EXISTS insights_cache_date_idx ON public.insights_cache (date);

-- Note: Cache entries automatically expire after 2 hours (handled by application logic)
