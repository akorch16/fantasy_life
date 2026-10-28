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
                                   └──→ docs/projections.json (+ docs/projection_history.json daily snapshot)
docs/*.html read both JSONs client-side (GitHub Pages, no server).
Supabase also backs the sportsbook (sb_players, sb_bets) and draft room directly from the browser.
```

- `daily.yml` (6:48 AM ET via a Claude scheduled task → workflow_dispatch; GitHub cron 12:17 UTC is a backup that skips itself if today already ran — GitHub cron was starting 4-9 h late): scrapers → scoring → projections → commit both JSONs to main.
- `odds.yml` (hourly at :23, skips 08:xx): `projections.py --odds-only` — refreshes Kalshi
  prop odds in projections.json (Monte Carlo untouched), auto-settles props whose Kalshi
  markets resolved, pays the ledger via `db.settle_sb_bet`, and maintains a GitHub issue
  listing overdue unsettled props. Commits only when odds/settlements actually changed.
- `headline.yml` (07:00 UTC): Tavily news search + Claude writes `headline` into scores.json.
  Manual dispatch always passes `--force` (bypasses the 24h dedup guard); scheduled runs don't.
  scoring.py re-preserves `headline`/`headline_generated_at` when it rewrites scores.json.
- `audit.yml` (1st & 15th, 15:17 UTC): `audit.py` — scripted health checks (unmatched picks, stale/unfrozen
  categories near a season rollover, bonus bookkeeping, FILM_PIPELINE double-counts, projection drift,
  stale calendar) → opens an `audit` GitHub issue. Run `/fl-audit` for the judgment half.
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
| NFL, NCAAF, NASCAR, NCAAB | static dicts in scoring.py (NFL/NCAAF); `data/nascar.json` → Supabase → static (NASCAR); Supabase poll (NCAAB) | 2025 seasons frozen (NFL/NCAAF); NASCAR frozen at the real 2026 regular-season end (Aug 29, Coke Zero Sugar 400) since NASCAR resets all Chase qualifiers' points to a seed-based scale once the playoffs start — see `data/nascar.json`'s `_note` and `db.py repair_nascar_freeze()`; NCAAB frozen at the final 2025-26 AP Top 25 poll (Michigan won the title, April 2026) since this league's NCAAB category tracks that already-concluded season, not whatever a live scrape of a not-yet-started new season would show — see `db.py repair_ncaab_freeze()` |
| NBA, MLB, NHL | Supabase (live scrape) | sports-reference daily; NHL was frozen/restored once already (2026-27 season rollover wiped it, see `db.py repair_nhl_freeze()`) |
| Tennis | Supabase | women's rank gets +0.5 (Amend. 7.4) |
| Golf | PGA Tour GraphQL API (statId 186) → `GOLF_2026_OWGR_STATIC` fallback | owgr.com 404s, ESPN 500s; PGA Tour AppSync key in scrapers.py `PGATOUR_API_KEY` |
| MLS | `data/mls.json` → Supabase → static | local file is a manual override; freshness-timestamp comparison in `select_standings()` is the only staleness guard (the old >50-pts rejection heuristic was removed — it started rejecting legitimate fresh data as a season progresses) |
| Actor, Actress | `data/actor.json` / `data/actress.json` (roster) + Supabase via OMDb scraper (live box office/RT) | movie-to-player assignments + release dates are hand-curated in the file; `scrape_actor`/`scrape_actress` refresh each movie daily and merge in per-field (live wins when present). Domestic (US+Canada) box office comes from Box Office Mojo's year listing (fallback The Numbers) via `_fetch_domestic_grosses()` — OMDb's `BoxOffice` field is a stale snapshot for films still earning (Spider-Man: BND was $300M low), so it's only a last-resort fallback; RT critic score comes from OMDb (`OMDB_API_KEY`). Roster titles are matched to listings by `_norm_title()` (case/punctuation-insensitive, `&`=`and`), so use the film's official title. composite = (RT/100) × box office $M |
| Musician | Supabase (Billboard) | `scrape_billboard` tallies the top 10 of every 2026 weekly Hot 100 issue straight from billboard.com (Saturday issue dates; refuses to save if any published week fails). Score = 2×#1 weeks + top-10 song-weeks, 2026 issues only. Do NOT use Wikipedia's year-summary tables: their "weeks in top ten" are whole-run totals (2025 weeks leak in) and rowspan'd cells drop multi-week #1 runs |
| Country | `data/country.json` only | hand-edited IMF data; never Supabase |
| Stock | Supabase (Yahoo) | (L)/(S) = long/short |
| Bonuses | `data/bonuses.json` **overrides** Supabase | append entries here, never delete history |

## File ownership (merge-conflict rules)

| File | Written by | Conflict rule |
|---|---|---|
| `docs/scores.json` | scoring.py via Actions | always take **origin/main** |
| `docs/projections.json` | projections.py via Actions | always take **origin/main** |
| `docs/scores_2027.json`, `data/standings_2027.json` | scoring_2027.py via Actions | always take **origin/main** |
| `docs/projection_history.json` | projections.py via Actions (one snapshot per UTC day, full runs only; backfilled from git history to 2026-05-20) — feeds the Odds Over Time chart on projections.html | always take **origin/main** |
| `data/bonuses.json` | hand-edited | **manually merge** — combine entries from both sides |
| `data/*.json` (others) | hand-edited overrides | take feature branch (HEAD) |
| `*.py`, `docs/*.html`, `.github/**` | hand-edited | take feature branch (HEAD) |
| `docs/sb-schema.sql`, `docs/draft-schema.sql` | hand-edited | reference copies of Supabase schemas |
| `docs/sb-ledger-schema.sql`, `docs/sb-ledger-phase3.sql` | hand-edited | reference copies of Supabase schema/RPC — sb_ledger is the sportsbook balance source of truth |

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
  `_AUTO_SETTLE_RULES` kinds: `wins`/`either_wins` (resolved Kalshi markets), `score_cmp` (compare two owners
  on the leaderboard generated inside a UTC window — `settle_rules.py`; tie → push; stale category data → stays open),
  `tavily_series` (series winner from Tavily news + two Claude reads that must agree on a verbatim-quoted result;
  runs in the hourly job, needs `TAVILY_API_KEY`/`ANTHROPIC_API_KEY`, no-ops without them).
- **Sportsbook balance authority:** `sb_ledger` (Supabase, append-only — see `docs/sb-ledger-schema.sql`)
  is the sole source of truth for balance history: every bet placement, settlement, and manual
  adjustment is a row (`event_type`, `delta`), RLS-locked so only `service_role` can write, with
  triggers rejecting any `UPDATE`/`DELETE`. `db.py` `recalculate_sb_balance()` is the sole writer of
  `sb_players.balance` (a cached projection), formula `1000 + sum(sb_ledger.delta for that player)`.
  `place_bet` (the Supabase RPC, `docs/sb-ledger-phase3.sql`) checks available balance the same way.
  `data/sb_adjustments.json` is retired — its one entry (Jens) was backfilled into `sb_ledger` as a
  `balance_adjusted` event; do not resurrect that file. The browser (`sbSyncState`) only inserts new
  `sb_bets` rows — it never writes balance or `settled_outcome`. `sbResetPlayer` no longer deletes
  bets. Use `dump-sb.yml` (workflow_dispatch) to inspect live Supabase state, or its `--migrate-ledger`
  command to re-verify the ledger fold against live balances.
- **Projection bookkeeping invariant:** `simulate()` starts every player from their *current* total, strips only
  the baseline of re-ranked categories (actor/actress/stock/country), and adds playoff/major bonuses as deltas
  over what is already banked — so league-wide Σ(projected − current) ≥ 0 and `PROJ = NOW + EXP` per row
  (`projected_additional` is derived from the sim, not a separate heuristic). Finished events (all four golf
  majors, all four slams) are skipped via `EVENT_END`; add new dates there. `audit.py` enforces the invariant.
- **MLS playoff bonuses in projections:** `mls_playoffs.py` simulates the rest of the regular season from the stored
  30-team table + `data/mls_schedule.json` (fixture snapshot, regenerate locally with
  `python3 mls_playoffs.py --refresh-schedule` — ESPN is blocked from Actions), seeds 9 per conference, plays the 8-v-9
  play-in (loser 0) and the bracket (lost R1 2.5 / semi 4.0 / conf final 6.5 / Cup 9.0 / champion 13.0), calibrated to
  Kalshi MLS Cup prices ≥2%. It falls back to the champion-only sampler when the table is missing/behind, or once any MLS
  bonus is banked (real bracket results exist).
- **NASCAR Chase bonuses in projections:** `nascar_chase.py` races out the remaining Chase events from the live points
  table (cf.nascar.com points + race-list feeds — Actions only; snapshot in `data/nascar_chase.json`, committed by
  daily.yml, used only while no listed race has run). Per race: Plackett-Luce finish + 2 stages over 38 cars
  (win 40 / 2nd 35 / −1 per place; stages 10..1), superspeedways mostly luck; contender skills fitted to Kalshi title
  prices. Final top 5 → 13 / 9 / 6.5 / 4 / 2.5. Falls back to the title-odds-only top-5 sampler if standings are unavailable.
- **2027 league (drafted Oct 25, 2026):** rosters in `draft_picks_2027.py` (board column "ChatGPTodd" = Todd). Same scoring as 2026
  (rank 13..1 per category, RANK.AVG ties, plus bonuses). `scoring_2027.py` (daily.yml step, `continue-on-error`) writes
  `docs/scores_2027.json` and ranks only categories whose 2027 season is underway — NFL/NBA/NHL (win % / points %), NCAAF (AFCA Coaches
  Poll), NCAAB (AP Top 25) — from ESPN + the NHL API (raw rows cached in `data/standings_2027.json`; a failed fetch re-scores from
  the cache and flags it stale). MLB, MLS, NASCAR, Golf, Tennis, Actor, Actress, Musician, Country and Stock score 0 until their 2027
  seasons start. Bonuses live in `data/bonuses_2027.json` (same convention as `bonuses.json`); Country is uncapped and carries the
  Women's World Cup ladder in `Country_WWC` (13/9/6.5/4/2.5 by round eliminated, lost Round of 16 = 2.5 — assumed, unconfirmed).
  Site: `index.html?season=2027` and `projections.html?season=2027` (nav tabs "2027 Standings" / "2027 Projections"); the 2026
  pages are unchanged. `docs/projections_2027.json` is the static pre-season simulation from `draft_guide/season_sim_2027.py --site`
  (guide odds, not refreshed daily); the page overlays live standings for Now/+Exp. Women's World Cup odds: `draft_guide/wwc_model.py`.
- projections.py odds sources, in priority order: Kalshi live markets → Monte Carlo
  pairwise sim → standings-based normal approximation (`_mlb_h2h`/`_mls_h2h`/`_pts_h2h`) → static `FALLBACK`.
- **League calendar: `docs/calendar.json` is the single source of truth.** The Calendar tab renders from it (status =
  computed from dates, never typed), `headline.py` derives every search from it (`events[].search` windows + `seasons[]`:
  while a category's season is active every pick is searched by name, in groups of 4, 12 group-queries/day rotating so each
  pick is searched at least every ~3 days), and `projections.py` derives `EVENT_END` from `events[].sim_key`. Add or move an
  event there only — never in the HTML or Python. `audit.py` validates it and fails if any pick can't be searched.
  FL News model: `HEADLINE_MODEL` in headline.py (Sonnet 5.5, server-side refusal fallback on).
- Headlines must only state facts present in Tavily snippets — the prompt forbids
  training-knowledge casting claims and stale events; keep those rules intact when editing headline.py.
## Rulings (decided by the league — don't re-ask)

- **Actor/Actress:** score = RT critic % × domestic box office ($M), summed over a pick's 2026 releases.
  Cameos count; a photo/headshot-only appearance does not; streaming-only titles are listed
  (`"streaming": true`) but score nothing; 2025 releases don't count (Oscar bonuses are separate).
- **Musician:** 2 × weeks at #1 + top-10 song-weeks (each song counts, so a 9-song week = 9), from 2026
  weekly Hot 100 issues only. Grammy bonus: Record/Album/Song of the Year win +7, other win +3,
  nomination +1.
- **Bonus cap:** 13 per category (Amend. 7.14), **except Country, which is uncapped** (Oct 2026): Olympics + World Cup
  bonuses simply add (Fryar/Norway 13 + 4 = 17).
- **Country/Olympics:** ranked by **total medal count**, not golds. World Cup by finish.
- **Playoff bonuses (NFL/MLB):** keyed to the round a team was *eliminated* in — lost first round 2.5,
  next 4.0, next 6.5, lost the final 9.0, champion 13.0; teams still alive are credited at their
  guaranteed floor. NCAAB: nothing before the Sweet 16 (S16 2.5, E8 4.0, F4 6.5, runner-up 9.0, champ 13.0).
- **NASCAR:** baseline frozen at the Aug 29 regular-season finish; bonus = final Chase standings 1st–5th
  (13 / 9 / 6.5 / 4 / 2.5). The 2026 Chase has no eliminations (title = most points over 10 races).
- **Odds (page and recaps):** round American odds to the nearest 100 under 1,000; nearest 1,000 up to 15,000;
  nearest 10,000 above 15,000 and under 100,000; nearest 100,000 from 100,000 up. 0% shows as +∞.
  (Implemented in `toAmericanOdds()` in `docs/projections.html`.)

- Skills: `/fl-draft-prep` (pre-draft research workbook, `draft_guide/`), `/fl-audit` (biweekly audit), `/fl-merge` (ship to prod), `/fl-repair` (broken Actions run), `/fl-bonus`
  (award bonus points), `/fl-category-fix` (bad category data), `/fl-headline` (manual headline).
