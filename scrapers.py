"""
Fantasy Life 2026 — Data Scrapers
Sources:
  NBA/NHL/MLB/NCAAB/MLS → ESPN API (no key needed)
  Tennis       → ATP/WTA scrape
  Golf         → OWGR scrape
  Stock        → Yahoo Finance
  Country      → IMF DataMapper API
  Musician     → Billboard scrape (fragile, fallback to manual)
  NFL/NCAAF    → FROZEN in Supabase, scrapers skip these
"""

import json, os, re
from datetime import datetime

try:
    import requests
    from bs4 import BeautifulSoup
    SCRAPING_AVAILABLE = True
except ImportError:
    SCRAPING_AVAILABLE = False

from db import save_standing, is_frozen, get_standing

ESPN_BASE = 'https://site.api.espn.com/apis/site/v2/sports'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Accept': 'application/json',
}

def fetch_json(url, headers=None, params=None, timeout=15):
    h = {**HEADERS, **(headers or {})}
    r = requests.get(url, headers=h, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def fetch_html(url, timeout=15):
    h = {**HEADERS, 'Accept': 'text/html,application/xhtml+xml'}
    r = requests.get(url, headers=h, timeout=timeout)
    r.raise_for_status()
    return BeautifulSoup(r.text, 'html.parser')

# ── ESPN helpers ──────────────────────────────────────────────────────────────

def _espn_standings(sport, league):
    # Try multiple ESPN URL patterns
    urls = [
        f'https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/standings',
        f'https://site.web.api.espn.com/apis/v2/sports/{sport}/{league}/standings',
        f'https://site.web.api.espn.com/apis/v2/sports/{sport}/{league}/standings?seasontype=2&type=0&level=3',
    ]
    
    for url in urls:
        try:
            data = fetch_json(url, timeout=15)
            print(f'    ESPN {league} keys: {list(data.keys())}')
            entries = []
            for conf in data.get('children', []):
                children = conf.get('children', [conf])
                for div in children:
                    for entry in div.get('standings', {}).get('entries', []):
                        entries.append(entry)
                for entry in conf.get('standings', {}).get('entries', []):
                    if entry not in entries:
                        entries.append(entry)
            if not entries:
                for entry in data.get('standings', {}).get('entries', []):
                    entries.append(entry)
            if entries:
                print(f'    ✓ Got {len(entries)} entries from {url}')
                return entries
            print(f'    ✗ No entries from {url}')
        except Exception as e:
            print(f'    ✗ {url}: {e}')
    
    return []


def _espn_stat(entry, name):
    for s in entry.get('stats', []):
        if s.get('name') == name or s.get('abbreviation') == name:
            return s.get('value')
    return None

# ── NBA ───────────────────────────────────────────────────────────────────────

def scrape_nba():
    if is_frozen('NBA'):
        print('  ⏸ NBA is frozen, skipping'); return True
    try:
        entries = _espn_standings('basketball', 'nba')
        if not entries: raise Exception('No data')
        standings = []
        for e in entries:
            name = e.get('team', {}).get('displayName', '')
            wins = _espn_stat(e, 'wins') or 0
            losses = _espn_stat(e, 'losses') or 0
            gp = wins + losses
            standings.append({'team': name, 'win_pct': round(wins / gp, 4) if gp else 0})
        standings.sort(key=lambda x: x['win_pct'], reverse=True)
        return save_standing('NBA', {'standings': standings})
    except Exception as e:
        print(f'  ✗ NBA: {e}'); return False

# ── NHL ───────────────────────────────────────────────────────────────────────

def scrape_nhl():
    if is_frozen('NHL'):
        print('  ⏸ NHL is frozen, skipping'); return True
    try:
        entries = _espn_standings('hockey', 'nhl')
        if not entries: raise Exception('No data')
        standings = []
        for e in entries:
            name = e.get('team', {}).get('displayName', '')
            pts = _espn_stat(e, 'points') or 0
            gp  = _espn_stat(e, 'gamesPlayed') or 1
            standings.append({'team': name, 'points_pct': round(pts / (gp * 2), 4)})
        standings.sort(key=lambda x: x['points_pct'], reverse=True)
        return save_standing('NHL', {'standings': standings})
    except Exception as e:
        print(f'  ✗ NHL: {e}'); return False

# ── MLB ───────────────────────────────────────────────────────────────────────

def scrape_mlb():
    if is_frozen('MLB'):
        print('  ⏸ MLB is frozen, skipping'); return True
    try:
        entries = _espn_standings('baseball', 'mlb')
        if not entries: raise Exception('No data')
        standings = []
        for e in entries:
            name = e.get('team', {}).get('displayName', '')
            wins = _espn_stat(e, 'wins') or 0
            losses = _espn_stat(e, 'losses') or 0
            gp = wins + losses
            standings.append({'team': name, 'win_pct': round(wins / gp, 4) if gp else 0})
        standings.sort(key=lambda x: x['win_pct'], reverse=True)
        return save_standing('MLB', {'standings': standings})
    except Exception as e:
        print(f'  ✗ MLB: {e}'); return False

# ── NFL (frozen) ──────────────────────────────────────────────────────────────

def scrape_nfl():
    if is_frozen('NFL'):
        print('  ⏸ NFL is frozen, skipping'); return True
    print('  ℹ NFL: enter final standings in admin panel, then freeze')
    return False

# ── NCAAF (frozen) ────────────────────────────────────────────────────────────

def scrape_ncaaf():
    if is_frozen('NCAAF'):
        print('  ⏸ NCAAF is frozen, skipping'); return True
    print('  ℹ NCAAF: enter final standings in admin panel, then freeze')
    return False

# ── NCAAB ─────────────────────────────────────────────────────────────────────

def scrape_ncaab():
    if is_frozen('NCAAB'):
        print('  ⏸ NCAAB is frozen, skipping'); return True
    try:
        url = f'{ESPN_BASE}/basketball/mens-college-basketball/standings'
        data = fetch_json(url, timeout=15)
        entries = []
        for conf in data.get('children', []):
            for div in conf.get('children', [conf]):
                for entry in div.get('standings', {}).get('entries', []):
                    entries.append(entry)
        if not entries: raise Exception('No data')
        ranked = []
        for e in entries:
            name = e.get('team', {}).get('displayName', '')
            wins = _espn_stat(e, 'wins') or 0
            losses = _espn_stat(e, 'losses') or 0
            gp = wins + losses
            pct = wins / gp if gp else 0
            ranked.append({'team': name, 'pct': pct})
        ranked.sort(key=lambda x: x['pct'], reverse=True)
        poll = [{'rank': i+1, 'team': r['team']} for i, r in enumerate(ranked[:25])]
        return save_standing('NCAAB', {'poll': poll})
    except Exception as e:
        print(f'  ✗ NCAAB: {e}'); return False

# ── MLS ───────────────────────────────────────────────────────────────────────

def scrape_mls():
    if is_frozen('MLS'):
        print('  ⏸ MLS is frozen, skipping'); return True
    try:
        entries = _espn_standings('soccer', 'usa.mls')
        if not entries: raise Exception('No MLS data')
        standings = []
        for e in entries:
            name = e.get('team', {}).get('displayName', '')
            pts = _espn_stat(e, 'points') or _espn_stat(e, 'pts') or 0
            standings.append({'team': name, 'points': pts})
        standings.sort(key=lambda x: x['points'], reverse=True)
        return save_standing('MLS', {'standings': standings})
    except Exception as e:
        print(f'  ✗ MLS: {e}'); return False

# ── NASCAR (manual) ───────────────────────────────────────────────────────────

def scrape_nascar():
    if is_frozen('NASCAR'):
        print('  ⏸ NASCAR is frozen, skipping'); return True
    print('  ℹ NASCAR: update manually in admin panel')
    return False

# ── Tennis ────────────────────────────────────────────────────────────────────

def scrape_tennis():
    if is_frozen('Tennis'):
        print('  ⏸ Tennis is frozen, skipping'); return True
    try:
        rankings = []
        soup = fetch_html('https://www.atptour.com/en/rankings/singles')
        for row in soup.select('table tbody tr')[:50]:
            cols = row.find_all('td')
            if len(cols) >= 4:
                try:
                    rank = int(cols[0].text.strip().replace('T', ''))
                    # col[1] = move, col[2] = country, col[3] = player name
                    player = cols[3].text.strip()
                    if not player:
                        player = cols[2].text.strip()
                    if player: rankings.append({'player': player, 'rank': rank, 'tour': 'ATP'})
                except (ValueError, AttributeError): continue
        soup2 = fetch_html('https://www.wtatennis.com/rankings/singles')
        for row in soup2.select('table tbody tr')[:50]:
            cols = row.find_all('td')
            if len(cols) >= 2:
                try:
                    rank = int(cols[0].text.strip())
                    player = cols[1].text.strip()
                    if player: rankings.append({'player': player, 'rank': rank, 'tour': 'WTA'})
                except (ValueError, AttributeError): continue
        if rankings: return save_standing('Tennis', {'rankings': rankings})
        raise Exception('No rankings found')
    except Exception as e:
        print(f'  ✗ Tennis: {e}'); return False

# ── Golf ──────────────────────────────────────────────────────────────────────

def scrape_golf():
    if is_frozen('Golf'):
        print('  ⏸ Golf is frozen, skipping'); return True
    try:
        soup = fetch_html('https://www.owgr.com/ranking')
        rankings = []
        for row in soup.select('table tr')[1:60]:
            cols = row.find_all('td')
            if len(cols) >= 3:
                try:
                    rank = int(cols[0].text.strip())
                    player = cols[2].text.strip() or cols[1].text.strip()
                    if player: rankings.append({'player': player, 'rank': rank})
                except (ValueError, AttributeError): continue
        if rankings: return save_standing('Golf', {'rankings': rankings})
        raise Exception('No rankings found')
    except Exception as e:
        print(f'  ✗ Golf: {e}'); return False

# ── Stock ─────────────────────────────────────────────────────────────────────

def scrape_stock():
    if is_frozen('Stock'):
        print('  ⏸ Stock is frozen, skipping'); return True
    try:
        from draft_picks_2026 import DRAFT_PICKS_2026
        tickers = list(set(info['ticker'] for info in DRAFT_PICKS_2026['Stock'].values()))
        prices = []
        for ticker in tickers:
            try:
                url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=ytd'
                r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}, timeout=10)
                data = r.json()['chart']['result'][0]
                meta = data['meta']
                current = meta.get('regularMarketPrice') or meta.get('previousClose')
                closes = data['indicators']['quote'][0].get('close', [])
                jan1 = next((c for c in closes if c is not None), None)
                if current and jan1:
                    prices.append({'ticker': ticker, 'current_price': current, 'jan1_price': jan1,
                                   'ytd_pct_raw': round((current / jan1 - 1) * 100, 2)})
                    print(f'    {ticker}: ${jan1:.2f} → ${current:.2f}')
            except Exception as e:
                print(f'    ✗ {ticker}: {e}')
        if prices: return save_standing('Stock', {'prices': prices})
        return False
    except Exception as e:
        print(f'  ✗ Stock: {e}'); return False

# ── Country GDP ───────────────────────────────────────────────────────────────

def scrape_country_gdp():
    if is_frozen('Country'):
        print('  ⏸ Country is frozen, skipping'); return True
    try:
        data = fetch_json('https://www.imf.org/external/datamapper/api/v1/NGDP_RPCH')
        ISO_MAP = {
            'Netherlands': 'NLD', 'United States': 'USA', 'Germany': 'DEU',
            'Guinea': 'GIN', 'South Sudan': 'SSD', 'France': 'FRA',
            'Switzerland': 'CHE', 'Brazil': 'BRA', 'Norway': 'NOR',
            'Guyana': 'GUY', 'Argentina': 'ARG', 'Spain': 'ESP', 'Canada': 'CAN',
        }
        from draft_picks_2026 import DRAFT_PICKS_2026
        countries = list(DRAFT_PICKS_2026['Country'].values())
        values = data.get('values', {}).get('NGDP_RPCH', {})
        gdp = []
        for country in countries:
            code = ISO_MAP.get(country)
            if code and code in values:
                growth = values[code].get('2026') or values[code].get('2025')
                if growth: gdp.append({'country': country, 'gdp_growth_pct': float(growth)})
        if gdp: return save_standing('Country', {'gdp': gdp})
        raise Exception('No GDP data found')
    except Exception as e:
        print(f'  ✗ Country: {e}'); return False

# ── Musician (Billboard) ──────────────────────────────────────────────────────

def scrape_billboard():
    if is_frozen('Musician'):
        print('  ⏸ Musician is frozen, skipping'); return True
    try:
        existing = get_standing('Musician')
        scores_map = {e['artist']: e for e in existing.get('scores', [])}
        soup = fetch_html('https://www.billboard.com/charts/hot-100/')
        entries_found = 0
        for item in soup.select('li.o-chart-results-list__item'):
            rank_el   = item.select_one('span.c-label')
            artist_el = item.select_one('span.c-label.a-font-primary-s')
            if rank_el and artist_el:
                try:
                    rank = int(rank_el.text.strip())
                    artist = artist_el.text.strip()
                    if artist not in scores_map:
                        scores_map[artist] = {'artist': artist, 'num1_weeks': 0, 'hot100_weeks': 0}
                    scores_map[artist]['hot100_weeks'] += 1
                    if rank == 1: scores_map[artist]['num1_weeks'] += 1
                    entries_found += 1
                except ValueError: continue
        if entries_found > 0:
            return save_standing('Musician', {'scores': list(scores_map.values())})
        raise Exception('No chart entries found')
    except Exception as e:
        print(f'  ✗ Musician/Billboard: {e}'); return False

# ── Refresh All ───────────────────────────────────────────────────────────────

def refresh_all():
    import traceback
    print('\n🔄 Fantasy Life 2026 — Refreshing all data...\n')

    import os
    surl = os.environ.get('SUPABASE_URL', 'NOT SET')
    skey = os.environ.get('SUPABASE_KEY', 'NOT SET')
    print(f'  ENV: SUPABASE_URL={surl[:30] if surl != "NOT SET" else "NOT SET"}')
    print(f'  ENV: SUPABASE_KEY={"SET (" + str(len(skey)) + " chars)" if skey != "NOT SET" else "NOT SET"}')

    results = {}
    all_scrapers = [
        ('NFL', scrape_nfl), ('NCAAF', scrape_ncaaf),
        ('NBA', scrape_nba), ('NHL', scrape_nhl), ('MLB', scrape_mlb),
        ('NCAAB', scrape_ncaab), ('Tennis', scrape_tennis), ('Golf', scrape_golf),
        ('NASCAR', scrape_nascar), ('MLS', scrape_mls), ('Stock', scrape_stock),
        ('Country', scrape_country_gdp), ('Musician', scrape_billboard),
    ]
    for name, fn in all_scrapers:
        print(f'Scraping {name}...')
        try:
            result = fn()
            status = 'ok' if result else 'failed'
        except Exception as e:
            status = f'error: {e}'
            print(f'  TRACEBACK:\n{traceback.format_exc()}')
        results[name] = status
        print(f'  → {name}: {status}')
    print('\n✅ Refresh complete!')
    return results

# ── Demo seed ─────────────────────────────────────────────────────────────────

def seed_demo_data():
    """Seed Supabase with starter data. Run once on empty DB."""
    print('Seeding demo data to Supabase...')
    save_standing('NBA',     {'standings': []})
    save_standing('NHL',     {'standings': []})
    save_standing('NFL',     {'standings': []}, frozen=True)
    save_standing('NCAAF',   {'poll': []},      frozen=True)
    save_standing('MLB',     {'standings': []})
    save_standing('NCAAB',   {'poll': []})
    save_standing('Tennis',  {'rankings': []})
    save_standing('Golf',    {'rankings': []})
    save_standing('Stock',   {'prices': []})
    save_standing('Country', {'gdp': []})
    save_standing('Musician',{'scores': []})
    save_standing('MLS',     {'standings': []})
    save_standing('NASCAR',  {'standings': []})
    print('✅ Demo seed complete!')

if __name__ == '__main__':
    seed_demo_data()
