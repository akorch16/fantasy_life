"""
Fantasy Life 2026 — Scoring Engine
Handles baseline (rotisserie) + bonus point computation.
Reads all data from Supabase via db.py instead of local JSON files.
"""

import os
from datetime import datetime

from draft_picks_2026 import DRAFT_PICKS_2026, PLAYERS, TENNIS_GENDER
from db import get_standing, get_all_standings, get_all_bonuses

# Bonus points per Amendment 7.14 (13-member inflation)
BONUS_POINTS = {
    'sports_championship': {
        'champion': 13, 'runner_up': 9, 'semi': 6.5, 'quarter': 4, 'round16': 2.5,
    },
    'tennis': {
        'major_win_men': 4, 'major_runnerup_men': 2.5,
        'major_win_women': 4,  # disputed — Amendment 7.20
        'major_runnerup_women': 2.5,
    },
    'golf':   {'major_win': 6, 'major_runnerup': 2.5},
    'oscar':  {'lead_win': 13, 'supporting_win': 9, 'lead_nom': 4, 'supporting_nom': 2.5},
    'grammy': {'best_song_album_record': 7, 'other_win': 3, 'nomination': 1, 'cap': 13},
    'country': {1: 13, 2: 9, 3: 6.5, 4: 4, 5: 2.5},
    'nascar':  {1: 13, 2: 9, 3: 6.5, 4: 4, 5: 2.5},
}


# ── Data loading ──────────────────────────────────────────────────────────────

_KEY_MAP = {
    'nfl': 'NFL', 'nba': 'NBA', 'mlb': 'MLB', 'nhl': 'NHL',
    'ncaaf': 'NCAAF', 'ncaab': 'NCAAB', 'tennis': 'Tennis',
    'golf': 'Golf', 'nascar': 'NASCAR', 'mls': 'MLS',
    'actor': 'Actor', 'actress': 'Actress', 'musician': 'Musician',
    'country': 'Country', 'stock': 'Stock',
}

# Populated at the start of compute_all_scores() to avoid 15 round-trips
_bulk_standings: dict = {}

def load_data(category_key):
    """Load category data from Supabase, falling back to local data/ JSON files."""
    import json as _json
    key = _KEY_MAP.get(category_key.lower(), category_key)
    supabase_data = None
    if _bulk_standings:
        supabase_data = _bulk_standings.get(key) or None
    else:
        supabase_data = get_standing(key) or None

    # If Supabase returned nothing, use local file entirely
    if not supabase_data:
        local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', f'{category_key.lower()}.json')
        if os.path.exists(local_path):
            try:
                with open(local_path) as f:
                    supabase_data = _json.load(f)
                print(f'  ⚠ {key}: using local fallback file (Supabase empty)')
            except Exception:
                pass
        return supabase_data

    return supabase_data


# Bonuses that can't yet be entered via admin panel — merged on top of Supabase
HARDCODED_BONUSES = {
    'Tennis': {
        'Todd':  4.0,   # Alcaraz — 2026 Australian Open champion
        'Shep':  2.5,   # Djokovic — 2026 Australian Open runner-up
        'Fryar': 2.5,   # Sabalenka — 2026 Australian Open women's runner-up
    },
    'Actress': {
        'Jamzee': 4.0,   # Emma Stone — Best Actress nomination (Bugonia, 98th Oscars)
        'Theo':  -4.0,   # Correction: Sydney Sweeney was NOT nominated (Supabase had wrong 4.0)
    },
    'NCAAF': {
        'Fryar': 2.5,  # Texas A&M — made CFP playoff (Round of 16 exit)
    },
    'Musician': {
        # Supabase already has partial bonuses; these values offset to reach the correct totals:
        # target total = Supabase existing + hardcoded adjustment
        'Fryar':  1.0,   # Justin Bieber:      Supabase=3  + 1  = 4 total
        'Korch':  2.0,   # SZA:                Supabase=11 + 2  = 13 total
        'Wu':    -1.0,   # FKA Twigs:          Supabase=4  + -1 = 3 total
        'Jens':   3.0,   # Sabrina Carpenter:  Supabase=3  + 3  = 6 total
    },
    'NCAAB': {
        'Tim':     2.5,  # St. John's — eliminated Sweet 16
        'Jens':    4.0,  # Duke — Elite 8 (beat St. John's 80-75)
        'Mitchell':2.5,  # Alabama — eliminated Sweet 16
        'Theo':    2.5,  # Houston — eliminated Sweet 16
        'Fryar':   9.0,  # UConn — National Championship game
        'Korch':   4.0,  # Purdue — Elite 8 (beat Arizona Mar 28)
        'Jamzee': 13.0,  # Michigan — National Champions 🏆
    },
    'Golf': {
        'Molmen': 6.0,  # McIlroy — 2026 Masters champion (back-to-back)
        'Wu':     2.5,  # Scheffler — 2026 Masters runner-up
    },
    'NBA': {
        # 2.5 pts each for teams that made the 2026 playoffs (not play-in losers)
        # Warriors (Mitchell), Clippers (Fryar), Bucks (Molmen) did NOT make playoffs
        'Tim':    2.5,  # Denver Nuggets
        'Wu':     2.5,  # San Antonio Spurs
        'Jens':   2.5,  # Cleveland Cavaliers
        'Todd':   2.5,  # Minnesota Timberwolves
        'Shep':   2.5,  # Boston Celtics
        'Theo':   2.5,  # Los Angeles Lakers
        'Feder':  2.5,  # Oklahoma City Thunder
        'Korch':  2.5,  # Houston Rockets
        'Jamzee': 2.5,  # Orlando Magic (won play-in)
        'Buckley':2.5,  # New York Knicks
    },
}

def load_bonuses():
    """Load bonus points from Supabase, merged with hardcoded bonuses."""
    bonuses = get_all_bonuses()
    for cat, players in HARDCODED_BONUSES.items():
        if cat not in bonuses:
            bonuses[cat] = {}
        for player, pts in players.items():
            existing = bonuses[cat].get(player, 0)
            bonuses[cat][player] = round(existing + pts, 2)
    return bonuses


def get_last_updated():
    """Get the most recent updated_at timestamp from Supabase standings."""
    try:
        import requests as req
        SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
        SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')
        r = req.get(
            f'{SUPABASE_URL}/rest/v1/standings',
            headers={'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}'},
            params={'select': 'updated_at', 'order': 'updated_at.desc', 'limit': '1'},
            timeout=10,
        )
        rows = r.json()
        if rows:
            ts = rows[0]['updated_at']
            # Parse ISO timestamp
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            return dt.strftime('%Y-%m-%d %H:%M UTC')
    except Exception:
        pass
    return None


# ── Ranking helpers ───────────────────────────────────────────────────────────

def rank_avg(values, reverse=True):
    """
    RANK.AVG style ranks.
    values: dict of {name: numeric_value}
    reverse=True means higher value = better (rank 1)
    Returns dict of {name: rank_float}
    """
    sorted_vals = sorted(values.items(), key=lambda x: x[1], reverse=reverse)
    ranks = {}
    i = 0
    while i < len(sorted_vals):
        j = i
        while j < len(sorted_vals) - 1 and sorted_vals[j][1] == sorted_vals[j+1][1]:
            j += 1
        avg_rank = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[sorted_vals[k][0]] = avg_rank
        i = j + 1
    return ranks


def rank_to_points(rank, n=13):
    """Rank 1 = 13 pts, Rank 13 = 1 pt."""
    return max(0, n - rank + 1)


# ── Static data (frozen seasons) ──────────────────────────────────────────────

# 2025 NFL regular season final standings
NFL_2025_STANDINGS = {"standings": [
    {"team": "New England Patriots",  "wins": 14, "losses": 3,  "win_pct": 0.824},
    {"team": "Buffalo Bills",         "wins": 12, "losses": 5,  "win_pct": 0.706},
    {"team": "Miami Dolphins",        "wins": 7,  "losses": 10, "win_pct": 0.412},
    {"team": "New York Jets",         "wins": 3,  "losses": 14, "win_pct": 0.176},
    {"team": "Pittsburgh Steelers",   "wins": 10, "losses": 7,  "win_pct": 0.588},
    {"team": "Baltimore Ravens",      "wins": 8,  "losses": 9,  "win_pct": 0.471},
    {"team": "Cincinnati Bengals",    "wins": 6,  "losses": 11, "win_pct": 0.353},
    {"team": "Cleveland Browns",      "wins": 5,  "losses": 12, "win_pct": 0.294},
    {"team": "Jacksonville Jaguars",  "wins": 13, "losses": 4,  "win_pct": 0.765},
    {"team": "Houston Texans",        "wins": 12, "losses": 5,  "win_pct": 0.706},
    {"team": "Indianapolis Colts",    "wins": 8,  "losses": 9,  "win_pct": 0.471},
    {"team": "Tennessee Titans",      "wins": 3,  "losses": 14, "win_pct": 0.176},
    {"team": "Denver Broncos",        "wins": 14, "losses": 3,  "win_pct": 0.824},
    {"team": "Los Angeles Chargers",  "wins": 11, "losses": 6,  "win_pct": 0.647},
    {"team": "Kansas City Chiefs",    "wins": 6,  "losses": 11, "win_pct": 0.353},
    {"team": "Las Vegas Raiders",     "wins": 3,  "losses": 14, "win_pct": 0.176},
    {"team": "Philadelphia Eagles",   "wins": 11, "losses": 6,  "win_pct": 0.647},
    {"team": "Dallas Cowboys",        "wins": 7,  "losses": 9,  "win_pct": 0.441},
    {"team": "Washington Commanders", "wins": 5,  "losses": 12, "win_pct": 0.294},
    {"team": "New York Giants",       "wins": 4,  "losses": 13, "win_pct": 0.235},
    {"team": "Chicago Bears",         "wins": 11, "losses": 6,  "win_pct": 0.647},
    {"team": "Green Bay Packers",     "wins": 9,  "losses": 7,  "win_pct": 0.559},
    {"team": "Minnesota Vikings",     "wins": 9,  "losses": 8,  "win_pct": 0.529},
    {"team": "Detroit Lions",         "wins": 9,  "losses": 8,  "win_pct": 0.529},
    {"team": "Carolina Panthers",     "wins": 8,  "losses": 9,  "win_pct": 0.471},
    {"team": "Tampa Bay Buccaneers",  "wins": 8,  "losses": 9,  "win_pct": 0.471},
    {"team": "Atlanta Falcons",       "wins": 8,  "losses": 9,  "win_pct": 0.471},
    {"team": "New Orleans Saints",    "wins": 6,  "losses": 11, "win_pct": 0.353},
    {"team": "Seattle Seahawks",      "wins": 14, "losses": 3,  "win_pct": 0.824},
    {"team": "Los Angeles Rams",      "wins": 12, "losses": 5,  "win_pct": 0.706},
    {"team": "San Francisco 49ers",   "wins": 12, "losses": 5,  "win_pct": 0.706},
    {"team": "Arizona Cardinals",     "wins": 3,  "losses": 14, "win_pct": 0.176},
]}

# 2026 MLS standings — week of Apr 5, 2026 (~6 games played). Locked because ESPN scraper returns stale data.
MLS_2026_STANDINGS = {"standings": [
    {"team": "LAFC",                   "points": 16},
    {"team": "Vancouver Whitecaps",    "points": 15},
    {"team": "San Jose Earthquakes",   "points": 15},
    {"team": "Real Salt Lake",         "points": 13},
    {"team": "Seattle Sounders",       "points": 13},
    {"team": "Nashville SC",           "points": 13},
    {"team": "FC Dallas",              "points": 11},
    {"team": "San Diego FC",           "points": 11},
    {"team": "New York City FC",       "points": 11},
    {"team": "Charlotte FC",           "points": 11},
    {"team": "Inter Miami",            "points": 11},
    {"team": "Chicago Fire",           "points": 10},
    {"team": "Toronto FC",             "points": 10},
    {"team": "New York Red Bulls",     "points": 10},
    {"team": "Colorado Rapids",        "points": 9},
    {"team": "Minnesota United",       "points": 8},
    {"team": "DC United",              "points": 7},
    {"team": "Houston Dynamo",         "points": 6},
    {"team": "Austin FC",              "points": 6},
    {"team": "New England Revolution", "points": 6},
    {"team": "FC Cincinnati",          "points": 6},
    {"team": "LA Galaxy",              "points": 5},
    {"team": "St. Louis City",         "points": 5},
    {"team": "Columbus Crew",          "points": 5},
    {"team": "Portland Timbers",       "points": 4},
    {"team": "Sporting Kansas City",   "points": 4},
    {"team": "Atlanta United",         "points": 4},
    {"team": "CF Montreal",            "points": 3},
    {"team": "Orlando City",           "points": 3},
    {"team": "Philadelphia Union",     "points": 0},
]}

# 2025 NCAAF CFP Committee Final Rankings (Dec 7, 2025) — the last rankings BEFORE the CFP playoff
# Used for roto scoring per rules: standings locked at week before college playoffs begin
NCAAF_2025_POLL = {"poll": [
    {"rank": 1,  "team": "Indiana Hoosiers",           "short": "Indiana",      "location": "Indiana"},
    {"rank": 2,  "team": "Ohio State Buckeyes",         "short": "Ohio State",   "location": "Ohio State"},
    {"rank": 3,  "team": "Georgia Bulldogs",            "short": "Georgia Bulldogs","location": "Georgia Bulldogs"},
    {"rank": 4,  "team": "Texas Tech Red Raiders",      "short": "Texas Tech",   "location": "Texas Tech"},
    {"rank": 5,  "team": "Oregon Ducks",                "short": "Oregon",       "location": "Oregon"},
    {"rank": 6,  "team": "Mississippi Rebels",          "short": "Ole Miss",     "location": "Mississippi"},
    {"rank": 7,  "team": "Texas A&M Aggies",            "short": "Texas A&M",    "location": "Texas A&M"},
    {"rank": 8,  "team": "Oklahoma Sooners",            "short": "Oklahoma",     "location": "Oklahoma"},
    {"rank": 9,  "team": "Alabama Crimson Tide",        "short": "Alabama",      "location": "Alabama"},
    {"rank": 10, "team": "Miami Hurricanes",            "short": "Miami",        "location": "Miami"},
    {"rank": 11, "team": "Notre Dame Fighting Irish",   "short": "Notre Dame",   "location": "Notre Dame"},
    {"rank": 12, "team": "BYU Cougars",                 "short": "BYU",          "location": "BYU"},
    {"rank": 13, "team": "Texas Longhorns",             "short": "Texas",        "location": "Texas"},
    {"rank": 14, "team": "Vanderbilt Commodores",       "short": "Vanderbilt",   "location": "Vanderbilt"},
    {"rank": 15, "team": "Utah Utes",                   "short": "Utah",         "location": "Utah"},
    {"rank": 16, "team": "USC Trojans",                 "short": "USC",          "location": "Southern California"},
    {"rank": 17, "team": "Arizona Wildcats",            "short": "Arizona",      "location": "Arizona"},
    {"rank": 18, "team": "Michigan Wolverines",         "short": "Michigan",     "location": "Michigan"},
    {"rank": 19, "team": "Virginia Cavaliers",          "short": "Virginia",     "location": "Virginia"},
    {"rank": 20, "team": "Tulane Green Wave",           "short": "Tulane",       "location": "Tulane"},
    {"rank": 21, "team": "Houston Cougars",             "short": "Houston",      "location": "Houston"},
    {"rank": 22, "team": "Georgia Tech Yellow Jackets", "short": "Georgia Tech", "location": "Georgia Tech"},
    {"rank": 23, "team": "Iowa Hawkeyes",               "short": "Iowa",         "location": "Iowa"},
    {"rank": 24, "team": "James Madison Dukes",         "short": "James Madison","location": "James Madison"},
    {"rank": 25, "team": "North Texas Mean Green",      "short": "North Texas",  "location": "North Texas"},
]}

# 2026 NCAAB AP Poll — Week 18 (through Mar 15, 2026), last poll before NCAA Tournament
# Used for roto scoring per rules: standings locked at week before college playoffs begin
NCAAB_2026_PRE_TOURNAMENT_POLL = {"poll": [
    {"rank": 1,  "team": "Duke Blue Devils",            "short": "Duke",         "location": "Duke"},
    {"rank": 2,  "team": "Arizona Wildcats",            "short": "Arizona",      "location": "Arizona"},
    {"rank": 3,  "team": "Michigan Wolverines",         "short": "Michigan",     "location": "Michigan"},
    {"rank": 4,  "team": "Florida Gators",              "short": "Florida",      "location": "Florida"},
    {"rank": 5,  "team": "Houston Cougars",             "short": "Houston",      "location": "Houston"},
    {"rank": 6,  "team": "Iowa State Cyclones",         "short": "Iowa State",   "location": "Iowa State"},
    {"rank": 7,  "team": "UConn Huskies",               "short": "UConn",        "location": "Connecticut"},
    {"rank": 8,  "team": "Purdue Boilermakers",         "short": "Purdue",       "location": "Purdue"},
    {"rank": 9,  "team": "Virginia Cavaliers",          "short": "Virginia",     "location": "Virginia"},
    {"rank": 10, "team": "St. John's Red Storm",        "short": "St. John's",   "location": "St. John's"},
    {"rank": 11, "team": "Michigan State Spartans",     "short": "Michigan State","location": "Michigan State"},
    {"rank": 12, "team": "Gonzaga Bulldogs",            "short": "Gonzaga",      "location": "Gonzaga"},
    {"rank": 13, "team": "Illinois Fighting Illini",    "short": "Illinois",     "location": "Illinois"},
    {"rank": 14, "team": "Arkansas Razorbacks",         "short": "Arkansas",     "location": "Arkansas"},
    {"rank": 15, "team": "Nebraska Cornhuskers",        "short": "Nebraska",     "location": "Nebraska"},
    {"rank": 16, "team": "Vanderbilt Commodores",       "short": "Vanderbilt",   "location": "Vanderbilt"},
    {"rank": 17, "team": "Kansas Jayhawks",             "short": "Kansas",       "location": "Kansas"},
    {"rank": 18, "team": "Alabama Crimson Tide",        "short": "Alabama",      "location": "Alabama"},
    {"rank": 19, "team": "Wisconsin Badgers",           "short": "Wisconsin",    "location": "Wisconsin"},
    {"rank": 20, "team": "Texas Tech Red Raiders",      "short": "Texas Tech",   "location": "Texas Tech"},
    {"rank": 21, "team": "North Carolina Tar Heels",    "short": "North Carolina","location": "North Carolina"},
    {"rank": 22, "team": "Saint Mary's Gaels",          "short": "Saint Mary's", "location": "Saint Mary's"},
    {"rank": 23, "team": "Louisville Cardinals",        "short": "Louisville",   "location": "Louisville"},
    {"rank": 24, "team": "Tennessee Volunteers",        "short": "Tennessee",    "location": "Tennessee"},
    {"rank": 25, "team": "Miami Hurricanes",            "short": "Miami",        "location": "Miami"},
]}


# 2026 NCAAB bracket bonus — awarded for correct bracket prediction (championship winner)
NCAAB_BRACKET_BONUS = {
    'Wu':    2.5,  # Bracket win
    'Korch': 2.5,  # Bracket win
}

# ── Baseline scorers ──────────────────────────────────────────────────────────

def compute_baseline_sports(category, data_key, value_key, reverse=True, static_data=None):
    picks = DRAFT_PICKS_2026.get(category, {})
    data = static_data or load_data(data_key)

    raw_values = {}
    for player, team in picks.items():
        raw = None
        if data:
            for entry in data.get('standings', []):
                if team_matches(team, entry.get('team', '')):
                    raw = entry.get(value_key)
                    break
        raw_values[player] = raw if raw is not None else -1

    valid = {p: (v if v >= 0 else 0) for p, v in raw_values.items()}
    ranks = rank_avg(valid, reverse=reverse)

    result = {}
    for player, team in picks.items():
        raw = raw_values[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        result[player] = {
            'pick': team, 'raw_value': raw if raw >= 0 else None,
            'rank': rank, 'baseline_pts': pts, 'bonus_pts': 0,
        }
    return result

def compute_baseline_poll(category, data_key, reverse=False, static_data=None):
    picks = DRAFT_PICKS_2026.get(category, {})
    data = static_data or load_data(data_key)

    raw_values = {}
    for player, team in picks.items():
        raw = None
        if data:
            for entry in data.get('poll', []):
                entry_team = entry.get('team', '')
                entry_short = entry.get('short', '')
                entry_location = entry.get('location', '')
                if (team_matches(team, entry_team) or
                    team_matches(team, entry_short) or
                    team_matches(team, entry_location)):
                    raw = entry.get('rank')
                    break
        raw_values[player] = raw if raw is not None else 26

    ranks = rank_avg(raw_values, reverse=False)

    result = {}
    for player, team in picks.items():
        raw = raw_values[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        result[player] = {
            'pick': team, 'raw_value': raw if raw != 26 else None,
            'rank': rank, 'baseline_pts': pts, 'bonus_pts': 0,
        }
    return result


def compute_baseline_tennis():
    picks = DRAFT_PICKS_2026.get('Tennis', {})
    data = load_data('tennis')

    adjusted = {}
    for player, name in picks.items():
        raw = None
        gender = TENNIS_GENDER.get(name, 'M')
        if data:
            for entry in data.get('rankings', []):
                if name_matches(name, entry.get('player', '')):
                    raw = entry.get('rank')
                    break
        raw = raw if raw is not None else 999
        adjusted[player] = raw + 0.5 if gender == 'F' else float(raw)

    ranks = rank_avg(adjusted, reverse=False)

    result = {}
    for player, name in picks.items():
        raw_adj = adjusted[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        result[player] = {
            'pick': name, 'raw_value': raw_adj if raw_adj < 900 else None,
            'rank': rank, 'baseline_pts': pts, 'bonus_pts': 0,
            'gender': TENNIS_GENDER.get(name, 'M'),
        }
    return result


def fetch_owgr_live():
    """Scrape current OWGR rankings from owgr.com. Returns {rankings:[{player,rank}]} or None."""
    try:
        from bs4 import BeautifulSoup
        url = 'https://www.owgr.com/ranking?pageNo=1&pageSize=200&country=All'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml',
        }
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        table = soup.find('table')
        if not table:
            print('  ✗ OWGR: no table found')
            return None

        # Identify which column indices hold rank and name
        headers_row = table.find('thead')
        col_rank, col_name = 0, 2  # sensible defaults
        if headers_row:
            ths = [th.get_text(strip=True).lower() for th in headers_row.find_all('th')]
            for i, h in enumerate(ths):
                if 'this week' in h or h == 'pos':
                    col_rank = i
                if h == 'name' or 'player' in h:
                    col_name = i

        tbody = table.find('tbody') or table
        rankings = []
        for row in tbody.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) <= max(col_rank, col_name):
                continue
            try:
                rank = int(cells[col_rank].get_text(strip=True).lstrip('=').strip())
                name = cells[col_name].get_text(strip=True)
                if name and rank:
                    rankings.append({'player': name, 'rank': rank})
            except (ValueError, IndexError):
                continue

        if len(rankings) >= 10:
            print(f'  ✓ OWGR live: {len(rankings)} players fetched')
            return {'rankings': rankings}
        print(f'  ✗ OWGR: too few rows ({len(rankings)})')
        return None
    except Exception as e:
        print(f'  ✗ OWGR live fetch failed: {e}')
        return None


def fetch_nascar_espn_live():
    """Fetch NASCAR Cup standings from ESPN public API. Returns {standings:[{driver,points}]} or None."""
    try:
        url = 'https://site.api.espn.com/apis/site/v2/sports/racing/nascar-premier/standings'
        resp = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        resp.raise_for_status()
        data = resp.json()

        entries = []
        for child in data.get('children', []):
            child_entries = child.get('standings', {}).get('entries', [])
            if not child_entries:
                continue
            for entry in child_entries:
                name = entry.get('athlete', {}).get('displayName', '')
                pts = None
                for stat in entry.get('stats', []):
                    if stat.get('name') == 'points':
                        try:
                            pts = int(float(stat.get('value', 0)))
                        except (TypeError, ValueError):
                            pass
                        break
                if name and pts is not None:
                    entries.append({'driver': name, 'points': pts})
            if entries:
                break  # first child with entries is driver standings

        if len(entries) >= 5:
            standings = sorted(entries, key=lambda x: -x['points'])
            print(f'  ✓ NASCAR ESPN live: {len(standings)} drivers fetched')
            return {'standings': standings}
        print(f'  ✗ NASCAR ESPN: too few entries ({len(entries)})')
        return None
    except Exception as e:
        print(f'  ✗ NASCAR ESPN live fetch failed: {e}')
        return None


# OWGR static fallback (post-Masters April 2026)
GOLF_2026_OWGR_STATIC = {"rankings": [
    {"player": "Scottie Scheffler",   "rank": 1},
    {"player": "Rory McIlroy",        "rank": 2},
    {"player": "Cameron Young",       "rank": 3},
    {"player": "Tommy Fleetwood",     "rank": 4},
    {"player": "Justin Rose",         "rank": 5},
    {"player": "Collin Morikawa",     "rank": 6},
    {"player": "Xander Schauffele",   "rank": 7},
    {"player": "Russell Henley",      "rank": 8},
    {"player": "J.J. Spaun",          "rank": 11},
    {"player": "Justin Thomas",       "rank": 13},
    {"player": "Ludvig Aberg",        "rank": 14},
    {"player": "Viktor Hovland",      "rank": 16},
    {"player": "Bryson DeChambeau",   "rank": 24},
    {"player": "Patrick Cantlay",     "rank": 34},
    {"player": "Jon Rahm",            "rank": 36},
]}

def compute_baseline_golf():
    picks = DRAFT_PICKS_2026.get('Golf', {})
    _d = load_data('golf')
    if _d and _d.get('rankings'):
        data = _d
    else:
        data = fetch_owgr_live() or GOLF_2026_OWGR_STATIC

    raw_values = {}
    for player, name in picks.items():
        raw = None
        if data:
            for entry in data.get('rankings', []):
                if name_matches(name, entry.get('player', '')):
                    raw = entry.get('rank')
                    break
        raw_values[player] = raw if raw is not None else 999

    ranks = rank_avg(raw_values, reverse=False)

    result = {}
    for player, name in picks.items():
        raw = raw_values[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        result[player] = {
            'pick': name, 'raw_value': raw if raw < 900 else None,
            'rank': rank, 'baseline_pts': pts, 'bonus_pts': 0,
        }
    return result


# NASCAR Cup standings after Race 6 (Darlington, March 22 2026)
NASCAR_2026_STANDINGS_STATIC = {"standings": [
    {"driver": "Tyler Reddick",         "points": 325},
    {"driver": "Ryan Blaney",           "points": 230},
    {"driver": "Bubba Wallace",         "points": 205},
    {"driver": "Denny Hamlin",          "points": 203},
    {"driver": "Chase Elliott",         "points": 194},
    {"driver": "William Byron",         "points": 191},
    {"driver": "Chris Buescher",        "points": 188},
    {"driver": "Christopher Bell",      "points": 182},
    {"driver": "Brad Keselowski",       "points": 182},
    {"driver": "Kyle Larson",           "points": 176},
    {"driver": "Ty Gibbs",              "points": 173},
    {"driver": "Ryan Preece",           "points": 154},
    {"driver": "Carson Hocevar",        "points": 151},
    {"driver": "Daniel Suarez",         "points": 150},
    {"driver": "Shane van Gisbergen",   "points": 140},
    {"driver": "Joey Logano",           "points": 139},
    {"driver": "Ross Chastain",         "points": 115},
    {"driver": "Chase Briscoe",         "points": 108},
]}

def compute_baseline_nascar():
    picks = DRAFT_PICKS_2026.get('NASCAR', {})
    _d = load_data('nascar')
    if _d and _d.get('standings'):
        data = _d
    else:
        data = fetch_nascar_espn_live() or NASCAR_2026_STANDINGS_STATIC

    raw_values = {}
    for player, driver in picks.items():
        raw = None
        if data:
            for entry in data.get('standings', []):
                if name_matches(driver, entry.get('driver', '')):
                    raw = entry.get('points')
                    break
        raw_values[player] = raw if raw is not None else -1

    valid = {p: (v if v >= 0 else 0) for p, v in raw_values.items()}
    ranks = rank_avg(valid, reverse=True)

    result = {}
    for player, driver in picks.items():
        raw = raw_values[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        result[player] = {
            'pick': driver, 'raw_value': raw if raw >= 0 else None,
            'rank': rank, 'baseline_pts': pts, 'bonus_pts': 0,
        }
    return result


# Static composite fallback for films OMDB/TMDB haven't fully indexed yet.
# composite = rt_score / 100 when no box office data available.
ACTOR_ACTRESS_STATIC = {
    'Actor': {
        'Robert Pattinson': 0.59,    # The Bride! (2026-03-06, RT 59%)
        'Chris Hemsworth':  63.36,   # Crime 101 (2026-02-13, RT 88%, BO $72M → 72 × 0.88)
    },
    'Actress': {
        'Jessie Buckley':   0.59,    # The Bride! (2026-03-06, RT 59%)
    },
}


def compute_baseline_actor_actress(category):
    picks = DRAFT_PICKS_2026.get(category, {})
    data = load_data(category.lower())
    static_lookup = ACTOR_ACTRESS_STATIC.get(category, {})

    raw_values = {}
    movies_map = {}
    for player, name in picks.items():
        composite = None
        movies = []
        if data:
            for entry in data.get('scores', []):
                if name_matches(name, entry.get('name', '')):
                    composite = entry.get('composite_score')
                    movies = entry.get('movies', [])
                    break
        # Fall back to static when scraper returned nothing or zero
        if not composite:
            static = static_lookup.get(name)
            if static is not None:
                composite = static
                print(f'  ↩ {name}: using static composite {composite}')
        raw_values[player] = composite if composite is not None else -1
        movies_map[player] = movies

    valid = {p: (v if v >= 0 else 0) for p, v in raw_values.items()}
    ranks = rank_avg(valid, reverse=True)

    result = {}
    for player, name in picks.items():
        raw = raw_values[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        movies = movies_map[player]
        film_count = len([m for m in movies if m.get('composite') is not None])
        result[player] = {
            'pick': name, 'raw_value': round(raw, 2) if raw >= 0 else None,
            'film_count': film_count, 'movies': movies,
            'rank': rank, 'baseline_pts': pts, 'bonus_pts': 0,
        }
    return result


def compute_baseline_musician():
    picks = DRAFT_PICKS_2026.get('Musician', {})
    data = load_data('musician')

    raw_values = {}
    num1_map = {}
    hot100_map = {}
    for player, name in picks.items():
        score = None
        num1 = None
        if data:
            for entry in data.get('scores', []):
                if name_matches(name, entry.get('artist', '')):
                    num1   = entry.get('num1_weeks', 0) or 0
                    hot100 = entry.get('hot100_weeks', 0) or 0
                    score  = (2 * num1) + hot100
                    break
        raw_values[player] = score if score is not None else -1
        num1_map[player] = num1
        hot100_map[player] = hot100 if score is not None else None

    valid = {p: (v if v >= 0 else 0) for p, v in raw_values.items()}
    ranks = rank_avg(valid, reverse=True)

    songs_map = {}
    for player, name in picks.items():
        if data:
            for entry in data.get('scores', []):
                if name_matches(name, entry.get('artist', '')):
                    songs_map[player] = entry.get('songs', [])
                    break

    result = {}
    for player, name in picks.items():
        raw = raw_values[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        n1 = num1_map[player]
        h100 = hot100_map[player]
        result[player] = {
            'pick': name, 'raw_value': raw if raw >= 0 else None,
            'raw_display': n1 if n1 is not None else None,  # #1 weeks for frontend column
            'num1_weeks': n1,
            'hot100_weeks': h100,
            'rank': rank, 'baseline_pts': pts, 'bonus_pts': 0,
            'songs': songs_map.get(player, []),
        }
    return result


# IMF WEO April 2025 real GDP growth (%) — used as fallback if scraper fails
# Source: IMF DataMapper API NGDP_RPCH, retrieved March 2026
COUNTRY_GDP_IMF_STATIC = {"gdp": [
    {"country": "Netherlands",   "gdp_growth_pct": 1.4},
    {"country": "United States", "gdp_growth_pct": 2.0},
    {"country": "Germany",       "gdp_growth_pct": 0.2},
    {"country": "Guinea",        "gdp_growth_pct": 7.2},
    {"country": "South Sudan",   "gdp_growth_pct": 22.4},
    {"country": "France",        "gdp_growth_pct": 0.7},
    {"country": "Switzerland",   "gdp_growth_pct": 0.9},
    {"country": "Brazil",        "gdp_growth_pct": 2.4},
    {"country": "Norway",        "gdp_growth_pct": 1.2},
    {"country": "Guyana",        "gdp_growth_pct": 10.3},
    {"country": "Argentina",     "gdp_growth_pct": 4.5},
    {"country": "Spain",         "gdp_growth_pct": 2.9},
    {"country": "Canada",        "gdp_growth_pct": 1.2},
]}


def compute_baseline_country():
    picks = DRAFT_PICKS_2026.get('Country', {})
    _d = load_data('country')
    live_data = _d if (_d and _d.get('gdp')) else None

    # Build per-country lookup from static fallback
    static_lookup = {e['country']: e['gdp_growth_pct'] for e in COUNTRY_GDP_IMF_STATIC.get('gdp', [])}

    def _find_gdp(country, data):
        if not data:
            return None
        for entry in data.get('gdp', []):
            if country.lower() in entry.get('country', '').lower() or \
               entry.get('country', '').lower() in country.lower():
                return entry.get('gdp_growth_pct')
        return None

    raw_values = {}
    for player, country in picks.items():
        gdp = _find_gdp(country, live_data)
        # Per-country fallback: if live data missing this country, use static
        if gdp is None:
            gdp = static_lookup.get(country)
        raw_values[player] = gdp if gdp is not None else -999

    valid = {p: (v if v > -999 else 0) for p, v in raw_values.items()}
    ranks = rank_avg(valid, reverse=True)

    result = {}
    for player, country in picks.items():
        raw = raw_values[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        result[player] = {
            'pick': country, 'raw_value': raw if raw > -999 else None,
            'rank': rank, 'baseline_pts': pts, 'bonus_pts': 0,
        }
    return result


def compute_baseline_stock():
    picks = DRAFT_PICKS_2026.get('Stock', {})
    data = load_data('stock')

    raw_values = {}
    for player, info in picks.items():
        ticker    = info['ticker']
        direction = info['direction']
        pct_change = None
        if data:
            for entry in data.get('prices', []):
                if entry.get('ticker', '').upper() == ticker.upper():
                    today = entry.get('current_price')
                    jan1  = entry.get('jan1_price')
                    if today and jan1 and jan1 > 0:
                        raw_pct    = (today / jan1 - 1)
                        pct_change = -raw_pct if direction == 'S' else raw_pct
                    break
        raw_values[player] = pct_change if pct_change is not None else -999

    valid = {p: (v if v > -999 else 0) for p, v in raw_values.items()}
    ranks = rank_avg(valid, reverse=True)

    result = {}
    for player, info in picks.items():
        raw  = raw_values[player]
        rank = ranks.get(player)
        pts  = rank_to_points(rank) if rank is not None else 0
        result[player] = {
            'pick': f"{info['ticker']} ({'Long' if info['direction']=='L' else 'Short'})",
            'raw_value':   round(raw * 100, 2) if raw > -999 else None,
            'raw_display': f"{raw*100:+.1f}%"  if raw > -999 else None,
            'rank': rank, 'baseline_pts': pts, 'bonus_pts': 0,
        }
    return result


# ── Bonus application ─────────────────────────────────────────────────────────

def apply_bonuses(category_scores, bonuses, category):
    cat_bonuses = bonuses.get(category, {})
    for player, bonus_pts in cat_bonuses.items():
        if player in category_scores:
            category_scores[player]['bonus_pts'] = bonus_pts
    return category_scores


# ── Live news headline ────────────────────────────────────────────────────────

def generate_news_headline(draft_picks):
    """Generate FL News headline via two-turn Anthropic call: search turn, then write-only turn."""
    try:
        import anthropic, re
        api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if not api_key:
            print('  ✗ ANTHROPIC_API_KEY not set — skipping headline')
            return None

        print(f'  Anthropic: key present ({len(api_key)} chars), calling API...')
        client = anthropic.Anthropic(api_key=api_key)

        picks_lines = []
        for cat, players in draft_picks.items():
            for player, pick in players.items():
                picks_lines.append(f'{pick} ({cat}, picked by {player})')

        from datetime import date, timedelta
        today = date.today()
        three_days_ago = today - timedelta(days=3)

        # ── Turn 1: Search ──────────────────────────────────────────────────
        search_prompt = (
            f'Today is {today.strftime("%B %d, %Y")}. '
            f'Search for high-impact sports results from {three_days_ago.strftime("%B %d")}–{today.strftime("%B %d")} '
            'for these Fantasy Life draft picks. Focus on: NCAA tournament results, '
            'tennis/golf major results, NHL/NBA playoff clinches or eliminations, NASCAR race wins. '
            'Ignore injuries, trades, contract news, and regular-season games with no standings impact.\n\n'
            'Draft picks:\n' + '\n'.join(picks_lines)
        )

        messages = [{'role': 'user', 'content': search_prompt}]
        tools = [{'type': 'web_search_20250305', 'name': 'web_search'}]

        r1 = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=2000,
            tools=tools,
            messages=messages,
        )
        print(f'  turn1 stop_reason={r1.stop_reason}, blocks={[type(b).__name__ for b in r1.content]}')

        # ── Turn 2: Write only ───────────────────────────────────────────────
        messages.append({'role': 'assistant', 'content': r1.content})
        messages.append({'role': 'user', 'content': (
            'Output ONLY the news ticker text — nothing else. '
            'Plain text, complete sentences, max 50 words total. '
            'Format each item as "Team/Person (FantasyPlayer) result." '
            'No preamble, no analysis, no headers, no bullet points. '
            'If nothing notable happened, output exactly: NO_NEWS'
        )})

        r2 = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=300,
            messages=messages,  # no tools — forces pure text output
        )
        print(f'  turn2 stop_reason={r2.stop_reason}, blocks={[type(b).__name__ for b in r2.content]}')

        # Extract text from turn 2
        text = ' '.join(
            getattr(b, 'text', '').strip()
            for b in r2.content
            if getattr(b, 'text', '').strip()
        ).strip()

        if not text or text.upper() == 'NO_NEWS':
            return None

        # Clean up markdown artifacts
        text = re.sub(r'\*\*|\*|__', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        text = re.sub(r'\s+([.,;])', r'\1', text)

        # Enforce 50-word limit — truncate at last complete sentence
        words = text.split()
        if len(words) > 50:
            truncated = ' '.join(words[:50])
            last_end = max(truncated.rfind('. '), truncated.rfind('! '), truncated.rfind('? '))
            if last_end > 10:
                text = truncated[:last_end + 1].strip()
            else:
                text = truncated.rstrip('.,;') + '.'

        print(f'  Anthropic response text: {repr(text)}')
        return text or None
    except Exception as e:
        import traceback
        print(f'  ✗ Headline generation failed: {e}')
        print(traceback.format_exc())
        return None


# ── Main scorer ───────────────────────────────────────────────────────────────

def compute_all_scores():
    global _bulk_standings
    try:
        _bulk_standings = get_all_standings()
    except Exception as e:
        print(f'  ✗ get_all_standings failed: {e}')
        _bulk_standings = {}

    try:
        bonuses = load_bonuses()
    except Exception as e:
        print(f'  ✗ load_bonuses failed: {e}')
        bonuses = {}

    categories = {
        'NFL':      lambda: compute_baseline_sports('NFL',   'nfl',     'win_pct', static_data=NFL_2025_STANDINGS),
        'NBA':      lambda: compute_baseline_sports('NBA',   'nba',     'win_pct'),
        'MLB':      lambda: compute_baseline_sports('MLB',   'mlb',     'win_pct'),
        'NHL':      lambda: compute_baseline_sports('NHL',   'nhl',     'points_pct'),
        'NCAAF':    lambda: compute_baseline_poll('NCAAF',   'ncaaf',  static_data=NCAAF_2025_POLL),
        'NCAAB':    lambda: compute_baseline_poll('NCAAB',   'ncaab',  static_data=NCAAB_2026_PRE_TOURNAMENT_POLL),
        'Tennis':   compute_baseline_tennis,
        'Golf':     compute_baseline_golf,
        'NASCAR':   compute_baseline_nascar,
        'MLS':      lambda: compute_baseline_sports('MLS',   'mls',     'points', reverse=True, static_data=MLS_2026_STANDINGS),
        'Actor':    lambda: compute_baseline_actor_actress('Actor'),
        'Actress':  lambda: compute_baseline_actor_actress('Actress'),
        'Musician': compute_baseline_musician,
        'Country':  compute_baseline_country,
        'Stock':    compute_baseline_stock,
    }

    all_cat_scores = {}
    for cat, fn in categories.items():
        scores = fn()
        scores = apply_bonuses(scores, bonuses, cat)
        all_cat_scores[cat] = scores

    player_totals = {}
    for player in PLAYERS:
        total = 0
        cat_breakdown = {}
        for cat, scores in all_cat_scores.items():
            p_data    = scores.get(player, {})
            base      = p_data.get('baseline_pts', 0) or 0
            bonus     = p_data.get('bonus_pts', 0) or 0
            bracket   = NCAAB_BRACKET_BONUS.get(player, 0) if cat == 'NCAAB' else 0
            cat_total = base + bonus + bracket
            total    += cat_total
            cat_breakdown[cat] = {
                'pick':             p_data.get('pick', '—'),
                'raw_value':        p_data.get('raw_value'),
                'raw_display':      p_data.get('raw_display'),
                'rank':             p_data.get('rank'),
                'baseline_pts':     round(base, 2),
                'bonus_pts':        round(bonus, 2),
                'bracket_win_pts':  round(bracket, 2) if cat == 'NCAAB' else None,
                'total_pts':        round(cat_total, 2),
                'num1_weeks':       p_data.get('num1_weeks'),
                'hot100_weeks':     p_data.get('hot100_weeks'),
                'movies':           p_data.get('movies') if cat in ('Actor', 'Actress') else None,
                'songs':            p_data.get('songs')  if cat == 'Musician' else None,
            }
        player_totals[player] = {
            'name':       player,
            'total':      round(total, 2),
            'categories': {k.lower(): v for k, v in cat_breakdown.items()},
            'is_premium': player == 'Todd',
        }

    sorted_players = sorted(player_totals.values(), key=lambda x: x['total'], reverse=True)
    for i, p in enumerate(sorted_players):
        p['place'] = i + 1

    print('Generating live news headline via Gemini...')
    headline = generate_news_headline(DRAFT_PICKS_2026)
    if headline == 'NO_NEWS':
        headline = None
    print(f'  Headline: {headline}')

    return {
        'players':      sorted_players,
        'headline':     headline,
        'last_updated': get_last_updated(),
        'season':       2026,
    }


# ── Fuzzy matching ────────────────────────────────────────────────────────────

def team_matches(pick_name, data_name):
    if not pick_name or not data_name:
        return False
    pick = pick_name.lower().strip()
    data = data_name.lower().strip()
    if pick in data or data in pick:
        return True
    for word in ['fc', 'sc', 'city', 'united', 'the', 'de', 'af', 'afc']:
        pick = pick.replace(word, '').strip()
        data = data.replace(word, '').strip()
    if pick and data and len(pick) >= 4 and len(data) >= 4 and (pick in data or data in pick):
        return True
    NICKNAMES = {
        'seahawks': 'seattle seahawks', 'ravens': 'baltimore ravens',
        'bills': 'buffalo bills', '49ers': 'san francisco 49ers',
        'rams': 'los angeles rams', 'chiefs': 'kansas city chiefs',
        'colts': 'indianapolis colts', 'pats': 'new england patriots',
        'packers': 'green bay packers', 'eagles': 'philadelphia eagles',
        'broncos': 'denver broncos', 'lions': 'detroit lions',
        'bucs': 'tampa bay buccaneers', 'buccaneers': 'tampa bay buccaneers',
        'nuggets': 'denver nuggets', 'spurs': 'san antonio spurs',
        'cavs': 'cleveland cavaliers', 'timberwolves': 'minnesota timberwolves',
        'warriors': 'golden state warriors', 'celtics': 'boston celtics',
        'lakers': 'los angeles lakers', 'okc': 'oklahoma city thunder',
        'clippers': 'los angeles clippers', 'rockets': 'houston rockets',
        'bucks': 'milwaukee bucks', 'magic': 'orlando magic',
        'knicks': 'new york knicks', 'lafc': 'los angeles fc',
        'la galaxy': 'los angeles galaxy',
        'la clippers': 'los angeles clippers',
        'la lakers': 'los angeles lakers',
        'la rams': 'los angeles rams',
        'la chargers': 'los angeles chargers',
    }
    pick_norm = NICKNAMES.get(pick, pick)
    data_norm = NICKNAMES.get(data, data)
    return len(pick_norm) >= 4 and len(data_norm) >= 4 and (pick_norm in data_norm or data_norm in pick_norm)


def name_matches(pick_name, data_name):
    if not pick_name or not data_name:
        return False
    pick = pick_name.lower().strip()
    data = data_name.lower().strip()
    if pick in data or data in pick:
        return True
    pick_last = pick.split()[-1] if pick.split() else pick
    data_last = data.split()[-1] if data.split() else data
    if len(pick_last) > 3 and (pick_last in data or data_last in pick):
        return True
    return False


if __name__ == '__main__':
    import json, os
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'scores.json')

    # Preserve existing headline if Gemini fails to produce one
    existing_headline = None
    existing_snapshot = None
    if os.path.exists(out_path):
        try:
            with open(out_path) as f:
                existing = json.load(f)
                existing_headline = existing.get('headline')
                existing_snapshot = existing.get('prev_snapshot')
        except Exception:
            pass

    print('Computing scores...')
    data = compute_all_scores()

    if not data.get('headline') and existing_headline:
        print(f'  Gemini produced no headline — preserving existing: {existing_headline[:60]}...')
        data['headline'] = existing_headline
    elif not data.get('headline'):
        data['headline'] = (
            'Final Four Saturday: UConn (Fryar) vs Illinois, Michigan (Jamzee) vs Arizona in Indianapolis. '
            'Tommy Fleetwood (Korch) tees off as favorite at the Valero Texas Open today. '
            'Colorado Avalanche (Korch) were first to clinch an NHL playoff spot. Alcaraz (Todd) eyes Monte Carlo next week.'
        )

    # Snapshot rotation: keep prev_snapshot for 7 days, then rotate
    from datetime import date as _date
    today_str = _date.today().isoformat()
    snap = existing_snapshot or {}
    snap_date = snap.get('date')
    if snap_date:
        days_old = (_date.today() - _date.fromisoformat(snap_date)).days
        if days_old >= 7:
            snap = None  # will be replaced with current data below
    if not snap:
        snap = {
            'date':   today_str,
            'ranks':  {p['name']: p['place'] for p in data.get('players', [])},
            'totals': {p['name']: round(p['total'], 2) for p in data.get('players', [])},
        }
    data['prev_snapshot'] = snap

    with open(out_path, 'w') as f:
        json.dump(data, f)
    n = len(data.get('players', []))
    print(f'✓ Wrote {out_path}  ({n} players, last_updated={data.get("last_updated")})')
