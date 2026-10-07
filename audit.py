#!/usr/bin/env python3
"""
Fantasy Life — deterministic audit (the scripted half of /fl-audit).

Reads the committed outputs (docs/scores.json, docs/projections.json) and the
hand-edited data files, and flags the classes of problem that cost us the most
debugging time: unmatched picks, stale/unfrozen categories about to roll over,
bonus bookkeeping errors, actor/actress roster gaps, projection-model drift and
rotted docs. It needs no network; Supabase is only consulted (if credentials
exist) to see which categories are frozen.

    python3 audit.py                  # markdown report to stdout
    python3 audit.py --out report.md  # also write it to a file
    python3 audit.py --today 2026-10-20

Exit code 1 if any ERROR finding, else 0. The judgment half (does the bonus
match what actually happened? is the roster complete?) is the /fl-audit
runbook in .claude/commands/fl-audit.md.
"""
import json
import os
import re
import sys
from datetime import date, datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

PLAYERS = ['Tim', 'Wu', 'Jens', 'Todd', 'Mitchell', 'Shep', 'Theo', 'Feder',
           'Fryar', 'Korch', 'Molmen', 'Jamzee', 'Buckley']
CATEGORIES = ['nfl', 'nba', 'mlb', 'nhl', 'ncaaf', 'ncaab', 'tennis', 'golf',
              'nascar', 'mls', 'actor', 'actress', 'musician', 'country', 'stock']
BONUS_CAP = 13.0                      # Amendment 7.14

# Categories where "raw_value is None" is a legitimate "scored zero" rather than
# an unmatched pick, and where big ties are normal.
ZERO_OK = {'actor', 'actress', 'musician', 'country', 'ncaab'}   # ncaab = AP Top 25 poll, unranked is legit
# Live-scraped categories (their Supabase row should refresh daily unless frozen).
LIVE = ['nba', 'mlb', 'nhl', 'ncaab', 'tennis', 'golf', 'nascar', 'mls', 'stock', 'musician']

# Next season's opening day per category. A category that is NOT frozen when its
# next season tips off gets its final standings overwritten by a 0-0 table (NHL,
# NCAAB and NASCAR all got burned this way). Update this table every audit.
NEXT_SEASON_START = {
    'nba':   date(2026, 10, 20),
    'nhl':   date(2026, 9, 29),
    'ncaab': date(2026, 11, 3),
    'mlb':   date(2027, 3, 25),
    'mls':   date(2027, 2, 20),
    'nascar': date(2027, 2, 14),
}
ROLLOVER_WARN_DAYS = 21
# db.is_frozen() keys
DB_NAMES = {'nfl': 'NFL', 'nba': 'NBA', 'mlb': 'MLB', 'nhl': 'NHL', 'ncaaf': 'NCAAF', 'ncaab': 'NCAAB',
            'tennis': 'Tennis', 'golf': 'Golf', 'nascar': 'NASCAR', 'mls': 'MLS', 'musician': 'Musician',
            'stock': 'Stock'}

findings = []   # (severity, area, message)


def add(sev, area, msg):
    findings.append((sev, area, msg))


def load(rel, default=None):
    try:
        with open(os.path.join(ROOT, rel)) as f:
            return json.load(f)
    except Exception as e:
        add('ERROR', 'files', f'could not read {rel}: {e}')
        return default


def norm_title(t):
    return re.sub(r'[^a-z0-9]', '', (t or '').lower().replace('&', 'and'))


# ── 1. scores.json integrity ─────────────────────────────────────────────────
def check_scores(scores):
    players = {p['name']: p for p in scores.get('players', [])}
    for name in PLAYERS:
        if name not in players:
            add('ERROR', 'scores', f'player {name} missing from scores.json')
    for name, p in players.items():
        cats = p.get('categories', {})
        missing = [c for c in CATEGORIES if c not in cats]
        if missing:
            add('ERROR', 'scores', f'{name}: categories missing {missing}')
        total = sum((cats.get(c) or {}).get('total_pts') or 0 for c in CATEGORIES)
        if abs(total - (p.get('total') or 0)) > 0.01:
            add('ERROR', 'scores', f'{name}: total {p.get("total")} != sum of category totals {total}')
        for c in CATEGORIES:
            v = cats.get(c) or {}
            if (v.get('bonus_pts') or 0) > BONUS_CAP + 1e-9:
                add('ERROR', 'bonus', f'{name}/{c}: bonus {v["bonus_pts"]} exceeds the {BONUS_CAP:g} cap')

    for c in CATEGORIES:
        rows = [(n, (p['categories'].get(c) or {})) for n, p in players.items()]
        # unmatched picks: no raw value in a category that should have one
        if c not in ZERO_OK:
            for n, v in rows:
                if v.get('raw_value') is None:
                    add('ERROR', 'match', f'{c}: {n}\'s pick "{v.get("pick")}" has no data '
                        f'(unmatched name? — it is silently ranked last). Check team_matches/name_matches '
                        f'against the source\'s spelling (LA vs Los Angeles, accents, FC/SC suffixes).')
        # suspicious big ties
        if c not in ZERO_OK:
            by_rank = {}
            for n, v in rows:
                by_rank.setdefault(v.get('rank'), []).append(n)
            for rk, ns in by_rank.items():
                if len(ns) >= 4:
                    add('WARN', 'ties', f'{c}: {len(ns)}-way tie at rank {rk} ({", ".join(ns)}) — '
                        f'often a wiped/0-0 or placeholder standings table')


# ── 2. freshness + season rollover ───────────────────────────────────────────
def frozen_categories():
    """Return {cat: bool}, or {} if Supabase isn't reachable."""
    if not (os.environ.get('SUPABASE_URL') and os.environ.get('SUPABASE_KEY')):
        return {}
    try:
        import db
        return {c: bool(db.is_frozen(DB_NAMES[c])) for c in DB_NAMES}
    except Exception as e:
        add('WARN', 'freshness', f'could not read frozen flags from Supabase: {e}')
        return {}


def check_freshness(scores, today, frozen):
    fresh = scores.get('data_freshness') or {}
    if not frozen:
        add('INFO', 'freshness', 'frozen flags unavailable (no Supabase credentials) — stale categories '
            'cannot be told apart from intentionally frozen ones')
    for c in LIVE:
        f = fresh.get(c)
        if not f:
            continue
        is_frozen = frozen.get(c)
        if f.get('stale') and not is_frozen:
            if frozen:
                add('ERROR', 'freshness', f'{c}: last refreshed {f.get("age_days")} days ago and not frozen — the '
                    f'scraper is failing (check the DEGRADED line in the daily.yml log)')
            else:
                add('INFO', 'freshness', f'{c}: last refreshed {f.get("age_days")} days ago (frozen? unknown)')
        if f.get('source') not in ('live', None) and c not in ('golf', 'mls'):
            add('INFO', 'freshness', f'{c}: serving from "{f.get("source")}" instead of live')
    for c, opener in NEXT_SEASON_START.items():
        if frozen.get(c):
            continue
        days = (opener - today).days
        if -7 <= days <= ROLLOVER_WARN_DAYS:
            when = f'in {days} days' if days >= 0 else f'{-days} days ago'
            state = 'NOT frozen' if frozen else 'of unknown frozen state (no Supabase credentials)'
            add('WARN', 'rollover', f'{c}: next season opens {opener} ({when}) and the category is {state} — '
                f'freeze the final standings first (db.py repair_*_freeze via dump-sb.yml) or the new 0-0 '
                f'table overwrites them')


# ── 3. bonuses.json bookkeeping ──────────────────────────────────────────────
def check_bonuses(scores, bonuses):
    valid_cats = {c.lower() for c in CATEGORIES} | {'country_worldcup'}
    players = {p['name']: p for p in scores.get('players', [])}
    for cat, entries in (bonuses or {}).items():
        if cat.startswith('_'):
            continue
        if cat.lower() not in valid_cats:
            add('ERROR', 'bonus', f'bonuses.json: unknown category "{cat}"')
            continue
        for player, val in entries.items():
            if player not in PLAYERS:
                add('ERROR', 'bonus', f'bonuses.json: {cat}: unknown player "{player}"')
                continue
            if cat.lower() == 'country_worldcup':
                continue
            applied = ((players.get(player) or {}).get('categories', {}).get(cat.lower()) or {}).get('bonus_pts')
            if applied is not None:
                expect = min(BONUS_CAP, val + (bonuses.get('Country_WorldCup', {}).get(player, 0)
                                               if cat.lower() == 'country' else 0))
                if abs(applied - expect) > 0.01:
                    add('ERROR', 'bonus', f'{cat}/{player}: bonuses.json says {val} (expected {expect}) '
                        f'but scores.json shows {applied}')
    # Omitting an entry falls back to the stale Supabase value instead of zeroing it.
    add('INFO', 'bonus', 'reminder: a (category, player) pair missing from bonuses.json falls back to the '
        'Supabase value — to zero a bonus write an explicit 0.0')


# ── 4. actor / actress roster ────────────────────────────────────────────────
def check_films(scores, today):
    try:
        import projections
        pipeline = projections.FILM_PIPELINE
    except Exception as e:
        add('WARN', 'films', f'could not import projections.FILM_PIPELINE: {e}')
        return
    from draft_picks_2026 import DRAFT_PICKS_2026 as PICKS
    players = {p['name']: p for p in scores.get('players', [])}
    for cat, fname in (('actor', 'data/actor.json'), ('actress', 'data/actress.json')):
        roster = load(fname, {'scores': []})
        owners = {v: k for k, v in PICKS[cat.capitalize()].items()}
        roster_titles = {}    # norm title -> players holding it in the roster file
        for entry in roster.get('scores', []):
            for m in entry.get('movies', []) or []:
                roster_titles.setdefault(norm_title(m.get('title')), set()).add(owners.get(entry.get('name')))
        # resolved (live-merged) movies as scoring.py sees them
        resolved = {}         # norm title -> list of (player, movie)
        for name, p in players.items():
            for m in (p.get('categories', {}).get(cat) or {}).get('movies', []) or []:
                resolved.setdefault(norm_title(m.get('title')), []).append((name, m))
                rel, streaming = m.get('release_date'), m.get('streaming')
                if streaming and m.get('box_office'):
                    add('WARN', 'films', f'{cat}: "{m["title"]}" is flagged streaming but has a box office')
                if not streaming and rel and rel <= today.isoformat() and not m.get('box_office'):
                    add('WARN', 'films', f'{cat}: {name}\'s "{m["title"]}" released {rel} but has no box office '
                        f'(not matching Box Office Mojo? use the official title)')
                if not streaming and m.get('box_office') and m.get('rt_score') is None:
                    add('INFO', 'films', f'{cat}: {name}\'s "{m["title"]}" has a box office but no RT score yet '
                        f'(contributes nothing until OMDb has one — set rt_score by hand if it is out)')
                if not rel and not streaming:
                    add('INFO', 'films', f'{cat}: {name}\'s "{m["title"]}" has no release date (inert until added)')
        for film in pipeline:
            t = norm_title(film['title'])
            wanted = set(film.get(cat) or [])
            missing = wanted - roster_titles.get(t, set())
            if wanted and missing:
                add('WARN', 'films', f'{cat}: FILM_PIPELINE counts "{film["title"]}" for {sorted(missing)} but '
                    f'the roster file does not list it for them')
            if any(m.get('box_office') and not m.get('streaming') for _, m in resolved.get(t, [])):
                add('ERROR', 'films', f'FILM_PIPELINE still simulates "{film["title"]}", which already has a real '
                    f'box office — it is double-counted in the Monte Carlo. Remove it from FILM_PIPELINE.')


# ── 5. projections drift ─────────────────────────────────────────────────────
def check_projections(proj, scores, today):
    try:
        gen = datetime.fromisoformat(proj['generated_at'].replace('Z', '+00:00'))
        age_h = (datetime.now(timezone.utc) - gen).total_seconds() / 3600
        if age_h > 36:
            add('ERROR', 'projections', f'projections.json is {age_h:.0f}h old')
    except Exception:
        add('WARN', 'projections', 'projections.json has no parseable generated_at')
    if not proj.get('kalshi_markets_used'):
        add('ERROR', 'projections', 'no Kalshi markets used — projections fell back to static odds '
            '(bad KALSHI_PRIVATE_KEY or dead tickers)')
    total = sum(p.get('win_pct') or 0 for p in proj.get('players', []))
    if abs(total - 100) > 1.0:
        add('ERROR', 'projections', f'win_pct sums to {total:.2f}, not ~100')
    n = proj.get('n_simulations') or 0
    if n < 50000:
        add('INFO', 'projections', f'{n:,} sims: win odds under ~0.1% are sampling noise (±2x run to run); '
            'do not quote the +100,000 tail as signal')
    # Bookkeeping invariants of simulate(): re-ranking is zero-sum and bonuses only add, so the
    # league-wide drift (projected_total - current_total) can never be negative, and every row must
    # satisfy projected_total == current_total + projected_additional. A negative drift means the
    # simulation is dropping already-earned points (it once stripped earned NBA/NHL/golf/tennis
    # bonuses: -49 points league-wide).
    rows = [p for p in proj.get('players', [])
            if None not in (p.get('current_total'), p.get('projected_additional'), p.get('projected_total'))]
    drift = sum(p['projected_total'] - p['current_total'] for p in rows)
    if rows and drift < -1.0:
        add('ERROR', 'projections', f'simulation drift is {drift:+.1f} points league-wide (must be >= 0) — it is '
            f'dropping earned bonus points or double-removing a category baseline')
    for p in rows:
        gap = p['projected_total'] - p['current_total'] - p['projected_additional']
        if abs(gap) > 0.15:
            add('ERROR', 'projections', f'{p["name"]}: projected_total {p["projected_total"]} != current '
                f'{p["current_total"]} + expected {p["projected_additional"]} (off by {gap:+.1f})')
    fb = proj.get('fallback_as_of')
    if fb:
        try:
            age = (today - date.fromisoformat(fb)).days
            if age > 60:
                add('INFO', 'projections', f'static FALLBACK odds last refreshed {fb} ({age} days ago)')
        except ValueError:
            pass


# ── 6. rotted docs (calendar) ────────────────────────────────────────────────
MONTHS = {m: i + 1 for i, m in enumerate(
    ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'])}


def check_calendar(today):
    try:
        html = open(os.path.join(ROOT, 'docs/calendar.html')).read()
    except Exception as e:
        add('WARN', 'docs', f'could not read docs/calendar.html: {e}')
        return
    cards = re.findall(r'event-card status-(\w+)".*?<div class="event-name">(.*?)</div>.*?'
                       r'<div class="event-date">(.*?)</div>', html, re.S)
    for status, name, dt in cards:
        toks = re.findall(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})'
                          r'(?:\s*[–-]\s*(\d{1,2})(?!\d))?', dt)
        if not toks:
            continue
        mon, d1, d2 = toks[-1]
        try:
            end = date(today.year, MONTHS[mon], int(d2 or d1))
        except ValueError:
            continue
        clean = re.sub(r'<.*?>', '', name)
        if status in ('upcoming', 'live') and end < today:
            add('WARN', 'docs', f'calendar: "{clean}" ({dt}) is still marked {status} but ended {end}')
        if status == 'past' and end > today:
            add('WARN', 'docs', f'calendar: "{clean}" ({dt}) is marked completed but is on {end}')
    if re.search(r'<div class="event-date">[^<]*TBD', html):
        add('INFO', 'docs', 'calendar still has "(TBD)" dates — firm them up when announced')


def render(today):
    order = {'ERROR': 0, 'WARN': 1, 'INFO': 2}
    fs = sorted(findings, key=lambda f: (order[f[0]], f[1]))
    counts = {s: sum(1 for f in fs if f[0] == s) for s in order}
    lines = [f'# Fantasy Life audit — {today}', '',
             f'**{counts["ERROR"]} errors · {counts["WARN"]} warnings · {counts["INFO"]} notes**', '']
    if not fs:
        lines.append('No findings.')
    for sev in ('ERROR', 'WARN', 'INFO'):
        group = [f for f in fs if f[0] == sev]
        if group:
            lines += [f'## {sev}', ''] + [f'- **{a}** — {m}' for _, a, m in group] + ['']
    lines += ['---', 'Deterministic checks only. Run `/fl-audit` for the judgment pass (bonuses vs real '
              'results, roster completeness, source cross-checks).']
    return '\n'.join(lines), counts


def main(argv):
    today = date.today()
    if '--today' in argv:
        today = date.fromisoformat(argv[argv.index('--today') + 1])
    scores = load('docs/scores.json', {})
    proj = load('docs/projections.json', {})
    bonuses = load('data/bonuses.json', {})
    frozen = frozen_categories()
    check_scores(scores)
    check_freshness(scores, today, frozen)
    check_bonuses(scores, bonuses)
    check_films(scores, today)
    check_projections(proj, scores, today)
    check_calendar(today)
    report, counts = render(today)
    print(report)
    if '--out' in argv:
        with open(argv[argv.index('--out') + 1], 'w') as f:
            f.write(report + '\n')
    return 1 if counts['ERROR'] else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
