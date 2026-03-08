"""
Fantasy Life 2026 — Data Scrapers
Fetches live data from sports sources and caches to JSON files.
"""

import json
import os
import re
from datetime import datetime

try:
    import requests
    from bs4 import BeautifulSoup
    SCRAPING_AVAILABLE = True
except ImportError:
    SCRAPING_AVAILABLE = False

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}


def save_data(key, data):
    path = os.path.join(DATA_DIR, f'{key}.json')
    data['_updated'] = datetime.utcnow().isoformat()
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"  ✓ {key} saved ({len(str(data))} chars)")
    return data


def fetch_url(url, timeout=15):
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return BeautifulSoup(r.text, 'html.parser')


# ─── SPORTS REFERENCE (NFL/NBA/MLB/NHL/NCAAF/NCAAB) ──────────────────────────

def scrape_sports_ref_standings(url, team_col, value_col, value_type='float'):
    """Generic sports-reference.com standings scraper."""
    soup = fetch_url(url)
    standings = []
    for table in soup.find_all('table'):
        for row in table.find_all('tr'):
            cells = row.find_all(['td', 'th'])
            if len(cells) < 3:
                continue
            try:
                team = None
                for cell in cells:
                    if cell.get('data-stat') == team_col:
                        a = cell.find('a')
                        team = a.text.strip() if a else cell.text.strip()
                    if team and cell.get('data-stat') == value_col:
                        val_text = cell.text.strip()
                        if val_text and val_text != '—':
                            val = float(val_text) if value_type == 'float' else int(val_text)
                            standings.append({'team': team, value_col: val})
                            break
            except (ValueError, AttributeError):
                continue
    return standings


def scrape_nfl():
    """NFL win percentage from sports-reference.com"""
    try:
        url = 'https://www.pro-football-reference.com/years/2025/'
        soup = fetch_url(url)
        standings = []
        for table in soup.find_all('table', id=re.compile('AFC|NFC')):
            for row in table.find_all('tr', class_=lambda c: c != 'thead'):
                tds = {td.get('data-stat'): td for td in row.find_all(['td', 'th'])}
                if 'team' not in tds:
                    continue
                a = tds['team'].find('a')
                team = a.text.strip() if a else tds['team'].text.strip()
                try:
                    wins = int(tds.get('wins', tds.get('w', '')).text.strip())
                    losses = int(tds.get('losses', tds.get('l', '')).text.strip())
                    ties = int(tds.get('ties', tds.get('t', {0: '0'})).text.strip() or 0)
                    total = wins + losses + ties
                    win_pct = wins / total if total > 0 else 0
                    standings.append({'team': team, 'win_pct': round(win_pct, 4)})
                except (ValueError, AttributeError):
                    continue
        return save_data('nfl', {'standings': standings})
    except Exception as e:
        print(f"  ✗ NFL scrape failed: {e}")
        return None


def scrape_nba():
    """NBA win percentage"""
    try:
        url = 'https://www.basketball-reference.com/leagues/NBA_2026_standings.html'
        soup = fetch_url(url)
        standings = []
        for table in soup.find_all('table'):
            for row in table.find_all('tr'):
                tds = {td.get('data-stat'): td for td in row.find_all(['td', 'th'])}
                if 'team_name' not in tds:
                    continue
                a = tds['team_name'].find('a')
                team = a.text.strip() if a else tds['team_name'].text.strip()
                try:
                    win_pct = float(tds.get('win_loss_pct', tds.get('pct', '')).text.strip())
                    standings.append({'team': team, 'win_pct': win_pct})
                except (ValueError, AttributeError, KeyError):
                    continue
        return save_data('nba', {'standings': standings})
    except Exception as e:
        print(f"  ✗ NBA scrape failed: {e}")
        return None


def scrape_mlb():
    """MLB win percentage"""
    try:
        url = 'https://www.baseball-reference.com/leagues/majors/2026-standings.shtml'
        soup = fetch_url(url)
        standings = []
        for table in soup.find_all('table'):
            for row in table.find_all('tr'):
                tds = {td.get('data-stat'): td for td in row.find_all(['td', 'th'])}
                if 'team_ID' not in tds and 'team' not in tds:
                    continue
                team_cell = tds.get('team_ID') or tds.get('team')
                if not team_cell:
                    continue
                a = team_cell.find('a')
                team = a.text.strip() if a else team_cell.text.strip()
                try:
                    win_pct = float(tds.get('win_loss_pct', {}).text.strip())
                    standings.append({'team': team, 'win_pct': win_pct})
                except (ValueError, AttributeError, KeyError):
                    continue
        return save_data('mlb', {'standings': standings})
    except Exception as e:
        print(f"  ✗ MLB scrape failed: {e}")
        return None


def scrape_nhl():
    """NHL points percentage from hockey-reference"""
    try:
        url = 'https://www.hockey-reference.com/leagues/NHL_2026_standings.html'
        soup = fetch_url(url)
        standings = []
        for table in soup.find_all('table'):
            for row in table.find_all('tr'):
                tds = {td.get('data-stat'): td for td in row.find_all(['td', 'th'])}
                if 'team_name' not in tds:
                    continue
                a = tds['team_name'].find('a')
                team = a.text.strip() if a else tds['team_name'].text.strip()
                try:
                    pts_pct = float(tds.get('points_pct', {}).text.strip())
                    standings.append({'team': team, 'points_pct': pts_pct})
                except (ValueError, AttributeError, KeyError):
                    continue
        return save_data('nhl', {'standings': standings})
    except Exception as e:
        print(f"  ✗ NHL scrape failed: {e}")
        return None


def scrape_ncaaf():
    """NCAAF AP Poll from sports-reference"""
    try:
        url = 'https://www.sports-reference.com/cfb/years/2026-polls.html'
        soup = fetch_url(url)
        poll = []
        # Parse latest AP poll table
        for table in soup.find_all('table', id=re.compile('ap')):
            for row in table.find_all('tr')[1:]:
                cells = row.find_all('td')
                if len(cells) >= 2:
                    try:
                        rank = int(cells[0].text.strip())
                        a = cells[1].find('a')
                        team = a.text.strip() if a else cells[1].text.strip()
                        poll.append({'rank': rank, 'team': team})
                    except (ValueError, AttributeError):
                        continue
        return save_data('ncaaf', {'poll': poll})
    except Exception as e:
        print(f"  ✗ NCAAF scrape failed: {e}")
        return None


def scrape_ncaab():
    """NCAAB AP Poll"""
    try:
        url = 'https://www.sports-reference.com/cbb/seasons/men/2026-polls.html'
        soup = fetch_url(url)
        poll = []
        for table in soup.find_all('table', id=re.compile('ap')):
            for row in table.find_all('tr')[1:]:
                cells = row.find_all('td')
                if len(cells) >= 2:
                    try:
                        rank = int(cells[0].text.strip())
                        a = cells[1].find('a')
                        team = a.text.strip() if a else cells[1].text.strip()
                        poll.append({'rank': rank, 'team': team})
                    except (ValueError, AttributeError):
                        continue
        return save_data('ncaab', {'poll': poll})
    except Exception as e:
        print(f"  ✗ NCAAB scrape failed: {e}")
        return None


def scrape_tennis():
    """ATP/WTA rankings from Tennis Abstract"""
    try:
        # ATP
        atp_url = 'https://www.tennisabstract.com/reports/atp_elo_ratings.html'
        soup = fetch_url(atp_url)
        rankings = []
        for row in soup.find_all('tr')[1:]:
            cells = row.find_all('td')
            if len(cells) >= 2:
                try:
                    rank = int(cells[0].text.strip())
                    player = cells[1].text.strip()
                    rankings.append({'player': player, 'rank': rank, 'tour': 'ATP'})
                except (ValueError, AttributeError):
                    continue

        # WTA — try official WTA rankings page
        wta_url = 'https://www.wtatennis.com/rankings/singles'
        soup2 = fetch_url(wta_url)
        for row in soup2.find_all('tr')[1:50]:
            cells = row.find_all('td')
            if len(cells) >= 2:
                try:
                    rank = int(cells[0].text.strip())
                    player = cells[1].text.strip()
                    rankings.append({'player': player, 'rank': rank, 'tour': 'WTA'})
                except (ValueError, AttributeError):
                    continue

        return save_data('tennis', {'rankings': rankings})
    except Exception as e:
        print(f"  ✗ Tennis scrape failed: {e}")
        return None


def scrape_golf():
    """OWGR from golftoday.co.uk"""
    try:
        url = 'https://www.golftoday.co.uk/world-golf-rankings/'
        soup = fetch_url(url)
        rankings = []
        for table in soup.find_all('table'):
            for row in table.find_all('tr')[1:]:
                cells = row.find_all('td')
                if len(cells) >= 2:
                    try:
                        rank = int(cells[0].text.strip())
                        player = cells[1].text.strip()
                        rankings.append({'player': player, 'rank': rank})
                    except (ValueError, AttributeError):
                        continue
        return save_data('golf', {'rankings': rankings})
    except Exception as e:
        print(f"  ✗ Golf scrape failed: {e}")
        return None


def scrape_nascar():
    """NASCAR standings from NASCAR.com"""
    try:
        url = 'https://www.nascar.com/nascar-cup-series/2026/driver-points/'
        soup = fetch_url(url)
        standings = []
        for row in soup.find_all('tr')[1:]:
            cells = row.find_all('td')
            if len(cells) >= 3:
                try:
                    driver = cells[1].text.strip()
                    points = int(cells[2].text.strip().replace(',', ''))
                    standings.append({'driver': driver, 'points': points})
                except (ValueError, AttributeError):
                    continue
        return save_data('nascar', {'standings': standings})
    except Exception as e:
        print(f"  ✗ NASCAR scrape failed: {e}")
        return None


def scrape_mls():
    """MLS standings"""
    try:
        url = 'https://www.mlssoccer.com/standings/2026/'
        soup = fetch_url(url)
        standings = []
        for table in soup.find_all('table'):
            for row in table.find_all('tr')[1:]:
                cells = row.find_all('td')
                if len(cells) >= 4:
                    try:
                        team = cells[0].text.strip()
                        points = int(cells[3].text.strip())
                        standings.append({'team': team, 'points': points})
                    except (ValueError, AttributeError):
                        continue
        return save_data('mls', {'standings': standings})
    except Exception as e:
        print(f"  ✗ MLS scrape failed: {e}")
        return None


def scrape_stock():
    """
    Stock prices via Yahoo Finance API (unofficial JSON endpoint).
    Computes YTD % change, handling L/S directions.
    """
    from draft_picks_2026 import DRAFT_PICKS_2026

    picks = DRAFT_PICKS_2026['Stock']
    tickers = list(set(info['ticker'] for info in picks.values()))
    prices = []

    # Try Yahoo Finance quote API
    for ticker in tickers:
        try:
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=ytd'
            r = requests.get(url, headers=HEADERS, timeout=10)
            data = r.json()
            result = data['chart']['result'][0]
            meta = result['meta']
            current = meta.get('regularMarketPrice') or meta.get('previousClose')

            # Get Jan 1 price (first trading day of year)
            timestamps = result.get('timestamp', [])
            closes = result['indicators']['quote'][0].get('close', [])
            if timestamps and closes:
                jan1_price = next((c for c in closes if c is not None), None)
            else:
                jan1_price = None

            if current and jan1_price:
                prices.append({
                    'ticker': ticker,
                    'current_price': current,
                    'jan1_price': jan1_price,
                    'ytd_pct_raw': round((current / jan1_price - 1) * 100, 2),
                })
            else:
                prices.append({'ticker': ticker, 'current_price': current, 'jan1_price': None})
        except Exception as e:
            print(f"    ✗ {ticker}: {e}")

    return save_data('stock', {'prices': prices})


def scrape_country_gdp():
    """IMF WEO GDP growth rates via API"""
    try:
        from draft_picks_2026 import DRAFT_PICKS_2026
        countries = list(DRAFT_PICKS_2026['Country'].values())

        # IMF WEO API for GDP growth
        imf_url = 'https://www.imf.org/external/datamapper/api/v1/NGDP_RPCH'
        r = requests.get(imf_url, headers=HEADERS, timeout=15)
        data = r.json()

        # IMF uses ISO codes; we need country name → code mapping
        ISO_MAP = {
            'Netherlands': 'NLD', 'United States': 'USA', 'Germany': 'DEU',
            'Guinea': 'GIN', 'South Sudan': 'SSD', 'France': 'FRA',
            'Switzerland': 'CHE', 'Brazil': 'BRA', 'Norway': 'NOR',
            'Guyana': 'GUY', 'Argentina': 'ARG', 'Spain': 'ESP',
            'Canada': 'CAN',
        }

        gdp = []
        values = data.get('values', {}).get('NGDP_RPCH', {})
        for country in countries:
            code = ISO_MAP.get(country)
            if code and code in values:
                growth = values[code].get('2026') or values[code].get('2025')
                if growth:
                    gdp.append({'country': country, 'gdp_growth_pct': float(growth)})

        return save_data('country', {'gdp': gdp})
    except Exception as e:
        print(f"  ✗ Country GDP scrape failed: {e}")
        return None


def scrape_billboard():
    """Billboard Hot 100 - track #1 weeks and Hot 100 weeks per artist"""
    try:
        # Current chart
        url = 'https://www.billboard.com/charts/hot-100/'
        soup = fetch_url(url)

        # Load existing data to accumulate
        existing_path = os.path.join(DATA_DIR, 'musician.json')
        if os.path.exists(existing_path):
            with open(existing_path) as f:
                existing = json.load(f)
            scores_map = {e['artist']: e for e in existing.get('scores', [])}
        else:
            scores_map = {}

        # Parse chart entries
        for li in soup.find_all('li', class_=re.compile('chart-element')):
            rank_el = li.find(class_=re.compile('rank'))
            artist_el = li.find(class_=re.compile('artist'))
            if not rank_el or not artist_el:
                continue
            try:
                rank = int(rank_el.text.strip())
                artist = artist_el.text.strip()
                if artist not in scores_map:
                    scores_map[artist] = {'artist': artist, 'num1_weeks': 0, 'hot100_weeks': 0}
                scores_map[artist]['hot100_weeks'] = scores_map[artist].get('hot100_weeks', 0) + 1
                if rank == 1:
                    scores_map[artist]['num1_weeks'] = scores_map[artist].get('num1_weeks', 0) + 1
            except (ValueError, AttributeError):
                continue

        return save_data('musician', {'scores': list(scores_map.values())})
    except Exception as e:
        print(f"  ✗ Billboard scrape failed: {e}")
        return None


# ─── REFRESH ALL ─────────────────────────────────────────────────────────────

def refresh_all():
    """Run all scrapers. Returns summary."""
    if not SCRAPING_AVAILABLE:
        return {'error': 'requests/beautifulsoup not installed'}

    print("\n🔄 Fantasy Life 2026 — Refreshing all data...\n")
    results = {}

    scrapers = [
        ('NFL', scrape_nfl),
        ('NBA', scrape_nba),
        ('MLB', scrape_mlb),
        ('NHL', scrape_nhl),
        ('NCAAF', scrape_ncaaf),
        ('NCAAB', scrape_ncaab),
        ('Tennis', scrape_tennis),
        ('Golf', scrape_golf),
        ('NASCAR', scrape_nascar),
        ('MLS', scrape_mls),
        ('Stock', scrape_stock),
        ('Country', scrape_country_gdp),
        ('Musician', scrape_billboard),
    ]

    for name, fn in scrapers:
        print(f"Scraping {name}...")
        result = fn()
        results[name] = 'ok' if result else 'failed'

    print("\n✅ Refresh complete!")
    return results


def seed_demo_data():
    """
    Seed realistic demo data so the site works out of the box
    without running scrapers. Based on early-2026 standings.
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    # NFL — early 2025 season results (placeholder 2026 projections)
    save_data('nfl', {'standings': [
        {'team': 'Kansas City Chiefs', 'win_pct': 0.812},
        {'team': 'Philadelphia Eagles', 'win_pct': 0.750},
        {'team': 'Detroit Lions', 'win_pct': 0.750},
        {'team': 'Baltimore Ravens', 'win_pct': 0.688},
        {'team': 'Buffalo Bills', 'win_pct': 0.688},
        {'team': 'Green Bay Packers', 'win_pct': 0.625},
        {'team': 'San Francisco 49ers', 'win_pct': 0.563},
        {'team': 'Tampa Bay Buccaneers', 'win_pct': 0.500},
        {'team': 'Los Angeles Rams', 'win_pct': 0.500},
        {'team': 'Seattle Seahawks', 'win_pct': 0.438},
        {'team': 'Indianapolis Colts', 'win_pct': 0.375},
        {'team': 'Denver Broncos', 'win_pct': 0.313},
        {'team': 'New England Patriots', 'win_pct': 0.125},
    ]})

    save_data('nba', {'standings': [
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

    save_data('mlb', {'standings': [
        {'team': 'Los Angeles Dodgers', 'win_pct': 0.642},
        {'team': 'New York Yankees', 'win_pct': 0.611},
        {'team': 'Atlanta Braves', 'win_pct': 0.580},
        {'team': 'Philadelphia Phillies', 'win_pct': 0.568},
        {'team': 'New York Mets', 'win_pct': 0.549},
        {'team': 'Houston Astros', 'win_pct': 0.543},
        {'team': 'San Diego Padres', 'win_pct': 0.531},
        {'team': 'Cleveland Guardians', 'win_pct': 0.519},
        {'team': 'Toronto Blue Jays', 'win_pct': 0.506},
        {'team': 'Milwaukee Brewers', 'win_pct': 0.494},
        {'team': 'Chicago Cubs', 'win_pct': 0.469},
        {'team': 'Texas Rangers', 'win_pct': 0.432},
        {'team': 'Seattle Mariners', 'win_pct': 0.395},
    ]})

    save_data('nhl', {'standings': [
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

    save_data('ncaaf', {'poll': [
        {'rank': 1, 'team': 'Ohio State'},
        {'rank': 2, 'team': 'Georgia'},
        {'rank': 3, 'team': 'Oregon'},
        {'rank': 4, 'team': 'Michigan'},
        {'rank': 5, 'team': 'Notre Dame'},
        {'rank': 6, 'team': 'Alabama'},
        {'rank': 7, 'team': 'Ole Miss'},
        {'rank': 8, 'team': 'Texas A&M'},
        {'rank': 9, 'team': 'Indiana'},
        {'rank': 11, 'team': 'BYU'},
        {'rank': 14, 'team': 'Miami'},
        {'rank': 17, 'team': 'Georgia Tech'},
        {'rank': 22, 'team': 'Texas Tech'},
    ]})

    save_data('ncaab', {'poll': [
        {'rank': 1, 'team': 'Duke'},
        {'rank': 2, 'team': 'Kansas'},
        {'rank': 3, 'team': 'Houston'},
        {'rank': 4, 'team': 'Florida'},
        {'rank': 5, 'team': 'Kentucky'},
        {'rank': 6, 'team': 'Alabama'},
        {'rank': 7, 'team': 'Purdue'},
        {'rank': 8, 'team': 'North Carolina'},
        {'rank': 9, 'team': 'UConn'},
        {'rank': 11, 'team': "St. John's"},
        {'rank': 13, 'team': 'UCLA'},
        {'rank': 18, 'team': 'Louisville'},
        {'rank': 22, 'team': 'Michigan'},
    ]})

    save_data('tennis', {'rankings': [
        {'player': 'Jannik Sinner', 'rank': 1, 'tour': 'ATP'},
        {'player': 'Carlos Alcaraz', 'rank': 2, 'tour': 'ATP'},
        {'player': 'Alexander Zverev', 'rank': 3, 'tour': 'ATP'},
        {'player': 'Taylor Fritz', 'rank': 4, 'tour': 'ATP'},
        {'player': 'Novak Djokovic', 'rank': 7, 'tour': 'ATP'},
        {'player': 'Daniil Medvedev', 'rank': 5, 'tour': 'ATP'},
        {'player': 'Aryna Sabalenka', 'rank': 1, 'tour': 'WTA'},
        {'player': 'Iga Swiatek', 'rank': 2, 'tour': 'WTA'},
        {'player': 'Coco Gauff', 'rank': 3, 'tour': 'WTA'},
        {'player': 'Jessica Pegula', 'rank': 4, 'tour': 'WTA'},
        {'player': 'Madison Keys', 'rank': 7, 'tour': 'WTA'},
        {'player': 'Jasmine Paolini', 'rank': 5, 'tour': 'WTA'},
        {'player': 'Amanda Anisimova', 'rank': 18, 'tour': 'WTA'},
    ]})

    save_data('golf', {'rankings': [
        {'player': 'Scottie Scheffler', 'rank': 1},
        {'player': 'Rory McIlroy', 'rank': 2},
        {'player': 'Xander Schauffele', 'rank': 3},
        {'player': 'Collin Morikawa', 'rank': 4},
        {'player': 'Ludvig Aberg', 'rank': 5},
        {'player': 'Bryson DeChambeau', 'rank': 6},
        {'player': 'Tommy Fleetwood', 'rank': 7},
        {'player': 'Viktor Hovland', 'rank': 8},
        {'player': 'Jon Rahm', 'rank': 9},
        {'player': 'Patrick Cantlay', 'rank': 12},
        {'player': 'Justin Thomas', 'rank': 15},
        {'player': 'Russell Henley', 'rank': 22},
        {'player': 'J.J. Spaun', 'rank': 45},
    ]})

    save_data('nascar', {'standings': [
        {'driver': 'Kyle Larson', 'points': 782},
        {'driver': 'Christopher Bell', 'points': 750},
        {'driver': 'William Byron', 'points': 731},
        {'driver': 'Denny Hamlin', 'points': 718},
        {'driver': 'Chase Elliott', 'points': 705},
        {'driver': 'Ryan Blaney', 'points': 698},
        {'driver': 'Tyler Reddick', 'points': 682},
        {'driver': 'Ross Chastain', 'points': 655},
        {'driver': 'Joey Logano', 'points': 641},
        {'driver': 'Daniel Suarez', 'points': 598},
        {'driver': 'Chase Briscoe', 'points': 572},
        {'driver': 'Shane van Gisbergen', 'points': 543},
        {'driver': 'Bubba Wallace', 'points': 490},
    ]})

    save_data('mls', {'standings': [
        {'team': 'LA Galaxy', 'points': 68},
        {'team': 'LAFC', 'points': 62},
        {'team': 'FC Cincinnati', 'points': 60},
        {'team': 'Columbus Crew', 'points': 58},
        {'team': 'Inter Miami', 'points': 55},
        {'team': 'Seattle Sounders', 'points': 52},
        {'team': 'Philadelphia Union', 'points': 50},
        {'team': 'Orlando City', 'points': 47},
        {'team': 'New York Red Bulls', 'points': 45},
        {'team': 'Vancouver Whitecaps', 'points': 42},
        {'team': 'Minnesota United', 'points': 38},
        {'team': 'San Diego FC', 'points': 30},
        {'team': 'Charlotte FC', 'points': 22},
    ]})

    save_data('actor', {'scores': [
        {'name': 'Timothee Chalamet', 'composite_score': 412.5},
        {'name': 'Pedro Pascal', 'composite_score': 387.2},
        {'name': 'Tom Holland', 'composite_score': 356.8},
        {'name': 'Dwayne Johnson', 'composite_score': 298.5},
        {'name': 'Chris Hemsworth', 'composite_score': 276.3},
        {'name': 'Robert Pattinson', 'composite_score': 241.7},
        {'name': 'Matt Damon', 'composite_score': 198.4},
        {'name': 'Leonardo DiCaprio', 'composite_score': 187.6},
        {'name': 'Jeremy Allen White', 'composite_score': 143.2},
        {'name': 'Jon Bernthal', 'composite_score': 118.9},
        {'name': 'George Clooney', 'composite_score': 95.4},
        {'name': 'Wagner Moura', 'composite_score': 72.1},
        {'name': 'Sean Penn', 'composite_score': 48.3},
    ]})

    save_data('actress', {'scores': [
        {'name': 'Zendaya', 'composite_score': 445.2},
        {'name': 'Emma Stone', 'composite_score': 398.7},
        {'name': 'Sydney Sweeney', 'composite_score': 354.1},
        {'name': 'Anya Taylor-Joy', 'composite_score': 312.5},
        {'name': 'Florence Pugh', 'composite_score': 287.3},
        {'name': 'Cynthia Erivo', 'composite_score': 245.8},
        {'name': 'Anne Hathaway', 'composite_score': 198.2},
        {'name': 'Ariana Grande', 'composite_score': 176.4},
        {'name': 'Charlize Theron', 'composite_score': 134.7},
        {'name': 'Teyana Taylor', 'composite_score': 98.3},
        {'name': 'Tessa Thompson', 'composite_score': 76.5},
        {'name': 'Jessie Buckley', 'composite_score': 54.2},
        {'name': 'Amanda Seyfried', 'composite_score': 42.8},
    ]})

    save_data('musician', {'scores': [
        {'artist': 'Kendrick Lamar', 'num1_weeks': 8, 'hot100_weeks': 24},
        {'artist': 'Beyonce', 'num1_weeks': 6, 'hot100_weeks': 20},
        {'artist': 'Taylor Swift', 'num1_weeks': 5, 'hot100_weeks': 22},
        {'artist': 'Bad Bunny', 'num1_weeks': 4, 'hot100_weeks': 18},
        {'artist': 'Sabrina Carpenter', 'num1_weeks': 3, 'hot100_weeks': 16},
        {'artist': 'SZA', 'num1_weeks': 2, 'hot100_weeks': 15},
        {'artist': 'Olivia Rodrigo', 'num1_weeks': 2, 'hot100_weeks': 14},
        {'artist': 'The Weeknd', 'num1_weeks': 2, 'hot100_weeks': 13},
        {'artist': 'Lady Gaga', 'num1_weeks': 1, 'hot100_weeks': 12},
        {'artist': 'Drake', 'num1_weeks': 1, 'hot100_weeks': 10},
        {'artist': 'Justin Bieber', 'num1_weeks': 0, 'hot100_weeks': 8},
        {'artist': 'FKA Twigs', 'num1_weeks': 0, 'hot100_weeks': 3},
        {'artist': 'BTS', 'num1_weeks': 0, 'hot100_weeks': 2},
    ]})

    save_data('country', {'gdp': [
        {'country': 'Guyana', 'gdp_growth_pct': 14.2},
        {'country': 'South Sudan', 'gdp_growth_pct': 8.7},
        {'country': 'Guinea', 'gdp_growth_pct': 6.9},
        {'country': 'India', 'gdp_growth_pct': 6.5},  # Not picked but placeholder
        {'country': 'Spain', 'gdp_growth_pct': 3.1},
        {'country': 'Netherlands', 'gdp_growth_pct': 2.8},
        {'country': 'United States', 'gdp_growth_pct': 2.7},
        {'country': 'Brazil', 'gdp_growth_pct': 3.2},
        {'country': 'France', 'gdp_growth_pct': 1.8},
        {'country': 'Canada', 'gdp_growth_pct': 2.1},
        {'country': 'Norway', 'gdp_growth_pct': 2.3},
        {'country': 'Germany', 'gdp_growth_pct': 1.2},
        {'country': 'Switzerland', 'gdp_growth_pct': 1.5},
        {'country': 'Argentina', 'gdp_growth_pct': 4.1},
    ]})

    save_data('stock', {'prices': [
        {'ticker': 'COIN', 'current_price': 312.50, 'jan1_price': 248.75},
        {'ticker': 'LULU', 'current_price': 298.40, 'jan1_price': 342.10},
        {'ticker': 'SOFI', 'current_price': 14.82, 'jan1_price': 10.15},
        {'ticker': 'NVDA', 'current_price': 118.50, 'jan1_price': 134.25},
        {'ticker': 'CVNA', 'current_price': 198.75, 'jan1_price': 225.40},
        {'ticker': 'TSLA', 'current_price': 312.80, 'jan1_price': 403.84},
        {'ticker': 'CMG', 'current_price': 58.20, 'jan1_price': 55.48},
        {'ticker': 'PLTR', 'current_price': 78.45, 'jan1_price': 71.96},
        {'ticker': 'AVGO', 'current_price': 198.30, 'jan1_price': 185.44},
        {'ticker': 'SMCI', 'current_price': 45.20, 'jan1_price': 38.75},
        {'ticker': 'TTWO', 'current_price': 198.75, 'jan1_price': 176.25},
        {'ticker': 'INTC', 'current_price': 22.50, 'jan1_price': 20.15},
        {'ticker': 'NEE', 'current_price': 68.90, 'jan1_price': 72.35},
    ]})

    # Empty bonuses file
    bonuses_path = os.path.join(DATA_DIR, 'bonuses.json')
    if not os.path.exists(bonuses_path):
        with open(bonuses_path, 'w') as f:
            json.dump({}, f, indent=2)

    print("✅ Demo data seeded successfully!")


if __name__ == '__main__':
    seed_demo_data()
