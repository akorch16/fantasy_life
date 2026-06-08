# FL Category Fix

Diagnose and fix incorrect data showing in production for a specific scoring category.

## When to use

Run `/fl-category-fix <category>` when a category's values in `docs/scores.json` (or on the live site) don't match the expected authoritative source. Examples:
- `/fl-category-fix country` — GDP values are wrong
- `/fl-category-fix golf` — OWGR rankings are stale
- `/fl-category-fix nhl` — standings aren't updating

---

## Architecture: How Data Flows

```
Authoritative source
    ↓ (scrapers.py, daily Actions run)
Supabase (standings table)
    ↓ (scoring.py load_data())
compute_baseline_<category>()
    ↓
docs/scores.json   →   live site
```

**Exception — static categories that bypass Supabase:**
- `Country` — always reads `data/country.json` directly (IMF WEO data, updated April + October)
- `NFL`, `NCAAF` — frozen in Supabase; static season-end standings

**Bonuses** — `data/bonuses.json` overrides Supabase for any (category, player) pair present in the file. Managed manually via `/fl-bonus`.

---

## Step 1 — Confirm what production is showing

```bash
python3 -c "
import json
d = json.load(open('docs/scores.json'))
cat = '$CATEGORY'  # replace with the category
for p in d['players']:
    c = p.get('categories', {}).get(cat, {})
    print(f\"{p['name']:10} raw={c.get('raw_value')} rank={c.get('rank')} bonus={c.get('bonus_pts')} total={c.get('total_pts')}\")
"
```

---

## Step 2 — Identify the data source

Determine which source should be authoritative for this category:

| Category | Authoritative source | Method |
|---|---|---|
| Country | `data/country.json` (IMF WEO April 2026) | Static file, Supabase bypassed |
| Golf | `GOLF_2026_OWGR_STATIC` in scoring.py | Static dict; scrapers 403 |
| NFL, NCAAF | Hardcoded dicts in scoring.py | Frozen seasons |
| NBA, NHL, MLB, MLS | Live Supabase standings | Scraped daily |
| Tennis | Live Supabase standings | Scraped daily |
| NASCAR | Live Supabase standings | Scraped daily |
| Actor, Actress | Live Supabase via TMDB scraper | Scraped daily |
| Musician | Live Supabase via Billboard scraper | Scraped daily |
| Stock | Live Supabase via Yahoo Finance scraper | Scraped daily |

---

## Step 3 — Trace the mismatch

**If the category uses a static file (`data/country.json`, etc.):**
- Read the static file and compare to `docs/scores.json`
- If the file is correct but scores.json is wrong: `scoring.py` may still be reading from Supabase first. Check `compute_baseline_<category>()` — the static file should be the PRIMARY source, with Supabase as fallback only if the file is missing.
- Fix: move the static file read above the `load_data()` call.

**If the category reads from Supabase:**
- Check what Supabase has by looking at what `scoring.py` would compute:
  ```bash
  python3 -c "
  import sys; sys.path.insert(0, '.')
  import db; db.get_standing = lambda k: None; db.get_all_standings = lambda: {}
  db.get_all_bonuses = lambda: {}; db.get_last_updated = lambda k: None
  db.get_standing_updated_at = lambda k: None
  from scoring import load_data
  print(load_data('$CATEGORY'))
  "
  ```
  (Returns None when Supabase is unavailable — in production the real Supabase data shows.)
- If Supabase has bad data: the scraper wrote incorrect values. Options:
  1. Fix the scraper to parse correctly
  2. Make `compute_baseline_<category>()` use a static file as primary
  3. Add a `is_frozen()` gate to stop the scraper from overwriting

**If values look correct but rankings/points are wrong:**
- The `rank_avg()` function in `scoring.py` may be comparing wrong values, or a player's pick name doesn't match the data source spelling. Check the name-matching logic in `compute_baseline_<category>()`.

---

## Step 4 — Apply the fix

Common fixes:

**Make static file primary (prevents Supabase corruption):**
```python
def compute_baseline_country():
    picks = DRAFT_PICKS_2026.get('Country', {})
    import json as _json
    _path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'country.json')
    data = None
    try:
        with open(_path) as _f:
            data = _json.load(_f)
    except Exception:
        data = load_data('country')  # fallback only if file missing
```

**Freeze a scraper until a future date:**
```python
def scrape_<category>():
    if is_frozen('<Category>'):
        print('  ⏸ frozen, skipping'); return True
    import datetime
    if datetime.date.today() < datetime.date(YYYY, MM, DD):
        print('  ⏸ using static data until <date>'); return True
```

**Update a static data file** (`data/country.json`, etc.): verify values from the authoritative source first, update the file, commit.

---

## Step 5 — Verify locally

Run the smoke test:
```bash
python3 -c "
import sys; sys.path.insert(0, '.')
import db
db.get_standing = lambda k: None
db.get_all_standings = lambda: {}
db.get_all_bonuses = lambda: {}
db.get_last_updated = lambda k: None
db.get_standing_updated_at = lambda k: None
from scoring import compute_baseline_$CATEGORY
r = compute_baseline_$CATEGORY()
for player, d in sorted(r.items(), key=lambda x: x[1]['rank'] or 99):
    print(f\"{player:10} {d.get('pick',''):20} raw={d.get('raw_value')} rank={d.get('rank')} pts={d.get('baseline_pts')}\")
"
```

All 13 players should appear with non-null values if data is correct.

---

## Step 6 — Deploy

Use `/fl-merge` to push and merge to production.
