-- Migration 005: widen ods.trade_transaction descriptive columns to TEXT
-- Fixes StringDataRightTruncation when category_chapter/heading exceed VARCHAR(100).
-- Safe to re-run: ALTER ... TYPE TEXT is a no-op when the column is already TEXT.

ALTER TABLE ods.trade_transaction
    ALTER COLUMN category_chapter TYPE TEXT,
    ALTER COLUMN category_heading TYPE TEXT,
    ALTER COLUMN product_name     TYPE TEXT,
    ALTER COLUMN partner_name     TYPE TEXT,
    ALTER COLUMN partner_region   TYPE TEXT,
    ALTER COLUMN partner_continent TYPE TEXT;
