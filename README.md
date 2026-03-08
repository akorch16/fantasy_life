# Fantasy Life 2026 🏆

Live leaderboard for the 2026 Fantasy Life season.  
13 players · 15 categories · rotisserie + bonus scoring

---

## Quick Start

```bash
cd fantasy_life

# Install dependencies
pip install flask requests beautifulsoup4

# Seed demo data (works out of the box, no internet needed)
python scrapers.py

# Start the server
python app.py
```

Then open http://localhost:5000

---

## Project Structure

```
fantasy_life/
├── app.py                  # Flask web server
├── scoring.py              # Scoring engine (baseline + bonus)
├── scrapers.py             # Data scrapers + demo data seeder
├── draft_picks_2026.py     # All 13 players × 15 categories
├── data/                   # JSON data cache (auto-created)
│   ├── nfl.json
│   ├── nba.json
│   ├── ... (one file per category)
│   └── bonuses.json        # Manually-entered bonus points
└── templates/
    ├── index.html           # Main leaderboard
    └── admin.html           # Admin panel
```

---

## Scoring Rules

### Baseline (Rotisserie)
- Rank each of the 13 picks within a category
- Rank 1 = 13 pts, Rank 13 = 1 pt
- Ties use RANK.AVG (e.g. two players tied for 2nd both get 12.5)
- **Tennis special (Amend. 7.4):** Women's ranking adjusted +0.5 before sorting

### Bonus Points (Amendment 7.14)
| Event | Points |
|-------|--------|
| Sports Champion | 13 |
| Runner-up | 9 |
| Semi-finalist | 6.5 |
| Quarter-finalist | 4 |
| Round of 16 | 2.5 |
| Tennis/Golf Major Win | 4/6 |
| Tennis/Golf Major Runner-up | 2.5 |
| Oscar Lead Win | 13 |
| Oscar Supporting Win | 9 |
| Oscar Lead Nom | 4 |
| Oscar Supporting Nom | 2.5 |
| Grammy BSAR | 7 |
| Grammy Other Win | 3 |
| Grammy Nomination | 1 (cap 13) |
| Country Top 5 Olympic/WC | 13/9/6.5/4/2.5 |

---

## Data Sources

| Category | Source | Update Freq |
|----------|--------|-------------|
| NFL/NBA/MLB | sports-reference.com | Daily |
| NHL | hockey-reference.com | Daily |
| NCAAF/NCAAB | AP Poll via sports-reference | Weekly |
| Tennis | ATP/WTA rankings | Daily |
| Golf | OWGR via golftoday.co.uk | Weekly |
| NASCAR | NASCAR.com standings | Weekly |
| MLS | mlssoccer.com | Weekly |
| Actor/Actress | Box Office Mojo + Rotten Tomatoes | Weekly |
| Musician | Billboard Hot 100 | Weekly |
| Country | IMF WEO API | Annual |
| Stock | Yahoo Finance API | Daily |

---

## Admin Panel

Visit http://localhost:5000/admin  
Password: `fantasyboss`

Use admin panel to:
- Manually add bonus points (playoffs, Oscars, Grammys, etc.)
- Trigger data refresh
- View all active bonuses

---

## Running Live Scrapers

When you have internet access, run `python scrapers.py` to refresh data,
or click "Refresh All Data Now" in the admin panel.

To schedule daily auto-refresh, add to crontab:
```
0 7 * * * cd /path/to/fantasy_life && python -c "from scrapers import refresh_all; refresh_all()"
```

---

## Deployment (Render.com)

1. Push to GitHub
2. New Web Service → connect repo
3. Build: `pip install -r requirements.txt`
4. Start: `gunicorn app:app`
5. Add env var `SECRET_KEY` for session security

---

## Open Issues / Known Disputes

- **Amendment 7.20**: Tennis women's major bonus TBD pending drink-off
- **Actor/Actress**: Film eligibility (2026 release) needs manual curation
- **ChatGPTodd**: Behind paywall gag — click "No thanks" to ignore
