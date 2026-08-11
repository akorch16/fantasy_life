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
- `odds.yml` (hourly at :23, skips 08:xx): `projections.py --odds-only` — refreshes Kalshi
  prop odds in projections.json (Monte Carlo untouched), auto-settles props whose Kalshi
  markets resolved, pays the ledger via `db.settle_sb_bet`, and maintains a GitHub issue
  listing overdue unsettled props. Commits only when odds/settlements actually changed.
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
| Golf | PGA Tour GraphQL API (statId 186) → `GOLF_2026_OWGR_STATIC` fallback | owgr.com 404s, ESPN 500s; PGA Tour AppSync key in scrapers.py `PGATOUR_API_KEY` |
| MLS, NASCAR | `data/mls.json` / `data/nascar.json` → Supabase → static | local file is a manual override; MLS data with >50 pts is rejected as stale |
| Actor, Actress | `data/actor.json` / `data/actress.json` (roster) + Supabase via OMDb scraper (live box office/RT) | movie-to-player assignments + release dates are hand-curated in the file; `scrape_actor`/`scrape_actress` refresh each movie's domestic box office + RT critic score from OMDb daily and merge in per-field (live wins when present). Requires `OMDB_API_KEY`; scraper no-ops harmlessly if unset. composite = (RT/100) × box office $M |
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
| `data/sb_adjustments.json` | hand-edited | take feature branch (HEAD); never delete entries |
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
| `OMDB_API_KEY` | scrapers.py (`scrape_actor`/`scrape_actress` — box office + RT via omdbapi.com, free tier 1,000 req/day) |

## Conventions

- **Never push to main.** Cut a fresh branch per task from origin/main; ship same-session via `/fl-merge`
  (squash PR + immediate merge). Long-lived branches pay a daily conflict tax — main gets
  ~4-5 automated commits/day from the workflows.
- Sportsbook bet definitions: the `BETS` array in `docs/sportsbook.html` (display) and
  `_PROP_DEFS` + `_PROP_SCHEDULE` (+ optional `_AUTO_SETTLE_RULES`) in projections.py
  (matching `id` strings). Every new bet needs a `_PROP_SCHEDULE` entry
  (`closes_at`, `resolves_by`) — see `/fl-bet`.
- **Settlement source of truth: `data/sb_settled.json`.** Settling = append
  `{"id", "outcome": yes|no|push}` there (see `/fl-settle`); the hourly `odds.yml` run pays
  winners, pins the prop in projections.json (`settled`+`outcome`), and the frontend derives
  closed/PUSH state from that JSON. No HTML/`_PROP_DEFS_SETTLED` edits — that list is gone.
  Wagering auto-locks client-side at `closes_at`; Kalshi-resolvable props settle themselves.
- **Sportsbook balance authority:** `db.py` `recalculate_sb_balance()` is the sole writer of
  `sb_players.balance`. Formula: `1000 + adjustment - wagered + won_returns`. Per-player baseline
  adjustments live in `data/sb_adjustments.json` (currently Jens=1438). The browser
  (`sbSyncState`) only inserts new `sb_bets` rows — it never writes balance or `settled_outcome`.
  `sbResetPlayer` no longer deletes bets. Use `dump-sb.yml` (workflow_dispatch) to inspect live
  Supabase state.
- projections.py odds sources, in priority order: Kalshi live markets → Monte Carlo
  pairwise sim → standings-based normal approximation (`_mlb_h2h`/`_mls_h2h`/`_pts_h2h`) → static `FALLBACK`.
- Headlines must only state facts present in Tavily snippets — the prompt forbids
  training-knowledge casting claims and stale events; keep those rules intact when editing headline.py.
- Skills: `/fl-merge` (ship to prod), `/fl-repair` (broken Actions run), `/fl-bonus`
  (award bonus points), `/fl-category-fix` (bad category data), `/fl-headline` (manual headline).
