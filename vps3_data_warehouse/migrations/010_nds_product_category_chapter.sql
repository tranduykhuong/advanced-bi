-- Migration 010: add category_chapter to nds.product
ALTER TABLE nds.product
    ADD COLUMN IF NOT EXISTS category_chapter TEXT;
