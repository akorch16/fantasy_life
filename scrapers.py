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
from scoring import name_matches

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

ESPN_BASE = 'https://site.api.espn.com/apis/site/v2/sports'

def _espn_standings(sport, league):
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
            print(f'    NCAAB: {full_name} | {short_name} | {location} ({wins}-{losses})')
        ranked.sort(key=lambda x: x['pct'], reverse=True)
        poll = [{'rank': i+1, 'team': r['team'], 'short': r.get('short',''), 'location': r.get('location','')}
                for i, r in enumerate(ranked[:25])]
        return save_standing('NCAAB', {'poll': poll})
    except Exception as e:
        print(f'  ✗ NCAAB: {e}'); return False

# ── MLS (ESPN) ────────────────────────────────────────────────────────────────

def scrape_mls():
    if is_frozen('MLS'):
        print('  ⏸ MLS is frozen, skipping'); return True
    try:
        # Try multiple MLS slugs
        for slug in ['usa.1', 'mls', 'soccer.usa.1']:
            entries = _espn_standings('soccer', slug)
            if entries:
                standings = []
                for e in entries:
                    name = e.get('team', {}).get('displayName', '')
                    pts = _espn_stat(e, 'points') or _espn_stat(e, 'pts') or 0
                    standings.append({'team': name, 'points': pts})
                if standings:
                    standings.sort(key=lambda x: x['points'], reverse=True)
                    print(f'    ✓ Got {len(standings)} MLS teams from slug {slug}')
                    return save_standing('MLS', {'standings': standings})
        raise Exception('No MLS data from any slug')
    except Exception as e:
        print(f'  ✗ MLS: {e}'); return False

# ── NASCAR (manual) ───────────────────────────────────────────────────────────

def scrape_nascar():
    if is_frozen('NASCAR'):
        print('  ⏸ NASCAR is frozen, skipping'); return True
    print('  ℹ NASCAR: update manually in admin panel')
    return False

# ── Tennis (ESPN) ─────────────────────────────────────────────────────────────

def scrape_tennis():
    if is_frozen('Tennis'):
        print('  ⏸ Tennis is frozen, skipping'); return True
    try:
        rankings = []
        # ATP
        try:
            atp = fetch_json('https://site.web.api.espn.com/apis/v2/sports/tennis/rankings?tour=atp', timeout=15)
            for entry in atp.get('rankings', []):
                rank = entry.get('current') or entry.get('rank')
                player = entry.get('athlete', {}).get('displayName', '')
                if player and rank:
                    rankings.append({'player': player, 'rank': int(rank), 'tour': 'ATP'})
            print(f'    ATP: {len([r for r in rankings if r["tour"]=="ATP"])} players')
        except Exception as e:
            print(f'    ✗ ATP: {e}')

        # WTA
        try:
            wta = fetch_json('https://site.web.api.espn.com/apis/v2/sports/tennis/rankings?tour=wta', timeout=15)
            for entry in wta.get('rankings', []):
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

# ── Golf (ESPN OWGR) ──────────────────────────────────────────────────────────
def scrape_golf():
    if is_frozen('Golf'):
        print('  ⏸ Golf is frozen, skipping'); return True
    try:
        rankings = []
        # Try ESPN golf world rankings
        for url in [
            'https://site.web.api.espn.com/apis/v2/sports/golf/owgr/rankings',
            'https://site.web.api.espn.com/apis/v2/sports/golf/pga/rankings',
            'https://site.web.api.espn.com/apis/v2/sports/golf/rankings?tour=pga',
        ]:
            try:
                data = fetch_json(url, timeout=15)
                print(f'    Golf URL {url} keys: {list(data.keys())}')
                for entry in data.get('rankings', []):
                    rank = entry.get('current') or entry.get('rank')
                    player = entry.get('athlete', {}).get('displayName', '')
                    if player and rank:
                        rankings.append({'player': player, 'rank': int(rank)})
                if rankings:
                    print(f'    ✓ Got {len(rankings)} golf rankings')
                    break
            except Exception as e:
                print(f'    ✗ {url}: {e}')

        if rankings:
            return save_standing('Golf', {'rankings': rankings})

        # Fallback: OWGR with improved parsing
        soup = fetch_html('https://www.owgr.com/ranking')
        for row in soup.select('table tr')[1:60]:
            cols = row.find_all('td')
            if len(cols) >= 3:
                try:
                    rank = int(cols[0].text.strip())
                    player = ''
                    for idx in [2, 3, 1]:
                        candidate = cols[idx].text.strip() if len(cols) > idx else ''
                        if candidate and not candidate.replace(',','').replace('.','').isdigit():
                            player = candidate
                            break
                    if player:
                        rankings.append({'player': player, 'rank': rank})
                except (ValueError, AttributeError):
                    continue
        if rankings:
            return save_standing('Golf', {'rankings': rankings})
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

# ── Country GDP (World Bank) ──────────────────────────────────────────────────
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
        gdp = []
        for country in countries:
            code = ISO_MAP.get(country)
            if not code:
                print(f'    ✗ No ISO code for {country}')
                continue
            try:
                url = f'https://api.worldbank.org/v2/country/{code}/indicator/NY.GDP.MKTP.KD.ZG?format=json&mrv=5'
                r = requests.get(url, headers=HEADERS, timeout=8)
                r.raise_for_status()
                data = r.json()
                records = data[1] if isinstance(data, list) and len(data) > 1 else []
                for rec in records:
                    val = rec.get('value')
                    if val is not None:
                        gdp.append({'country': country, 'gdp_growth_pct': round(float(val), 2)})
                        print(f'    {country} ({code}): {val:.2f}%')
                        break
                else:
                    print(f'    ✗ No data for {country}')
            except Exception as e:
                print(f'    ✗ {country} skipped: {e}')
                continue  # skip this country, don't crash
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
                        scores_map[a]['hot100_weeks'] += 1  # #1 counts as top 10 too
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
