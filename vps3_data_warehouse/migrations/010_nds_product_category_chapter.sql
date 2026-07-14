-- Migration 010: add chapter_name to nds.product
ALTER TABLE nds.product
    ADD COLUMN IF NOT EXISTS chapter_name TEXT;
