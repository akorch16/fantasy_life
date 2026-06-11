# Fantasy Life 2026 🏆

Live leaderboard for the 2026 Fantasy Life season.
13 players · 15 categories · rotisserie + bonus scoring

**Production site:** GitHub Pages, served from `docs/` — leaderboard, projections,
sportsbook, draft room, rules, calendar, trips.

**Architecture, data sources, conventions:** see [CLAUDE.md](./CLAUDE.md) — the living doc
for how the pipeline fits together.

---

## Quick start (local)

```bash
pip install -r requirements.txt

# Refresh data → Supabase (needs SUPABASE_URL / SUPABASE_KEY)
python scrapers.py

# Compute scores → docs/scores.json
python scoring.py

# Compute odds + projections → docs/projections.json (needs Kalshi keys; falls back to static)
python projections.py

# Preview the static site
python -m http.server -d docs 8000
```

The Flask app (`app.py`, `templates/`) is the legacy local admin UI, not the production frontend.

---

## Automation

| Workflow | Schedule | Does |
|---|---|---|
| `.github/workflows/daily.yml` | 08:00 UTC | scrape → score → project → commit JSONs |
| `.github/workflows/headline.yml` | 07:00 UTC | Tavily news + Claude → FL News ticker headline |

Secrets required: `SUPABASE_URL`, `SUPABASE_KEY`, `ANTHROPIC_API_KEY`, `TAVILY_API_KEY`,
`KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY`.

---

## Scoring rules

Full rules live on the site (`docs/rules.html`). Short version:

- **Baseline (rotisserie):** rank each pick within its category; rank 1 = 13 pts, rank 13 = 1 pt; ties use RANK.AVG.
- **Bonuses (Amend. 7.14):** championships, runner-ups, majors, Oscars, Grammys, World Cup placements — entered in `data/bonuses.json`.
- **Tennis (Amend. 7.4):** women's ranking adjusted +0.5 before sorting.
