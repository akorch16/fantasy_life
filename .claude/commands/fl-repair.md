# FL Repair

Diagnose and fix a broken Fantasy Life daily GitHub Actions run.

## When to use

Run `/fl-repair` when the daily Actions workflow fails. Paste the error logs if you have them, or run without arguments to pull the latest logs directly.

---

## Architecture Overview

The daily workflow runs two Python scripts:
1. `scrapers.py` — fetches live data from APIs and writes to Supabase
2. `scoring.py` — reads from Supabase, computes scores, writes `docs/scores.json`

Workflow file: `.github/workflows/daily.yml`

Key files:
- `scrapers.py` — one `scrape_*()` function per category
- `scoring.py` — `compute_all_scores()` + `__main__` block writes scores.json
- `db.py` — all Supabase read/write; `is_frozen()`, `get_standing()`, `save_standing()`
- `data/bonuses.json` — static bonus overrides (JSON only, no Supabase)
- `data/country.json` — static IMF WEO GDP data (bypasses Supabase entirely)

---

## Step 1 — Get the failure

If the user pasted logs, skip this step. Otherwise:

```bash
# Check recent git log for obvious issues
git log origin/main --oneline -10

# Look for syntax errors in the two main scripts
python3 -m py_compile scoring.py && echo "scoring ok" || echo "SYNTAX ERROR in scoring.py"
python3 -m py_compile scrapers.py && echo "scrapers ok" || echo "SYNTAX ERROR in scrapers.py"

# Check for leftover conflict markers
grep -n "<<<<<<\|=======\|>>>>>>>" scoring.py scrapers.py db.py docs/index.html 2>/dev/null
```

---

## Step 2 — Diagnose by error type

### SyntaxError / invalid syntax
Most likely cause: git merge conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) were accidentally committed.

Fix: Remove conflict markers, keeping the correct version. The correct version is almost always the feature branch change (HEAD), NOT the stashed/upstream version. Verify with `python3 -m py_compile` after fixing.

### `403 Forbidden` from a scraper
The scraper's API is blocking server-side requests. This is expected for some sources (ESPN golf, OWGR, IMF DataMapper). The scraper should fall back gracefully or be frozen.

Check which scraper is failing and whether `is_frozen()` is set in Supabase for that category. If the API is permanently blocked, add a date-gate or freeze to skip that scraper.

Known fragile scrapers:
- `scrape_golf()` — ESPN/OWGR both 403; falls back to `GOLF_2026_OWGR_STATIC`
- `scrape_country_gdp()` — IMF DataMapper 403; date-gated until Oct 1 2026, reads static file

### `KeyError` / `NoneType` in scoring.py
A category returned `None` from `load_data()` and the downstream code didn't handle it. Check which category and add a guard, or verify the Supabase row exists.

### `ModuleNotFoundError`
A new import was added but isn't installed. Check `requirements.txt` and add the missing package.

### Scores written but wrong values
The scraper wrote bad data to Supabase (stale, wrong source, wrong field name). Fix: freeze the category or make the scoring function use the static file as primary source (like `compute_baseline_country()` does).

### Workflow environment issue
Missing secret (e.g., `SUPABASE_URL`, `ANTHROPIC_API_KEY`). Check `.github/workflows/daily.yml` env block and compare against required env vars in `db.py` and `scoring.py`.

---

## Step 3 — Apply the fix

Make the minimal targeted fix:
- For conflict markers: remove them cleanly, verify syntax
- For frozen/bad scraper: add `is_frozen()` check or date-gate
- For scoring logic: fix the guard condition
- For static data: ensure the static file is the primary source

Always run:
```bash
python3 -m py_compile scoring.py scrapers.py
grep -c "<<<<<<" scoring.py scrapers.py db.py
```
before committing.

---

## Step 4 — Deploy

Use `/fl-merge` to push and merge the fix to production.

After merging, confirm the fix by checking that the workflow would pass:
```bash
python3 -c "
import json, sys
sys.path.insert(0, '.')
# Quick structural check only (no live Supabase needed)
import db
db.get_standing = lambda k: None
db.get_all_standings = lambda: {}
db.get_all_bonuses = lambda: {}
db.get_last_updated = lambda k: None
db.get_standing_updated_at = lambda k: None
from scoring import compute_baseline_country
r = compute_baseline_country()
print('Country OK:', {p: d['raw_value'] for p, d in r.items() if d['raw_value']})
"
```
