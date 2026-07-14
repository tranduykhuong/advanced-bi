-- Migration 005: widen ods.trade_transaction descriptive columns to TEXT
-- Fixes StringDataRightTruncation when chapter_name/heading exceed VARCHAR(100).
-- Safe to re-run: ALTER ... TYPE TEXT is a no-op when the column is already TEXT.

ALTER TABLE ods.trade_transaction
    ALTER COLUMN chapter_name TYPE TEXT,
    ALTER COLUMN heading_name TYPE TEXT,
    ALTER COLUMN product_name     TYPE TEXT,
    ALTER COLUMN partner_name     TYPE TEXT,
    ALTER COLUMN partner_region   TYPE TEXT,
    ALTER COLUMN partner_continent TYPE TEXT;
