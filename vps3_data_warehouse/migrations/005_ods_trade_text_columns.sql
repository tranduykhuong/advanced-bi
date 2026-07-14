-- Migration 005: widen ods.trade_transaction descriptive columns to TEXT
-- Fixes StringDataRightTruncation when chapter_name/heading exceed VARCHAR(100).
-- Safe to re-run: ALTER ... TYPE TEXT is a no-op when the column is already TEXT.

-- Retrofit: ods.trade_transaction is never dropped/recreated, so a database
-- bootstrapped before the category_chapter/category_heading -> chapter_name/
-- heading_name rename still has the old column names. Guarded so this is a
-- no-op on databases created after the rename.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'ods' AND table_name = 'trade_transaction'
          AND column_name = 'category_chapter'
    ) THEN
        ALTER TABLE ods.trade_transaction RENAME COLUMN category_chapter TO chapter_name;
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'ods' AND table_name = 'trade_transaction'
          AND column_name = 'category_heading'
    ) THEN
        ALTER TABLE ods.trade_transaction RENAME COLUMN category_heading TO heading_name;
    END IF;
END $$;

ALTER TABLE ods.trade_transaction
    ALTER COLUMN chapter_name TYPE TEXT,
    ALTER COLUMN heading_name TYPE TEXT,
    ALTER COLUMN product_name     TYPE TEXT,
    ALTER COLUMN partner_name     TYPE TEXT,
    ALTER COLUMN partner_region   TYPE TEXT,
    ALTER COLUMN partner_continent TYPE TEXT;
