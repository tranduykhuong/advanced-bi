-- Migration 001: widen stage.stage_csv.qty_unit for UN Comtrade unit strings
-- Example: 'U (jeu/pack)' is 12 chars; legacy DDL used VARCHAR(10).
-- Safe to re-run: ALTER TYPE to the same type is a no-op in PostgreSQL.

ALTER TABLE stage.stage_csv
    ALTER COLUMN qty_unit TYPE VARCHAR(50);
