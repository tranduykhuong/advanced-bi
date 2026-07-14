-- Migration 006: widen nds.product descriptive columns to TEXT
-- Fixes StringDataRightTruncation when heading_name exceeds VARCHAR(100).
-- Safe to re-run: ALTER ... TYPE TEXT is a no-op when the column is already TEXT.

ALTER TABLE nds.product
    ALTER COLUMN chapter_name TYPE TEXT,
    ALTER COLUMN heading_name TYPE TEXT,
    ALTER COLUMN product_name     TYPE TEXT;
