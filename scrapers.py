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

import requests
from bs4 import BeautifulSoup

from db import save_standing, is_frozen, get_standing
from scoring import name_matches

ESPN_BASE = 'https://site.api.espn.com/apis/site/v2/sports'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Referer': 'https://www.espn.com/',
    'Origin': 'https://www.espn.com',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
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
    urls = [
        f'https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/standings',
        f'https://site.web.api.espn.com/apis/v2/sports/{sport}/{league}/standings',
        f'https://site.web.api.espn.com/apis/v2/sports/{sport}/{league}/standings?seasontype=2&type=0&level=3',
    ]
    for url in urls:
        try:
            data = fetch_json(url, timeout=15)
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
    print('  ℹ NBA: 2025–26 regular season complete. Freeze in admin panel, update playoff bonuses in data/bonuses.json')
    return False

# ── NHL ───────────────────────────────────────────────────────────────────────

def _nhl_official_standings():
    """Fetch NHL standings from the official NHL API (no key required)."""
    url = 'https://api-web.nhle.com/v1/standings/now'
    data = fetch_json(url)
    standings = []
    for entry in data.get('standings', []):
        name = entry.get('teamName', {}).get('default', '')
        pts = entry.get('points', 0)
        gp = entry.get('gamesPlayed', 1)
        if name:
            standings.append({'team': name, 'points_pct': round(pts / (gp * 2), 4)})
    return standings


def scrape_nhl():
    if is_frozen('NHL'):
        print('  ⏸ NHL is frozen, skipping'); return True
    try:
        standings = []

        # Primary: official NHL API
        try:
            standings = _nhl_official_standings()
            if standings:
                print(f'    ✓ NHL official API: {len(standings)} teams')
        except Exception as e:
            print(f'    ✗ NHL official API: {e}')

        # Fallback: ESPN
        if not standings:
            entries = _espn_standings('hockey', 'nhl')
            for e in entries:
                name = e.get('team', {}).get('displayName', '')
                pts = _espn_stat(e, 'points') or 0
                gp = _espn_stat(e, 'gamesPlayed') or 1
                standings.append({'team': name, 'points_pct': round(pts / (gp * 2), 4)})

        if not standings:
            raise Exception('No data from NHL official API or ESPN')

        standings.sort(key=lambda x: x['points_pct'], reverse=True)
        return save_standing('NHL', {'standings': standings})
    except Exception as e:
        print(f'  ✗ NHL: {e}'); return False

# ── MLB ───────────────────────────────────────────────────────────────────────

def _mlb_statsapi_standings():
    """Fetch MLB standings from the official MLB Stats API (no key required)."""
    url = 'https://statsapi.mlb.com/api/v1/standings?leagueId=103,104&season=2026&standingsTypes=regularSeason'
    data = fetch_json(url, headers={
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/json',
    })
    standings = []
    for record in data.get('records', []):
        for tr in record.get('teamRecords', []):
            name = tr.get('team', {}).get('name', '')
            wins = tr.get('wins', 0)
            losses = tr.get('losses', 0)
            gp = wins + losses
            if name:
                standings.append({'team': name, 'win_pct': round(wins / gp, 4) if gp else 0, 'gp': gp})
    return standings


def scrape_mlb():
    if is_frozen('MLB'):
        print('  ⏸ MLB is frozen, skipping'); return True
    try:
        standings = []

        # Primary: official MLB Stats API
        try:
            standings = _mlb_statsapi_standings()
            if standings:
                print(f'    ✓ MLB Stats API: {len(standings)} teams')
        except Exception as e:
            print(f'    ✗ MLB Stats API: {e}')

        # Fallback: ESPN
        if not standings:
            entries = _espn_standings('baseball', 'mlb')
            for e in entries:
                name = e.get('team', {}).get('displayName', '')
                wins = _espn_stat(e, 'wins') or 0
                losses = _espn_stat(e, 'losses') or 0
                gp = wins + losses
                standings.append({'team': name, 'win_pct': round(wins / gp, 4) if gp else 0, 'gp': gp})

        if not standings:
            raise Exception('No data from MLB Stats API or ESPN')

        total_gp = sum(s['gp'] for s in standings)
        if total_gp == 0:
            print('  ⏸ MLB: season not started yet (0 games played)')
            return save_standing('MLB', {'standings': [], 'pre_season': True})
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

# ── NCAAB (ESPN - fixed name matching) ────────────────────────────────────────

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
        if not entries:
            # Try alternate URL
            url2 = 'https://site.web.api.espn.com/apis/v2/sports/basketball/mens-college-basketball/standings'
            data2 = fetch_json(url2, timeout=15)
            for conf in data2.get('children', []):
                for div in conf.get('children', [conf]):
                    for entry in div.get('standings', {}).get('entries', []):
                        entries.append(entry)
        if not entries: raise Exception('No data')
        ranked = []
        for e in entries:
            team = e.get('team', {})
            # Store both displayName and shortDisplayName for better matching
            full_name = team.get('displayName', '')
            short_name = team.get('shortDisplayName', '')
            location = team.get('location', '')
            wins = _espn_stat(e, 'wins') or 0
            losses = _espn_stat(e, 'losses') or 0
            gp = wins + losses
            pct = wins / gp if gp else 0
            ranked.append({
                'team': full_name,
                'short': short_name,
                'location': location,
                'pct': pct,
                'wins': wins,
                'losses': losses
            })
        ranked.sort(key=lambda x: x['pct'], reverse=True)
        poll = [{'rank': i+1, 'team': r['team'], 'short': r.get('short',''), 'location': r.get('location','')}
                for i, r in enumerate(ranked[:25])]
        return save_standing('NCAAB', {'poll': poll})
    except Exception as e:
        print(f'  ✗ NCAAB: {e}'); return False

# ── Wikipedia standings helper ────────────────────────────────────────────────

def _wiki_points_table(url, name_hints, points_hints=('pts', 'points'), timeout=20, max_cols=15):
    """Parse (name, points) pairs from Wikipedia wikitables.

    Header-driven: a table qualifies only if its header row contains BOTH a points
    column (matching points_hints) and a name column (matching name_hints), which
    avoids grabbing unrelated tables. Returns a list of {'name', 'points'} dicts,
    deduped by name keeping the max points seen. Reused by MLS and NASCAR.

    `max_cols` rejects season race-by-race result GRIDS (one column per race,
    e.g. NASCAR's "pos. | driver | atl | coa | pho | ... | pts. | stages" table)
    which coincidentally have both a driver/team column and a trailing "pts."
    column but hold PER-RACE finish positions, not the actual season points
    total — a real standings table is compact (well under 15 columns). Confirmed
    via probe: without this filter NASCAR silently scraped that grid and served
    single-digit-race point totals (~150-180) as if they were season standings.
    """
    soup = fetch_html(url, timeout=timeout)
    found = {}
    tables_scanned = 0
    for table in soup.select('table.wikitable'):
        rows = table.select('tr')
        if not rows:
            continue
        headers = [c.get_text(strip=True).lower() for c in rows[0].find_all(['th', 'td'])]
        if len(headers) > max_cols:
            continue
        pts_idx = next((i for i, h in enumerate(headers)
                        if any(k == h or k.strip('.') == h for k in points_hints)), None)
        if pts_idx is None:
            pts_idx = next((i for i, h in enumerate(headers)
                            if any(k in h for k in points_hints)), None)
        name_idx = next((i for i, h in enumerate(headers)
                         if any(k in h for k in name_hints)), None)
        if pts_idx is None or name_idx is None:
            continue
        tables_scanned += 1
        for row in rows[1:]:
            cells = row.find_all(['td', 'th'])
            if len(cells) <= max(pts_idx, name_idx):
                continue
            name = cells[name_idx].get_text(' ', strip=True)
            if not name:
                link = cells[name_idx].find('a') or row.find('a')
                name = link.get_text(strip=True) if link else ''
            m = re.search(r'-?\d+', cells[pts_idx].get_text(strip=True).replace(',', ''))
            if not name or not m:
                continue
            name = name.strip()
            pts = int(m.group())
            if name not in found or pts > found[name]:
                found[name] = pts
    return [{'name': n, 'points': p} for n, p in found.items()], tables_scanned

# ── MLS (ESPN JSON → Wikipedia fallback) ──────────────────────────────────────

def scrape_mls():
    if is_frozen('MLS'):
        print('  ⏸ MLS is frozen, skipping'); return True
    try:
        standings = []
        source = None

        # Tier 1: ESPN soccer standings (usa.1 = MLS). Often 403s from datacenter IPs.
        try:
            data = fetch_json(f'{ESPN_BASE}/soccer/usa.1/standings', timeout=15)
            for child in data.get('children', []):
                for entry in child.get('standings', {}).get('entries', []):
                    team = entry.get('team', {}).get('displayName', '')
                    pts = next((s.get('value') for s in entry.get('stats', [])
                                if s.get('name') == 'points' or s.get('type') == 'points'), None)
                    if team and pts is not None:
                        standings.append({'team': team, 'points': int(pts)})
            if standings:
                source = 'live'
                print(f'    ✓ ESPN soccer API: {len(standings)} teams')
        except Exception as e:
            print(f'    ✗ ESPN soccer API: {e}')

        # Tier 2: Wikipedia season page
        if not standings:
            try:
                rows, n = _wiki_points_table(
                    'https://en.wikipedia.org/wiki/2026_Major_League_Soccer_season',
                    name_hints=('team',))
                standings = [{'team': r['name'], 'points': r['points']} for r in rows]
                if standings:
                    source = 'wikipedia'
                    print(f'    ✓ Wikipedia MLS: {len(standings)} teams from {n} table(s)')
            except Exception as e:
                print(f'    ✗ Wikipedia MLS: {e}')

        if standings:
            print(f'  ✓ MLS via {source} ({len(standings)} teams)')
            return save_standing('MLS', {'standings': standings, '_source': source})
        print('  ⚠ MLS: ALL LIVE SOURCES FAILED → scoring will use data/mls.json or static dict')
        return False
    except Exception as e:
        print(f'  ✗ MLS: {e}'); return False

# ── NASCAR (ESPN JSON → Wikipedia fallback) ───────────────────────────────────

def scrape_nascar():
    if is_frozen('NASCAR'):
        print('  ⏸ NASCAR is frozen, skipping'); return True
    try:
        standings = []
        source = None

        # Tier 1: ESPN racing standings. Response uses children[].standings.entries structure.
        try:
            data = fetch_json('https://site.api.espn.com/apis/v2/sports/racing/nascar-premier/standings', timeout=15)
            entries = []
            for child in data.get('children', []):
                entries.extend(child.get('standings', {}).get('entries', []))
            # fall back to top-level standings[] shape if children absent
            if not entries:
                for group in data.get('standings', []) if isinstance(data.get('standings'), list) else []:
                    entries.extend(group.get('standings', {}).get('entries', []) if isinstance(group, dict) else [])
            for entry in entries:
                driver = entry.get('athlete', {}).get('displayName', '')
                pts = next((s.get('value') for s in entry.get('stats', [])
                            if s.get('name') == 'points'), None)
                if driver and pts is not None:
                    standings.append({'driver': driver, 'points': int(pts)})
            if standings:
                source = 'live'
                print(f'    ✓ ESPN racing API: {len(standings)} drivers')
        except Exception as e:
            print(f'    ✗ ESPN racing API: {e}')

        # Tier 2: Wikipedia season page (Drivers' Championship table)
        if not standings:
            try:
                rows, n = _wiki_points_table(
                    'https://en.wikipedia.org/wiki/2026_NASCAR_Cup_Series',
                    name_hints=('driver',))
                standings = [{'driver': r['name'], 'points': r['points']} for r in rows]
                if standings:
                    source = 'wikipedia'
                    print(f'    ✓ Wikipedia NASCAR: {len(standings)} drivers from {n} table(s)')
            except Exception as e:
                print(f'    ✗ Wikipedia NASCAR: {e}')

        if standings:
            print(f'  ✓ NASCAR via {source} ({len(standings)} drivers)')
            return save_standing('NASCAR', {'standings': standings, '_source': source})
        print('  ⚠ NASCAR: ALL LIVE SOURCES FAILED → scoring will use data/nascar.json or static dict')
        return False
    except Exception as e:
        print(f'  ✗ NASCAR: {e}'); return False

# ── Tennis (ESPN) ─────────────────────────────────────────────────────────────

def scrape_tennis():
    if is_frozen('Tennis'):
        print('  ⏸ Tennis is frozen, skipping'); return True
    try:
        rankings = []
        # ATP
        try:
            atp = fetch_json('https://site.api.espn.com/apis/site/v2/sports/tennis/atp/rankings', timeout=15)
            for entry in atp.get('rankings', [{}])[0].get('ranks', []):
                rank = entry.get('current') or entry.get('rank')
                player = entry.get('athlete', {}).get('displayName', '')
                if player and rank:
                    rankings.append({'player': player, 'rank': int(rank), 'tour': 'ATP'})
            print(f'    ATP: {len([r for r in rankings if r["tour"]=="ATP"])} players')
        except Exception as e:
            print(f'    ✗ ATP: {e}')

        # WTA
        try:
            wta = fetch_json('https://site.api.espn.com/apis/site/v2/sports/tennis/wta/rankings', timeout=15)
            for entry in wta.get('rankings', [{}])[0].get('ranks', []):
                rank = entry.get('current') or entry.get('rank')
                player = entry.get('athlete', {}).get('displayName', '')
                if player and rank:
                    rankings.append({'player': player, 'rank': int(rank), 'tour': 'WTA'})
            print(f'    WTA: {len([r for r in rankings if r["tour"]=="WTA"])} players')
        except Exception as e:
            print(f'    ✗ WTA: {e}')

        if rankings:
            return save_standing('Tennis', {'rankings': rankings})

        # Fallback to scraping ATP site
        soup = fetch_html('https://www.atptour.com/en/rankings/singles')
        for row in soup.select('table tbody tr')[:50]:
            cols = row.find_all('td')
            if len(cols) >= 4:
                try:
                    rank = int(cols[0].text.strip().replace('T', ''))
                    # Try cols 3, 4 for player name (skip rank, move, country, points)
                    for idx in [3, 4, 2]:
                        candidate = cols[idx].text.strip() if len(cols) > idx else ''
                        if candidate and not candidate.replace(',','').replace('.','').isdigit():
                            player = candidate
                            break
                    if player:
                        rankings.append({'player': player, 'rank': rank, 'tour': 'ATP'})
                except (ValueError, AttributeError):
                    continue

        if rankings:
            return save_standing('Tennis', {'rankings': rankings})
        raise Exception('No rankings found')
    except Exception as e:
        print(f'  ✗ Tennis: {e}'); return False

# ── Golf ─────────────────────────────────────────────────────────────────────
# OWGR's own site (API + HTML) fully 404s and ESPN /golf/pga/rankings 500s, but
# the PGA Tour's GraphQL API publishes the Official World Golf Ranking (statId
# 186) via a public AppSync key embedded in pgatour.com's JS. That's the live
# source. NOTE: must request gzip/deflate (not brotli) — requests can't decode br.

# Public AppSync key from pgatour.com's JS bundle. Rotates rarely; a 401 here
# means grab the current key from the site source and update this constant.
PGATOUR_GRAPHQL_URL = 'https://orchestrator.pgatour.com/graphql'
PGATOUR_API_KEY = 'da2-gsrx5bibzbb4njvhl7t37wqyl4'
_OWGR_QUERY = """query StatDetails($tourCode: TourCode!, $statId: String!, $year: Int) {
  statDetails(tourCode: $tourCode, statId: $statId, year: $year) {
    statId
    statTitle
    rows { ... on StatDetailsPlayer { playerName rank } }
  }
}"""

def scrape_golf():
    if is_frozen('Golf'):
        print('  ⏸ Golf is frozen, skipping'); return True
    try:
        rankings = []

        # Tier 1: PGA Tour GraphQL — Official World Golf Ranking (statId 186).
        try:
            r = requests.post(
                PGATOUR_GRAPHQL_URL,
                json={'query': _OWGR_QUERY,
                      'variables': {'tourCode': 'R', 'statId': '186', 'year': datetime.now().year}},
                headers={**HEADERS, 'x-api-key': PGATOUR_API_KEY,
                         'Content-Type': 'application/json', 'Accept-Encoding': 'gzip, deflate'},
                timeout=20,
            )
            r.raise_for_status()
            rows = (r.json().get('data', {}).get('statDetails') or {}).get('rows', [])
            for row in rows:
                player = row.get('playerName', '')
                rank = row.get('rank')
                if player and rank:
                    rankings.append({'player': player, 'rank': int(rank)})
            if rankings:
                print(f'    ✓ PGA Tour GraphQL (OWGR statId 186): {len(rankings)} players')
        except Exception as e:
            print(f'    ✗ PGA Tour GraphQL: {e}')

        if rankings:
            print(f'  ✓ Golf via pgatour ({len(rankings)} players)')
            return save_standing('Golf', {'rankings': rankings, '_source': 'pgatour'})
        print('  ⚠ Golf: ALL LIVE SOURCES FAILED → scoring will use data/golf.json or static dict')
        return False
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
                body = r.json()
                results = body.get('chart', {}).get('result') or []
                if not results:
                    raise Exception('empty result from Yahoo Finance')
                data = results[0]
                meta = data.get('meta', {})
                current = meta.get('regularMarketPrice') or meta.get('previousClose')
                closes = (data.get('indicators', {}).get('quote') or [{}])[0].get('close', [])
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

# ── Country GDP (IMF WEO DataMapper) ─────────────────────────────────────────
def scrape_country_gdp():
    if is_frozen('Country'):
        print('  ⏸ Country is frozen, skipping'); return True
    try:
        from draft_picks_2026 import DRAFT_PICKS_2026
        ISO_MAP = {
            'Netherlands': 'NLD', 'United States': 'USA', 'Germany': 'DEU',
            'Guinea': 'GIN', 'South Sudan': 'SSD', 'France': 'FRA',
            'Switzerland': 'CHE', 'Brazil': 'BRA', 'Norway': 'NOR',
            'Guyana': 'GUY', 'Argentina': 'ARG', 'Spain': 'ESP', 'Canada': 'CAN',
        }
        countries = list(DRAFT_PICKS_2026['Country'].values())
        codes = [ISO_MAP[c] for c in countries if c in ISO_MAP]

        # Primary: IMF DataMapper API — returns current WEO forecast year (not historical actuals)
        codes_str = '/'.join(codes)
        url = f'https://www.imf.org/external/datamapper/api/v1/NGDP_RPCH/{codes_str}'
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        values = data.get('values', {}).get('NGDP_RPCH', {})

        # Use current year; fall back to next year if current year not yet published
        import datetime
        year = str(datetime.date.today().year)
        gdp_lookup = {}
        for code, years in values.items():
            val = years.get(year) or years.get(str(int(year) + 1))
            if val is not None:
                gdp_lookup[code] = round(float(val), 2)

        gdp = []
        for country in countries:
            code = ISO_MAP.get(country)
            if code and code in gdp_lookup:
                gdp.append({'country': country, 'gdp_growth_pct': gdp_lookup[code]})
                print(f'    {country} ({code}): {gdp_lookup[code]}%')
            else:
                print(f'    ✗ No data for {country}')

        if gdp:
            return save_standing('Country', {'gdp': gdp})
        raise Exception('No GDP data found')
    except Exception as e:
        print(f'  ✗ Country: {e}'); return False


# ── Musician (Billboard) ──────────────────────────────────────────────────────
def scrape_billboard():
    if is_frozen('Musician'):
        print('  ⏸ Musician is frozen, skipping'); return True
    try:
        import re
        scores_map = {}

        # ── Page 1: #1 weeks ─────────────────────────────────────────────
        try:
            soup1 = fetch_html('https://en.wikipedia.org/wiki/List_of_Billboard_Hot_100_number_ones_of_2026', timeout=15)
            for table in soup1.select('table.wikitable'):
                for row in table.select('tr'):
                    cols = row.find_all(['td', 'th'])
                    if len(cols) < 4:
                        continue
                    # Table: No. | Issue date | Song | Artist(s) | Ref.
                    artist_text = cols[3].get_text(separator=' ', strip=True)
                    # Skip header rows
                    if artist_text.lower() in ('artist', 'artist(s)', 'ref.', ''):
                        continue
                    # Each row = 1 week at #1
                    artists = re.split(r'\s*[,&]\s*|\s+feat\.\s+|\s+and\s+', artist_text, flags=re.IGNORECASE)
                    for a in artists:
                        a = a.strip().strip('"').strip()
                        if not a or len(a) < 2:
                            continue
                        if a not in scores_map:
                            scores_map[a] = {'artist': a, 'num1_weeks': 0, 'hot100_weeks': 0}
                        scores_map[a]['num1_weeks'] += 1
                        # hot100_weeks is populated entirely by the top-10 page to avoid double-counting
            print(f'    #1 page: {len(scores_map)} artists found')
        except Exception as e:
            print(f'    ✗ #1 page: {e}')

        # ── Page 2: top-10 weeks ──────────────────────────────────────────
        try:
            soup2 = fetch_html('https://en.wikipedia.org/wiki/List_of_Billboard_Hot_100_top-ten_singles_in_2026', timeout=15)
            for table in soup2.select('table.wikitable'):
                for row in table.select('tr'):
                    cols = row.find_all(['td', 'th'])
                    if len(cols) < 6:
                        continue
                    # Table: Date | Single | Artist(s) | Peak | Peak date | Weeks in top ten | Ref.
                    artist_text = cols[2].get_text(separator=' ', strip=True)
                    weeks_text  = cols[5].get_text(strip=True).replace('*', '').strip()

                    if not weeks_text or artist_text.lower() in ('artist', 'artist(s)'):
                        continue
                    try:
                        weeks = int(weeks_text.split()[0])
                    except ValueError:
                        continue

                    artists = re.split(r'\s*[,&]\s*|\s+feat\.\s+|\s+and\s+', artist_text, flags=re.IGNORECASE)
                    for a in artists:
                        a = a.strip().strip('"').strip()
                        if not a or len(a) < 2:
                            continue
                        if a not in scores_map:
                            scores_map[a] = {'artist': a, 'num1_weeks': 0, 'hot100_weeks': 0}
                        scores_map[a]['hot100_weeks'] += weeks
            print(f'    Top-10 page: {len(scores_map)} total artists found')
        except Exception as e:
            print(f'    ✗ Top-10 page: {e}')

        if scores_map:
            # Log picks that matched
            from draft_picks_2026 import DRAFT_PICKS_2026
            picks = list(DRAFT_PICKS_2026.get('Musician', {}).values())
            for pick in picks:
                match = next((v for k, v in scores_map.items() if name_matches(pick, k)), None)
                if match:
                    print(f'    ✓ {pick}: {match["num1_weeks"]} #1 wks, {match["hot100_weeks"]} top-10 wks')
                else:
                    print(f'    – {pick}: no chart data')
            return save_standing('Musician', {'scores': list(scores_map.values())})

        raise Exception('No chart data found')
    except Exception as e:
        print(f'  ✗ Musician/Wikipedia: {e}'); return False

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

    # Degradation summary: surface any live-scraped category that failed, so a
    # run leaning on stale data/*.json or static dicts is obvious at a glance.
    LIVE_CATS = {'NBA', 'NHL', 'MLB', 'NCAAB', 'Tennis', 'Golf', 'NASCAR', 'MLS', 'Stock', 'Country', 'Musician'}
    degraded = [n for n, s in results.items() if n in LIVE_CATS and s != 'ok']
    if degraded:
        print(f'\n⚠ DEGRADED — {len(degraded)} live categor{"y" if len(degraded)==1 else "ies"} '
              f'did not refresh (scoring will fall back): {", ".join(degraded)}')
    else:
        print('\n✅ All live categories refreshed.')
    print('\n✅ Refresh complete!')
    return results


# ── Probe mode ────────────────────────────────────────────────────────────────

def probe():
    """GET each candidate source and report status/size, without saving anything.

    Run on the GitHub Actions runner (`python scrapers.py --probe`) to learn which
    endpoints the runner can actually reach — this environment cannot be used because
    its egress is allowlisted. Deciding input for the golf live tier and for whether
    ESPN's soccer/racing trees work from the Actions IP.
    """
    candidates = [
        ('MLS  · ESPN soccer',   f'{ESPN_BASE}/soccer/usa.1/standings'),
        ('MLS  · Wikipedia',     'https://en.wikipedia.org/wiki/2026_Major_League_Soccer_season'),
        ('NASCAR · ESPN racing', 'https://site.api.espn.com/apis/v2/sports/racing/nascar-premier/standings'),
        ('NASCAR · Wikipedia',   'https://en.wikipedia.org/wiki/2026_NASCAR_Cup_Series'),
        # Golf — all confirmed dead as of 2026-06-17; kept here for future re-probing
        # OWGR: entire owgr.com domain returns 404 (API and HTML page)
        # ESPN /golf/pga/rankings → 500; /golf/pga/standings → empty stub
        # ESPN /golf/leaderboard → 200 but is tournament event data, not OWGR rankings
        ('Golf · ESPN leaderboard', 'https://site.api.espn.com/apis/site/v2/sports/golf/leaderboard'),
        ('Golf · OWGR API',         'https://www.owgr.com/api/owgr/ranking?pageNo=1&pageSize=200'),
    ]
    print('\n🔎 Probing candidate sources (no data saved)...\n')
    for label, url in candidates:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            snippet = r.text[:100].replace('\n', ' ')
            print(f'  [{r.status_code}] {label}  ({len(r.content)} bytes)')
            print(f'        {url}')
            if r.status_code == 200:
                print(f'        {snippet}')
        except Exception as e:
            print(f'  [ERR] {label}: {e}')
            print(f'        {url}')

    _probe_golf()
    _probe_espn_nascar()
    _probe_wiki_points_table('NASCAR', 'https://en.wikipedia.org/wiki/2026_NASCAR_Cup_Series', ('driver',))
    _probe_wiki_points_table('MLS', 'https://en.wikipedia.org/wiki/2026_Major_League_Soccer_season', ('team',))
    print('\n🔎 Probe complete.')


def _probe_espn_nascar():
    """Dump the raw shape of the ESPN racing standings response — scrape_nascar's
    tier-1 parser expects children[].standings.entries[]; if ESPN changed the
    response shape this shows exactly where the mismatch is instead of silently
    falling through to the (previously buggy) Wikipedia tier."""
    print('\n  ── NASCAR ESPN tier-1 deep-probe ──')
    try:
        data = fetch_json('https://site.api.espn.com/apis/v2/sports/racing/nascar-premier/standings', timeout=15)
    except Exception as e:
        print(f'    ✗ fetch_json failed: {e}')
        return
    print(f'    top-level keys: {list(data.keys())}')
    children = data.get('children', [])
    print(f'    children: {len(children)}')
    for i, child in enumerate(children[:3]):
        print(f'      child[{i}] keys={list(child.keys())} name={child.get("name")!r}')
        standings = child.get('standings', {})
        print(f'        standings keys={list(standings.keys()) if isinstance(standings, dict) else type(standings)}')
        entries = standings.get('entries', []) if isinstance(standings, dict) else []
        print(f'        entries: {len(entries)}')
        if entries:
            e = entries[0]
            print(f'        entries[0] keys={list(e.keys())}')
            print(f'        entries[0].athlete={e.get("athlete")}')
            print(f'        entries[0].stats={e.get("stats")}')
    top_standings = data.get('standings')
    print(f'    top-level "standings" type: {type(top_standings)}'
          + (f' len={len(top_standings)}' if isinstance(top_standings, list) else ''))


def _probe_wiki_points_table(label, url, name_hints, points_hints=('pts', 'points')):
    """Dump every wikitable on the page that matches (name, points) headers,
    with its column count, row count, and top-5 values — makes it obvious if
    a season race/match-results GRID is being mistaken for the real standings
    table (see _wiki_points_table's max_cols guard) without deep debugging."""
    print(f'\n  ── {label} Wikipedia deep-probe ──')
    try:
        soup = fetch_html(url, timeout=20)
    except Exception as e:
        print(f'    ✗ fetch_html failed: {e}')
        return
    qualifying = 0
    for ti, table in enumerate(soup.select('table.wikitable')):
        rows = table.select('tr')
        if not rows:
            continue
        headers = [c.get_text(strip=True).lower() for c in rows[0].find_all(['th', 'td'])]
        pts_idx = next((i for i, h in enumerate(headers)
                        if any(k == h or k.strip('.') == h for k in points_hints)), None)
        if pts_idx is None:
            pts_idx = next((i for i, h in enumerate(headers)
                            if any(k in h for k in points_hints)), None)
        name_idx = next((i for i, h in enumerate(headers)
                         if any(k in h for k in name_hints)), None)
        if pts_idx is None or name_idx is None:
            continue
        qualifying += 1
        parsed = []
        for row in rows[1:]:
            cells = row.find_all(['td', 'th'])
            if len(cells) <= max(pts_idx, name_idx):
                continue
            name = cells[name_idx].get_text(' ', strip=True)
            if not name:
                link = cells[name_idx].find('a') or row.find('a')
                name = link.get_text(strip=True) if link else ''
            m = re.search(r'-?\d+', cells[pts_idx].get_text(strip=True).replace(',', ''))
            if name and m:
                parsed.append((name, int(m.group())))
        top = sorted(parsed, key=lambda x: -x[1])[:5]
        flag = '  ⚠ likely a race/match GRID, not standings' if len(headers) > 15 else ''
        print(f'    Table #{ti}: cols={len(headers)} rows_parsed={len(parsed)} top5={top}{flag}')
    print(f'    {qualifying} table(s) matched name_hints={name_hints} points_hints={points_hints} '
          f'(_wiki_points_table max_cols=15 filter applies at scrape time)')


def _probe_golf():
    """Deep golf probe of the PGA Tour GraphQL API (POST) that backs pgatour.com's
    world-ranking page. (OWGR's whole domain 404s, so it's not probed anymore.)

    NOTE: must NOT request brotli (`br`) encoding — `requests` can't decode it
    without the brotli package, which would leave r.text as binary garbage.
    """
    print('\n  ── Golf deep-probe ──')

    gql_url = 'https://orchestrator.pgatour.com/graphql'
    # Public AppSync key from pgatour.com's JS bundle; rotates rarely (401 if stale).
    gql_key = 'da2-gsrx5bibzbb4njvhl7t37wqyl4'
    # statId 186 = Official World Golf Ranking (confirmed: returns ~35 KB payload).
    query = """query StatDetails($tourCode: TourCode!, $statId: String!, $year: Int) {
      statDetails(tourCode: $tourCode, statId: $statId, year: $year) {
        statId
        statTitle
        rows {
          ... on StatDetailsPlayer { playerId playerName rank stats { statName statValue } }
        }
      }
    }"""
    variables = {'tourCode': 'R', 'statId': '186', 'year': 2026}
    headers = {**HEADERS, 'x-api-key': gql_key, 'Content-Type': 'application/json',
               'Accept-Encoding': 'gzip, deflate'}
    try:
        r = requests.post(gql_url, json={'query': query, 'variables': variables},
                          headers=headers, timeout=20)
        print(f'  [{r.status_code}] Golf · PGA GraphQL statId=186  ({len(r.content)} bytes)')
        print(f'        {r.text[:1800]}')
    except Exception as e:
        print(f'  [ERR] Golf · PGA GraphQL: {e}')

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
    import sys
    if '--probe' in sys.argv:
        probe()
    else:
        refresh_all()
