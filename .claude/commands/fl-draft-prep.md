# FL Draft Prep

Build and refresh the draft research workbook (`draft_guide/Fantasy_Life_2027_Draft_Research.xlsx`) before a Fantasy Life draft.
First used for the Oct 25, 2026 draft (2027 league year). Works in Claude Code; the method (sources, EV model, pitfalls) can be
pasted into chat/Cowork if you only want the research.

## When to use
- `/fl-draft-prep` — refresh everything before the draft (run ~weekly, then the day before).
- `/fl-draft-prep <category>` — refresh one category (e.g. `/fl-draft-prep nba`).
- Next year: copy `draft_guide/` to a new year, then follow "New year setup".

Rules decisions are in `CLAUDE.md` **Rulings** (cameos count, streaming scores 0, prior-year releases don't count, Olympic total medals, ...). Don't re-ask.

---

## What the workbook is
`draft_guide/data/<Category>.json` is the source of truth; `build_workbook.py` generates the xlsx. **Edit JSON, never the xlsx.**

| Tab | Purpose |
|---|---|
| `Master` | top 15 per category by EV with odds (same shape as the 2025 file) |
| `Draft Board` | every candidate, all 15 categories, ranked by value over replacement (VOR) |
| `Assumptions` | live inputs: point ladders, replacement rank N per category, bonus cap, risk λ — tweak in Excel and VOR recalculates |
| 15 category tabs + `Awards` | raw candidates: odds, probabilities, `mu`/`sd`, EV pieces, source / as-of / confidence |
| `QA` | missing sources, stale (>7 days) values, confidence-C names in the board top 10, bad probability sums |

**EV model.** EV = E[rank points] + E[bonus]. Rank points: Monte Carlo of each candidate (`mu`, `sd`) against the best 12 other candidates (≈ a drafted field), 13 pts best … 1 pt worst. Bonus: ladder × probability (live Excel formula): team sports 13 / 9 / 6.5 / 4 / 2.5 by round (title → lost final → lost conf final → …; p(final) = conference-champion odds), NCAAB from the Sweet 16, Tennis 4 / 2.5 per slam, Golf 6 / 2.5 per major, NASCAR final standing 13 / 9 / 6.5 / 4 / 2.5, Oscars 13 / 9 / 4 / 2.5, Grammys 7 / 3 / 1 (cap 13). VOR = EV − EV of the Nth-best option in that category.

**Timeline for a draft in year Y−1 for league year Y** (this is the easy thing to get wrong):
- NFL / NCAAF: the season in progress now (use current records + futures). NBA / NHL / NCAAB: the season that is starting. MLB / MLS / NASCAR / Golf / Tennis / Stock / Actor / Actress / Musician / Country: calendar Y.
- Oscars (Mar Y) honour year Y−1 films; Grammys (Feb Y; eligibility Aug 31 Y−2 → Aug 30 Y−1) honour Y−1 music. Awards bonuses are therefore priceable now, while the Actor/Actress **baseline** needs Y releases (Y−1 releases score 0).
- The IMF Oct WEO (second week of Oct) is the Country source; the April WEO of year Y is what the league scored last time.

---

**v2 adjustments (user feedback, Oct 8 2026) — keep these when refreshing:**
- `CERT` in `build_workbook.py` widens uncertainty by distance to the scored event: NFL/NBA/NHL/NCAAF and Golf/Tennis untouched; NCAAB, MLB, MLS, NASCAR get sd multipliers + mu/title-prob shrink; Stock is forced flat (pure luck).
- `MARKET` models the league over-drafting Grammy/Oscar names (Musician/Actor/Actress): field draft score = baseline + w x award-EV; replacement level = best candidate outside the field's first M picks. Board `Plan` column says TARGET LATE / let it come to you / skip.
- Country mu = IMF-published 2027 growth. DBnomics (`api.db.nomics.world`, IMF/WEO) is reachable from the runner but only carries the April 2025 vintage; imf.org itself is 403 even via cloudscraper. Replace with the Oct 13 2026 WEO upload.
- Box Office Mojo 2027 calendar: `boxofficemojo.com/calendar/2027-MM-DD/`, rows under `tr.mojo-group-label` carry real dates (saved in `raw/bom_calendar_*.json`).

## Step 1 — Pull fresh data (the sandbox can't reach most sites)

WebSearch is snippet-only; subagent reports are leads. Real prices come from an **Actions runner**:

1. `create_branch probe/<topic>` (or reuse one) and overwrite `.github/workflows/probe.yml` there with inline Python steps (pattern in `/fl-audit` Step 3). Give it `KALSHI_API_KEY`, `KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY`, `SUPABASE_URL`, `SUPABASE_KEY` env from secrets. Run it with `actions_run_trigger`; read the log with `get_job_logs` (big logs are saved to a file — `.replace('\\n','\n')`).
2. Useful pulls (all worked on 2026-10-08):
   - **Kalshi** via `projections._kalshi_get('/series')` + `_fetch_markets_for_series(ticker)`; price = mid of `yes_bid_dollars`/`yes_ask_dollars`, else `last_price_dollars`. Tickers: `KXSB-27`, `KXNBA-27`, `KXNHL-27`, `KXNCAAF-27` (titles); `KXNFLAFCCHAMP-27`, `KXNFLNFCCHAMP-27`, `KXNBAEAST-27`, `KXNBAWEST-27`, `KXNHLEAST-27`, `KXNHLWEST-27` (conference champions = p(final)); `KXOSCARACTO/ACTR/SUPACTO/SUPACTR-27` (win) and `KXOSCARNOM…-27` (nomination); `KXGRAMAOTY-69`, `KXGRAMBNA-69`, `KXGRAMMYNOMAOTY/ROTY/SOTY/NAOTY-69`; `KX1SONG` (artist gets a #1 this year), `KX10SONG`, `KXTOPSONG` (Hot 100). The next-year series suffix changes (`-28`, `-70`): list `/series` and filter by title. There was **no** 2027 MLB, NASCAR, MLS, golf-major or tennis-slam futures market yet (2026 ones only).
   - **Standings** from Supabase (`db.get_standing('MLS'|'MLB'|'NASCAR'|'Tennis'|'Golf')`): real OWGR top-N, ATP rankings (WTA is not in the dump), MLS points, MLB win%.
   - **Wikipedia** `List_of_American_films_of_<Y>` (wikitables: opening date, title, studio, cast text; the cast is the last `;`-separated segment). 89 films with billed leads for 2027; cameos are not listed.
   - **IMF DataMapper API returns 403** from the runner. For Country, ask Alex to upload the WEO "By Countries" CSV/XLS after the October release (he did it last year) and use the target-year column.
3. Save raw pulls under `draft_guide/raw/` (dated). Delete your `probe/*` branch if you can (the sandbox usually can't — list it in the report).

## Step 2 — Update the JSON
- Team sports: put Kalshi mids in `raw/kalshi_<date>.json` (see the 2026-10-08 file for the shape) and run `python3 draft_guide/kalshi_overlay.py draft_guide/raw/kalshi_<date>.json` — sets `p_champ` (title) and `p_final` (conference champion), confidence A, rescales unpriced teams.
- NFL/NCAAF: also update records, `mu` (projected win%) and the AP poll in `data/NFL.json` / `data/NCAAF.json`.
- `Awards.json`: Kalshi win + nomination prices per (person, category). Musician `grammy_ev` = 7×Σp(win big-3) + Σ(p(nom)−p(win)) + 3×p(win BNA) + other wins/noms (see `seeds/v1_seed_d.py` `grammy()`); cap 13.
- Actor/Actress: re-run `seeds/film_model.py`-style scoring after refreshing the Wikipedia pull; **tune the box-office/RT comps in `film_model.py`'s `M` table** (they are my estimates, tagged C). Check date slips (Avengers: Secret Wars Dec 17, 2027 may move to 2028) and streaming-only titles (score 0).
- Country: after the WEO file arrives, replace the priors with the real 2027 column; keep a `sd` that reflects forecast-vs-realised error (fragile/commodity states 8+, stable 0.5–1).
- Never invent a number: if you can't source it, set `confidence: "C"` and say why in `notes`.
- The v1 seed scripts (`draft_guide/seeds/`) are a one-time import kept for provenance — re-running them overwrites hand edits.

## Step 3 — Rebuild and check
```bash
pip install openpyxl numpy        # first time in a fresh sandbox
python3 draft_guide/build_workbook.py --today YYYY-MM-DD
```
Read the printed board and the `QA` tab: no ERRORs; WARNs explained. Formulas can be verified without LibreOffice (it doesn't open files in the cloud sandbox) with `pip install formulas` and `formulas.ExcelModel().loads(path).finish().calculate()`.
Send the xlsx to the user with SendUserFile (files must be under the working directory).

## Step 4 — Report
Per category: what's solid (A), what's soft (C), what changed since the last build (top-15 movers), and open questions (keeper rules, draft slot, rule changes).

## Refresh schedule used for the Oct 25, 2026 draft
Oct 8 v1 → Oct 13 IMF WEO (Country final) → ~Oct 15 NFL/NCAAF week 6–7 + futures → Oct 20 NBA opener → Oct 23–24 final pull and lock the board.

## New year setup
Copy `draft_guide/` → `draft_guide_<year>/`, update `OUT` name and the README text in `build_workbook.py`, clear `data/`, re-pull Step 1, bump the Kalshi `-27`/`-69` suffixes, update `FILM_PIPELINE`/`EVENT_END`/`NEXT_SEASON_START` per the `CLAUDE.md` 2027 checklist (the draft room `docs/draft.html` has `SESSION_ID`).
