-- Migration 008: add fta_keys column to ods.trade_transaction
--
-- Design intent: fta_keys uuid[] is intended to store explicit FTA references
-- per trade transaction when source data provides them.
--
-- Current ETL behaviour: the column is NOT populated by the stage→ODS transform
-- because no upstream source currently provides per-record FTA links.
-- nds.fta_utilization is therefore derived in ods_to_nds.py by joining
-- nds.trade_transaction.partner_code → nds.fta_member.country_code.
--
-- This column is added for future use and kept nullable.
-- Safe to re-run: ADD COLUMN IF NOT EXISTS is idempotent.

ALTER TABLE ods.trade_transaction
    ADD COLUMN IF NOT EXISTS fta_keys UUID[];

COMMENT ON COLUMN ods.trade_transaction.fta_keys IS
    'Optional explicit FTA UUIDs from source data. NULL = derive from partner_code via nds.fta_member.';
