-- Migration: Add email_notifications_enabled column to users table
-- Date: 2026-04-21
-- Purpose: Allow users to unsubscribe from daily insight emails

-- PostgreSQL (Supabase)
ALTER TABLE public.users
ADD COLUMN IF NOT EXISTS email_notifications_enabled BOOLEAN DEFAULT TRUE;

-- SQLite (Local DB)
-- SQLite doesn't support ALTER TABLE ADD COLUMN IF NOT EXISTS
-- So we check if column exists first, then add it
-- This migration should be run manually for SQLite databases:
-- ALTER TABLE users ADD COLUMN email_notifications_enabled INTEGER DEFAULT 1;
