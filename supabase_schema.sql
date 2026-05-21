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

-- ── Buckley Bucks sportsbook ────────────────────────────────────────────────

-- One account per player (13 total). Email is the login key.
CREATE TABLE IF NOT EXISTS bb_accounts (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         TEXT UNIQUE NOT NULL,
    player_name   TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    balance       NUMERIC NOT NULL DEFAULT 500,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- One row per (type, subject) pair, seeded from projections.json each day.
CREATE TABLE IF NOT EXISTS bb_markets (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type        TEXT NOT NULL,        -- 'win' | 'top4'
    subject     TEXT NOT NULL,        -- player name being bet on
    odds_pct    NUMERIC NOT NULL,     -- probability 0-100 at open time
    status      TEXT NOT NULL DEFAULT 'open',  -- 'open' | 'settled'
    result      BOOLEAN,              -- TRUE=hit, FALSE=miss, NULL=pending
    settled_at  TIMESTAMPTZ,
    UNIQUE(type, subject)
);

-- One row per bet placed.
CREATE TABLE IF NOT EXISTS bb_bets (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id       UUID NOT NULL REFERENCES bb_accounts(id),
    market_id        UUID NOT NULL REFERENCES bb_markets(id),
    stake            NUMERIC NOT NULL,
    odds_pct         NUMERIC NOT NULL,       -- locked at placement time
    potential_payout NUMERIC NOT NULL,       -- stake × (100 / odds_pct)
    status           TEXT NOT NULL DEFAULT 'pending',  -- 'pending'|'won'|'lost'
    placed_at        TIMESTAMPTZ DEFAULT NOW(),
    settled_at       TIMESTAMPTZ
);

-- Seed frozen categories with empty data so they show up in the admin panel
INSERT INTO standings (category, data, frozen) VALUES
    ('NFL',   '{"standings": []}'::jsonb, TRUE),
    ('NCAAF', '{"poll": []}'::jsonb,      TRUE)
ON CONFLICT (category) DO NOTHING;
