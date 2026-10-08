# FL Audit

Biweekly health audit of Fantasy Life: find the places where the app's numbers disagree with
reality, fix them, and ship. Built from the Oct 2026 debugging marathon — every check below is
a bug class that really happened.

## When to use

- `/fl-audit` — full audit (run on the 1st/15th; `audit.yml` opens an issue with the scripted findings).
- `/fl-audit <category>` — judgment pass on one category only (e.g. `/fl-audit musician`).
- After a season rollover, a new data source, or a rules change.

Two halves:
1. **Scripted** — `python3 audit.py` (also what `audit.yml` runs). Fast, no network, deterministic.
2. **Judgment** — you, with web search and Actions-runner probes: does the data match what *actually
   happened*? Scripts can't know that Zverev won two majors; you can.

Whenever the judgment pass finds a new class of bug that a script could catch, **add a check to
`audit.py`** so the next audit catches it for free.

---

## Unattended mode (the scheduled routine)

A recurring routine starts a fresh session on the 1st and 15th (after `audit.yml` has opened that
cycle's `audit` issue) and runs this runbook with **no human watching**. In that mode:

- **Open PRs; never merge them.** No `/fl-merge`, no pushing to main, no `daily.yml` runs. One PR per
  logical fix, branch `audit/<yyyy-mm-dd>-<topic>`, PR body = what was wrong, evidence (links), and the
  point impact per player.
- **Fix only what is unambiguous**: a matching/spelling bug, a stale pipeline entry, a doc that
  contradicts the code, a result that is a plain fact (a bracket outcome, a medal table). Anything that
  needs a judgment call or changes standings by interpretation (rules, disputed results, cameo
  questions) goes in the report as a **decision for the user**, not in a PR.
- **Don't re-litigate `CLAUDE.md` Rulings.** If new evidence contradicts one, flag it; don't change it.
- **Evidence standard:** every claim in a PR cites a primary source or an Actions-runner probe. Search
  snippets alone are leads, not facts — if you can't confirm it, say "couldn't verify".
- **Report**: post one comment on the cycle's `audit` issue: PRs opened (with point impact), decisions
  needed, categories verified clean, things you couldn't verify. If nothing is wrong say so briefly.
- Delete any `probe/*` branch you created.

---

## Step 0 — Orient

```bash
git fetch origin main && git checkout -q -b audit/$(date +%Y-%m-%d) origin/main   # local checkout lags main (bot commits)
python3 audit.py                       # scripted findings
```

If an `audit` GitHub issue exists for this cycle, start from it (it ran with Supabase credentials,
so its *frozen-category* and *stale-scraper* findings are authoritative; your local run's are not).
Read `CLAUDE.md` — the **Rulings** section lists decisions the user already made; don't re-ask them.

---

## Step 1 — Triage the scripted findings

| Finding | Usual cause | Fix |
|---|---|---|
| `match` — pick has no data | Source spells the name differently (`LA Clippers` vs `Los Angeles Clippers`, `Åberg` vs `Aberg`, `FC`/`SC` suffixes). The pick is **silently ranked last**. | Add an alias in `team_matches()` / handle in `name_matches()` (`scoring.py`). Verify against the live Supabase row (probe — Step 3). NCAAB unranked teams are legitimately empty. |
| `ties` — ≥4-way tie in a sports category | Wiped/0-0 or placeholder standings table | Look at the Supabase row; restore + freeze (`db.py repair_*_freeze`) |
| `freshness` (ERROR) — stale and not frozen | Scraper failing; the daily log says `DEGRADED` | `/fl-repair` |
| `rollover` — next season opens soon, category unfrozen | The new 0-0 table will overwrite final standings (NHL, NCAAB, NASCAR all got burned) | Freeze first: `dump-sb.yml` → `--freeze-nba` / a `--repair-*-freeze` command |
| `bonus` — scores.json ≠ bonuses.json, or > 13 | Typo, wrong player key, cap | Fix `data/bonuses.json` |
| `films` — FILM_PIPELINE still simulates a released film | Pipeline entry not pruned when real numbers landed → **double-counted** | Delete it from `FILM_PIPELINE` in `projections.py` |
| `films` — pipeline title ≠ roster title | Title mismatch (`Jumanji` vs `Jumanji: Open World`) | Make them match the official title |
| `films` — released, no box office | Title doesn't match Box Office Mojo's listing | Use the official title (`_norm_title` is case/punctuation-insensitive only) |
| `projections` — no Kalshi markets | Bad `KALSHI_PRIVATE_KEY` or dead tickers → static `FALLBACK` | `/fl-repair` (Kalshi section) |
| `docs` — calendar entry stale | `docs/calendar.html` not updated | Step 5 |

---

## Step 2 — Judgment pass (per category)

Compare `docs/scores.json` against reality. Pull the live file first:
`git show origin/main:docs/scores.json`. For each category verify **two things**: baseline rank
inputs and bonus points. Use WebSearch for results; for anything the sandbox can't fetch use a probe (Step 3).

| Category | Verify | Authority |
|---|---|---|
| NFL / MLB / NBA / NHL | Bonus tier = round each team was **eliminated** in (lost first round = 2.5 → champion 13). Alive teams are credited at their guaranteed floor and need re-tiering as series resolve. MLB: check each round as it finishes. | Official bracket |
| NCAAF / NCAAB | Champion 13, runner-up 9, F4 6.5, E8 4.0, S16 2.5 (NCAAB: nothing before the Sweet 16); poll baseline is the final poll | Official results / final AP poll |
| Tennis | Major winners (+4) and runners-up (+2.5) per drafted player; women's rank has +0.5 (Amend. 7.4) | Official draws |
| Golf | Major winner +6, runner-up +2.5; OWGR rank matches (accents!) | Official leaderboards |
| NASCAR | Baseline frozen at Aug 29 seeds. **Bonus** = final Chase standings 1st–5th: 13 / 9 / 6.5 / 4 / 2.5 (no eliminations in 2026; finale Nov 8, Homestead) | nascar.com standings |
| MLS | Baseline = current points; check the source's team names; Cup/playoff bonus when it happens | mlssoccer.com |
| Actor / Actress | See Step 4 | BOM, IMDb/TMDB, RT |
| Musician | Chart tally vs Billboard weekly charts (2026 issues only); **Grammy** bonus per pick: Record/Album/Song of the Year win +7, other win +3, nomination +1, cap 13 | Billboard; grammy.com full nominee list |
| Country | Olympics bonus by **total medal count** (1st 13, 2nd 9, 3rd 6.5, 4th 4, 5th 2.5); World Cup bonus by finish; Country + WC capped at 13 combined; GDP data after each IMF WEO (Apr, Oct) | IOC medal table, FIFA, IMF WEO |
| Stock | Long/short sign, YTD % vs a second source | Yahoo/Google Finance |

Spot-check one number per live source against a second source every audit (e.g. a top-10 chart,
a box office gross, a standings row). Sources fail *quietly*: OMDb served Spider-Man $300M low;
Wikipedia's year tables leaked 2025 weeks into 2026 and dropped multi-week #1 runs.

---

## Step 3 — Ground truth the sandbox can't reach (probe pattern)

The dev sandbox blocks most sites (Wikipedia, BOM, imdb, ESPN…) and subagent web results are
**snippet-based** — treat them as leads, not facts. The Actions runner has open internet and the
secrets. To see what a source really returns:

1. Create a throwaway branch `probe/<topic>` (`create_branch`).
2. Overwrite `.github/workflows/probe.yml` on that branch with a step that runs inline Python
   (add `env: SUPABASE_URL/SUPABASE_KEY: ${{ secrets.* }}` to read live Supabase rows).
3. `actions_run_trigger` → `probe.yml` on that ref; read output with `get_job_logs`
   (huge logs get saved to a file — `.replace('\\n','\n')` then grep with Python).
4. Never merge the probe branch. Delete it when done.

This is how the Clippers bug (`LA Clippers` in Supabase) and the Billboard fix were confirmed.

---

## Step 4 — Actor / Actress roster completeness

For each of the 13 actor + 13 actress picks, find their 2026 releases (BOM year listing, IMDb,
TMDB) and compare with `data/actor.json` / `data/actress.json` and `FILM_PIPELINE`.

Rules already decided (see CLAUDE.md Rulings): cameos count; being only a headshot/photo does not;
streaming-only titles are listed with `"streaming": true` and score nothing; 2025 releases don't
count; score = RT critics/100 × domestic box office in $M. Don't trust a "voice cameo" claim without
the cast list. Unreleased titles go in `FILM_PIPELINE` **and** the roster; released ones come out
of `FILM_PIPELINE` the same day.

---

## Step 5 — Docs and copy rot

- `docs/calendar.html` — completed events move to Completed Months with results; add the next
  month's schedule; fix TBD dates; verify venues and dates (several carried over from 2025).
- `docs/rules.html` — descriptions must match what `scoring.py` actually does (Actor/Actress and
  Musician were stale).
- `CLAUDE.md` and `.claude/commands/*.md` — source-of-truth table still true? (`fl-category-fix.md`
  once said Actors came from TMDB.)
- Recap/newsletter fact-check (when asked): check every number against live `scores.json` and
  `projections.json`; re-pull the odds on send day and apply the rounding rule (nearest 100 under 1,000; nearest 1,000 up to
  15,000; nearest 10,000 above 15,000 and under 100,000; nearest 100,000 from 100,000 up). Win odds below
  ~0.1% are Monte Carlo noise (10,000 sims) — don't present the tail as signal.

---

## Step 6 — Fix and ship

- One logical fix per branch/PR; ship each with `/fl-merge`, then trigger `daily.yml` for any
  data/logic change and **verify the live JSON** (daily.yml also regenerates projections.json).
  Pure `docs/*.html` changes go live on merge.
- `data/bonuses.json` **overrides** Supabase per (category, player): to zero a bonus write an
  explicit `0.0` — omitting the entry falls back to the stale Supabase value.
- Freezing a category: `dump-sb.yml` command (`--repair-*-freeze`, `--freeze-nba`).
- Don't reopen settled rulings. Anything that changes standings by a judgment call (a rules
  interpretation, a disputed result) → ask the user first and show the point impact.

---

## Step 7 — Report

Finish with: **Fixed** (what, PR #, point impact on whom), **Needs a decision** (with the options and
who gains/loses), **Verified clean** (categories checked), **Couldn't verify** (and why). Close the
audit issue with a link to the PRs.
