# Fantasy Life 2026 — Claude Context

13-person fantasy league. Each player drafted real teams/athletes/musicians/actors/stocks
across 15 categories. Rotisserie scoring (rank 1 of 13 → 13 pts) plus bonus points.
Frontend is static GitHub Pages served from `docs/`; data flows in via daily GitHub Actions.

## Pipeline

```
scrapers.py ──→ Supabase (standings table)
                    │
scoring.py  ←───────┘     reads Supabase + data/*.json + static fallbacks
    │
    └──→ docs/scores.json ──→ projections.py (Kalshi odds + Monte Carlo)
                                   │
                                   └──→ docs/projections.json
docs/*.html read both JSONs client-side (GitHub Pages, no server).
Supabase also backs the sportsbook (sb_players, sb_bets) and draft room directly from the browser.
```

- `daily.yml` (08:00 UTC): scrapers → scoring → projections → commit both JSONs to main.
- `headline.yml` (07:00 UTC): Tavily news search + Claude writes `headline` into scores.json.
  Manual dispatch always passes `--force` (bypasses the 24h dedup guard); scheduled runs don't.
  scoring.py re-preserves `headline`/`headline_generated_at` when it rewrites scores.json.
- `app.py`/`templates/` are the legacy Flask app — **not** the production frontend. Prod is `docs/`.

## League constants

- **Players (13):** Tim, Wu, Jens, Todd, Mitchell, Shep, Theo, Feder, Fryar, Korch, Molmen, Jamzee, Buckley
- **Categories (15):** NFL, NBA, MLB, NHL, NCAAF, NCAAB, Tennis, Golf, NASCAR, MLS, Actor, Actress, Musician, Country, Stock
- **Key dates:** sportsbook MLB/MLS standings bets close Jul 1; Country (World Cup) scored from the tournament; season ends Dec 31, 2026
- **Canonical picks:** `draft_picks_2026.py` (`DRAFT_PICKS_2026`). Also mirrored in
  `projections.py` pick dicts and `headline.py` `DRAFT_SUMMARY` — keep all three in sync
  until they're DRY'd to import from the canonical file.

## Source of truth per category

| Category | Primary source | Notes |
|---|---|---|
| NFL, NCAAF | static dicts in scoring.py | 2025 seasons, frozen |
| NBA, MLB, NHL, NCAAB | Supabase (live scrape) | sports-reference daily |
| Tennis | Supabase | women's rank gets +0.5 (Amend. 7.4) |
| Golf | `GOLF_2026_OWGR_STATIC` in scoring.py | ESPN/OWGR 403-blocked |
| MLS, NASCAR | `data/mls.json` / `data/nascar.json` → Supabase → static | local file is a manual override; MLS data with >50 pts is rejected as stale |
| Actor, Actress | `data/actor.json` / `data/actress.json` | hand-curated; Supabase only as fallback. composite = (RT/100) × box office $M |
| Musician | Supabase (Billboard) | |
| Country | `data/country.json` only | hand-edited IMF data; never Supabase |
| Stock | Supabase (Yahoo) | (L)/(S) = long/short |
| Bonuses | `data/bonuses.json` **overrides** Supabase | append entries here, never delete history |

## File ownership (merge-conflict rules)

| File | Written by | Conflict rule |
|---|---|---|
| `docs/scores.json` | scoring.py via Actions | always take **origin/main** |
| `docs/projections.json` | projections.py via Actions | always take **origin/main** |
| `data/bonuses.json` | hand-edited | **manually merge** — combine entries from both sides |
| `data/*.json` (others) | hand-edited overrides | take feature branch (HEAD) |
| `*.py`, `docs/*.html`, `.github/**` | hand-edited | take feature branch (HEAD) |
| `docs/sb-schema.sql`, `docs/draft-schema.sql` | hand-edited | reference copies of Supabase schemas |

## Secrets (GitHub Actions)

| Secret | Used by |
|---|---|
| `SUPABASE_URL`, `SUPABASE_KEY` | scrapers.py, scoring.py, db.py |
| `ANTHROPIC_API_KEY` | headline.py |
| `TAVILY_API_KEY` | headline.py (news search) |
| `KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY` | projections.py (RSA-PSS signed requests) |

## Conventions

- **Never push to main.** Cut a fresh branch per task from origin/main; ship same-session via `/fl-merge`
  (squash PR + immediate merge). Long-lived branches pay a daily conflict tax — main gets
  ~4-5 automated commits/day from the workflows.
- Sportsbook bets live in two places that must stay consistent: the `BETS` array in
  `docs/sportsbook.html` and `_PROP_DEFS` in projections.py (matching `id` strings).
  Settling a bet means odds → 100/0 + `settled: true` in both.
- projections.py odds sources, in priority order: Kalshi live markets → Monte Carlo
  pairwise sim → standings-based normal approximation (`_mlb_h2h`/`_mls_h2h`/`_pts_h2h`) → static `FALLBACK`.
- Headlines must only state facts present in Tavily snippets — the prompt forbids
  training-knowledge casting claims and stale events; keep those rules intact when editing headline.py.
- Skills: `/fl-merge` (ship to prod), `/fl-repair` (broken Actions run), `/fl-bonus`
  (award bonus points), `/fl-category-fix` (bad category data), `/fl-headline` (manual headline).
