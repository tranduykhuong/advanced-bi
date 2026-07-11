-- Migration 006: widen nds.product descriptive columns to TEXT
-- Fixes StringDataRightTruncation when category_heading exceeds VARCHAR(100).
-- Safe to re-run: ALTER ... TYPE TEXT is a no-op when the column is already TEXT.

ALTER TABLE nds.product
    ALTER COLUMN category_chapter TYPE TEXT,
    ALTER COLUMN category_heading TYPE TEXT,
    ALTER COLUMN product_name     TYPE TEXT;
