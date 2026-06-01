-- Migration: Add evening check-in columns to checkins table
-- Date: 2026-03-30
-- Purpose: Support evening check-in feature

-- Add evening check-in columns
ALTER TABLE public.checkins
ADD COLUMN IF NOT EXISTS completed_priority boolean,
ADD COLUMN IF NOT EXISTS disruption boolean,
ADD COLUMN IF NOT EXISTS disruption_detail text,
ADD COLUMN IF NOT EXISTS late_start boolean,
ADD COLUMN IF NOT EXISTS started_at text,
ADD COLUMN IF NOT EXISTS evening_completed_at timestamptz;

-- Note: These columns are nullable to maintain backward compatibility
-- with existing check-in records that only have morning data
