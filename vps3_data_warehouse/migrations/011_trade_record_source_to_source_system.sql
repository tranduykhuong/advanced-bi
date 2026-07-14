-- Migration 011: consolidate record_source + source_system into a single
-- source_system column on the trade_transaction tables.
--
-- Why: ods.trade_transaction / nds.trade_transaction / dds.fact_trade_transaction
-- previously carried TWO source columns that were always in lock-step 1:1:
--   record_source  — the data provider (UN_COMTRADE / NSO / TRADE_MAP)
--   source_system  — the technical stage table it came through (stage_csv /
--                     stage_text / stage_db), fully derivable from record_source
-- source_system never carried independent information (extract_stage.py hard-
-- codes the pairing), was never part of any fact grain, and — unlike ods.fta /
-- ods.exchange_rate, which already used a single source_system column to mean
-- the data provider (APTIAD / FRANKFURTER) — it was inconsistent in meaning
-- across tables. This migration drops the technical column and renames
-- record_source to source_system so all ODS/NDS/DDS tables agree on one
-- consistent "data provider" column.
--
-- Guarded by an information_schema check so it is a no-op on databases where
-- the tables were created fresh from the already-updated canonical DDL (no
-- record_source column ever existed there).

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'ods' AND table_name = 'trade_transaction'
          AND column_name = 'record_source'
    ) THEN
        ALTER TABLE ods.trade_transaction DROP COLUMN IF EXISTS source_system;
        ALTER TABLE ods.trade_transaction RENAME COLUMN record_source TO source_system;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nds' AND table_name = 'trade_transaction'
          AND column_name = 'record_source'
    ) THEN
        ALTER TABLE nds.trade_transaction DROP COLUMN IF EXISTS source_system;
        ALTER TABLE nds.trade_transaction RENAME COLUMN record_source TO source_system;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'dds' AND table_name = 'fact_trade_transaction'
          AND column_name = 'record_source'
    ) THEN
        ALTER TABLE dds.fact_trade_transaction DROP COLUMN IF EXISTS source_system;
        ALTER TABLE dds.fact_trade_transaction RENAME COLUMN record_source TO source_system;
    END IF;
END $$;

COMMENT ON COLUMN ods.trade_transaction.source_system IS 'Data provider: UN_COMTRADE, NSO, or TRADE_MAP.';
COMMENT ON COLUMN nds.trade_transaction.source_system IS 'Data provider: UN_COMTRADE, NSO, or TRADE_MAP.';
COMMENT ON COLUMN dds.fact_trade_transaction.source_system IS 'Data provider: UN_COMTRADE, NSO, or TRADE_MAP.';
