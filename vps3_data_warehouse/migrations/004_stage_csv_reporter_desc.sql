-- Migration 004: add reporter_desc TEXT to stage.stage_csv
-- Stores the human-readable reporter name alongside the numeric reporter_code.
-- Safe to re-run: ADD COLUMN IF NOT EXISTS is idempotent in PostgreSQL 9.6+.

ALTER TABLE stage.stage_csv
    ADD COLUMN IF NOT EXISTS reporter_desc TEXT;
