-- Fantasy Life 2026 — Supabase Schema
-- Paste this into your Supabase project: SQL Editor → New Query → Run

-- Stores all category standings data as JSON blobs, keyed by category name
CREATE TABLE IF NOT EXISTS standings (
    category    TEXT PRIMARY KEY,
    data        JSONB NOT NULL,
    frozen      BOOLEAN DEFAULT FALSE,  -- if true, scrapers will skip this category
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Stores bonus points: one row per player+category combo
CREATE TABLE IF NOT EXISTS bonuses (
    id          SERIAL PRIMARY KEY,
    category    TEXT NOT NULL,
    player      TEXT NOT NULL,
    points      NUMERIC NOT NULL DEFAULT 0,
    reason      TEXT,
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(category, player)
);

-- Seed frozen categories with empty data so they show up in the admin panel
INSERT INTO standings (category, data, frozen) VALUES
    ('NFL',   '{"standings": []}'::jsonb, TRUE),
    ('NCAAF', '{"poll": []}'::jsonb,      TRUE)
ON CONFLICT (category) DO NOTHING;
