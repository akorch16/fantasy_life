"""
Fantasy Life 2026 — Data Scrapers
Sources:
  NBA/NHL/MLB  → balldontlie.io (free tier, needs BALLDONTLIE_KEY env var)
  MLS          → api-football.com (free tier, needs API_FOOTBALL_KEY env var)
  Tennis       → ATP/WTA scrape (working)
  Golf         → OWGR scrape (working)
  Stock        → Yahoo Finance (working)
  Country      → IMF DataMapper API (working)
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

BDL_KEY          = os.environ.get('BALLDONTLIE_KEY', '')
API_FOOTBALL_KEY = os.environ.get('API_FOOTBALL_KEY', '')
BDL_BASE         = 'https://api.balldontlie.io'

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

def _bdl_headers():
    return {'Authorization': BDL_KEY}

def _bdl_standings(league, season):
    url = f'{BDL_BASE}/{league}/v1/standings'
    data = fetch_json(url, headers=_bdl_headers(), params={'season': season})
    return data.get('data', [])

# ── NBA ───────────────────────────────────────────────────────────────────────

def scrape_nba():
    if is_frozen('NBA'):
        print('  ⏸ NBA is frozen, skipping'); return True
    try:
        rows = _bdl_standings('nba', 2025)
        if not rows: raise Exception('No data')
        standings = []
        for row in rows:
            name = row.get('team', {}).get('full_name', '')
            w, l = row.get('wins', 0), row.get('losses', 0)
            gp = w + l
            standings.append({'team': name, 'win_pct': round(w / gp, 4) if gp else 0})
        standings.sort(key=lambda x: x['win_pct'], reverse=True)
        return save_standing('NBA', {'standings': standings})
    except Exception as e:
        print(f'  ✗ NBA: {e}'); return False

# ── NHL ───────────────────────────────────────────────────────────────────────

def scrape_nhl():
    if is_frozen('NHL'):
        print('  ⏸ NHL is frozen, skipping'); return True
    try:
        rows = _bdl_standings('nhl', 2025)
        if not rows: raise Exception('No data')
        standings = []
        for row in rows:
            name = row.get('team', {}).get('full_name', '')
            pts = float(row.get('points', 0) or 0)
            gp  = float(row.get('games_played', 1) or 1)
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
        rows = _bdl_standings('mlb', 2026)
        if not rows: raise Exception('Season not started yet')
        standings = []
        for row in rows:
            name = row.get('team', {}).get('full_name', '')
            w, l = row.get('wins', 0), row.get('losses', 0)
            gp = w + l
            standings.append({'team': name, 'win_pct': round(w / gp, 4) if gp else 0})
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
        rows = _bdl_standings('ncaab', 2026)
        if not rows: raise Exception('No data')
        poll = [{'rank': i+1, 'team': row.get('team', {}).get('full_name', '')}
                for i, row in enumerate(rows[:25])]
        return save_standing('NCAAB', {'poll': poll})
    except Exception as e:
        print(f'  ✗ NCAAB: {e}'); return False

# ── MLS ───────────────────────────────────────────────────────────────────────

def scrape_mls():
    if is_frozen('MLS'):
        print('  ⏸ MLS is frozen, skipping'); return True
    try:
        data = fetch_json('https://v3.football.api-sports.io/standings',
            headers={'x-apisports-key': API_FOOTBALL_KEY},
            params={'league': 253, 'season': 2026})
        leagues = data.get('response', [])
        if not leagues: raise Exception('No MLS data')
        standings = [
            {'team': e.get('team', {}).get('name', ''), 'points': e.get('points', 0)}
            for e in leagues[0].get('league', {}).get('standings', [[]])[0]
        ]
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
            if len(cols) >= 3:
                try:
                    rank = int(cols[0].text.strip().replace('T', ''))
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
    print('\n🔄 Fantasy Life 2026 — Refreshing all data...\n')
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
        results[name] = status
        print(f'  → {name}: {status}')
    print('\n✅ Refresh complete!')
    return results

# ── Demo seed ─────────────────────────────────────────────────────────────────

def seed_demo_data():
    """Seed Supabase with starter data. Run once on empty DB."""
    print('Seeding demo data to Supabase...')
    save_standing('NBA', {'standings': [
        {'team': 'Cleveland Cavaliers', 'win_pct': 0.780},
        {'team': 'Oklahoma City Thunder', 'win_pct': 0.760},
        {'team': 'Boston Celtics', 'win_pct': 0.730},
        {'team': 'Houston Rockets', 'win_pct': 0.680},
        {'team': 'Denver Nuggets', 'win_pct': 0.650},
        {'team': 'New York Knicks', 'win_pct': 0.630},
        {'team': 'Minnesota Timberwolves', 'win_pct': 0.600},
        {'team': 'Golden State Warriors', 'win_pct': 0.560},
        {'team': 'Los Angeles Lakers', 'win_pct': 0.530},
        {'team': 'Milwaukee Bucks', 'win_pct': 0.490},
        {'team': 'Orlando Magic', 'win_pct': 0.450},
        {'team': 'Los Angeles Clippers', 'win_pct': 0.400},
        {'team': 'San Antonio Spurs', 'win_pct': 0.250},
    ]})
    save_standing('NHL', {'standings': [
        {'team': 'Florida Panthers', 'points_pct': 0.720},
        {'team': 'Colorado Avalanche', 'points_pct': 0.700},
        {'team': 'Toronto Maple Leafs', 'points_pct': 0.685},
        {'team': 'Carolina Hurricanes', 'points_pct': 0.670},
        {'team': 'Boston Bruins', 'points_pct': 0.655},
        {'team': 'Edmonton Oilers', 'points_pct': 0.640},
        {'team': 'Vegas Golden Knights', 'points_pct': 0.615},
        {'team': 'Washington Capitals', 'points_pct': 0.590},
        {'team': 'New York Rangers', 'points_pct': 0.560},
        {'team': 'Dallas Stars', 'points_pct': 0.530},
        {'team': 'Tampa Bay Lightning', 'points_pct': 0.500},
        {'team': 'New Jersey Devils', 'points_pct': 0.450},
        {'team': 'Detroit Red Wings', 'points_pct': 0.380},
    ]})
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
