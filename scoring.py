"""
Fantasy Life 2026 — Scoring Engine
Handles baseline (rotisserie) + bonus point computation.
Reads all data from Supabase via db.py instead of local JSON files.
"""

import os

from draft_picks_2026 import DRAFT_PICKS_2026, PLAYERS, TENNIS_GENDER
from db import get_standing, get_all_standings, get_all_bonuses, get_last_updated

SEASON = 2026
PREMIUM_PLAYER = 'Todd'
_MISSING_POLL_RANK = 26  # one beyond the 25-team poll ceiling; treated as unranked in scoring

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
    """Load category data from Supabase. Returns the data dict or None."""
    key = _KEY_MAP.get(category_key.lower(), category_key)
    if _bulk_standings:
        return _bulk_standings.get(key) or None
    data = get_standing(key)
    return data if data else None


def load_bonuses():
    """Load bonus points from Supabase, with data/bonuses.json taking priority.

    For any (category, player) pair present in the JSON file, the file value
    replaces the Supabase value entirely (override-wins, not additive). Edit
    data/bonuses.json instead of Supabase for auditability.
    """
    import json as _json
    bonuses = get_all_bonuses()
    _bonus_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'bonuses.json')
    try:
        with open(_bonus_path) as _f:
            file_bonuses = _json.load(_f)
    except Exception as e:
        print(f'  ✗ Could not load data/bonuses.json: {e}')
        file_bonuses = {}
    for cat, players in file_bonuses.items():
        if cat.startswith('_'):
            continue
        if cat not in bonuses:
            bonuses[cat] = {}
        for player, pts in players.items():
            if player in bonuses.get(cat, {}):
                print(f'  ↩ bonus override: {cat}/{player} Supabase={bonuses[cat][player]} → file={pts}')
            bonuses[cat][player] = float(pts)
    return bonuses



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

# 2025 NCAAF final US LBM Coaches Poll (released Jan 20, 2026, after CFP championship)
NCAAF_2025_POLL = {"poll": [
    {"rank": 1,  "team": "Indiana Hoosiers",           "short": "Indiana",      "location": "Indiana"},
    {"rank": 2,  "team": "Miami Hurricanes",            "short": "Miami",        "location": "Miami"},
    {"rank": 3,  "team": "Mississippi Rebels",          "short": "Ole Miss",     "location": "Mississippi"},
    {"rank": 4,  "team": "Oregon Ducks",                "short": "Oregon",       "location": "Oregon"},
    {"rank": 5,  "team": "Georgia Bulldogs",            "short": "Georgia",      "location": "Georgia"},
    {"rank": 6,  "team": "Ohio State Buckeyes",         "short": "Ohio State",   "location": "Ohio State"},
    {"rank": 7,  "team": "Texas Tech Red Raiders",      "short": "Texas Tech",   "location": "Texas Tech"},
    {"rank": 8,  "team": "Texas A&M Aggies",            "short": "Texas A&M",    "location": "Texas A&M"},
    {"rank": 9,  "team": "Alabama Crimson Tide",        "short": "Alabama",      "location": "Alabama"},
    {"rank": 10, "team": "Oklahoma Sooners",            "short": "Oklahoma",     "location": "Oklahoma"},
    {"rank": 11, "team": "Notre Dame Fighting Irish",   "short": "Notre Dame",   "location": "Notre Dame"},
    {"rank": 12, "team": "BYU Cougars",                 "short": "BYU",          "location": "BYU"},
    {"rank": 13, "team": "Texas Longhorns",             "short": "Texas",        "location": "Texas"},
    {"rank": 14, "team": "Utah Utes",                   "short": "Utah",         "location": "Utah"},
    {"rank": 15, "team": "Vanderbilt Commodores",       "short": "Vanderbilt",   "location": "Vanderbilt"},
    {"rank": 16, "team": "Virginia Cavaliers",          "short": "Virginia",     "location": "Virginia"},
    {"rank": 17, "team": "Iowa Hawkeyes",               "short": "Iowa",         "location": "Iowa"},
    {"rank": 18, "team": "Tulane Green Wave",           "short": "Tulane",       "location": "Tulane"},
    {"rank": 19, "team": "Houston Cougars",             "short": "Houston",      "location": "Houston"},
    {"rank": 20, "team": "James Madison Dukes",         "short": "James Madison","location": "James Madison"},
    {"rank": 21, "team": "USC Trojans",                 "short": "USC",          "location": "Southern California"},
    {"rank": 22, "team": "Michigan Wolverines",         "short": "Michigan",     "location": "Michigan"},
    {"rank": 23, "team": "Navy Midshipmen",             "short": "Navy",         "location": "Navy"},
    {"rank": 24, "team": "Georgia Tech Yellow Jackets", "short": "Georgia Tech", "location": "Georgia Tech"},
    {"rank": 25, "team": "Illinois Fighting Illini",    "short": "Illinois",     "location": "Illinois"},
]}


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
        raw_values[player] = raw if raw is not None else _MISSING_POLL_RANK

    ranks = rank_avg(raw_values, reverse=False)

    result = {}
    for player, team in picks.items():
        raw = raw_values[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        result[player] = {
            'pick': team, 'raw_value': raw if raw != _MISSING_POLL_RANK else None,
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


# OWGR as of May 13, 2026 (static fallback — ESPN API blocked)
GOLF_2026_OWGR_STATIC = {"rankings": [
    {"player": "Scottie Scheffler",   "rank": 1},
    {"player": "Rory McIlroy",        "rank": 2},
    {"player": "Cameron Young",       "rank": 3},
    {"player": "Matt Fitzpatrick",    "rank": 4},
    {"player": "Collin Morikawa",     "rank": 5},
    {"player": "Tommy Fleetwood",     "rank": 6},
    {"player": "Justin Rose",         "rank": 7},
    {"player": "J.J. Spaun",          "rank": 8},
    {"player": "Russell Henley",      "rank": 9},
    {"player": "Chris Gotterup",      "rank": 10},
    {"player": "Xander Schauffele",   "rank": 11},
    {"player": "Robert MacIntyre",    "rank": 12},
    {"player": "Sepp Straka",         "rank": 13},
    {"player": "Ben Griffin",         "rank": 14},
    {"player": "Ludvig Aberg",        "rank": 15},
    {"player": "Justin Thomas",       "rank": 16},
    {"player": "Hideki Matsuyama",    "rank": 17},
    {"player": "Alex Noren",          "rank": 18},
    {"player": "Jacob Bridgeman",     "rank": 19},
    {"player": "Jon Rahm",            "rank": 20},
    {"player": "Harris English",      "rank": 21},
    {"player": "Viktor Hovland",      "rank": 27},
    {"player": "Bryson DeChambeau",   "rank": 28},
    {"player": "Patrick Cantlay",     "rank": 30},
]}

def compute_baseline_golf():
    picks = DRAFT_PICKS_2026.get('Golf', {})
    _d = load_data('golf')
    data = _d if (_d and _d.get('rankings')) else GOLF_2026_OWGR_STATIC

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


# MLS 2026 standings as of Apr 30 2026 (week ~10)
MLS_2026_STANDINGS_STATIC = {"standings": [
    {"team": "Vancouver Whitecaps",  "points": 24},
    {"team": "LAFC",                 "points": 20},
    {"team": "Inter Miami",          "points": 19},
    {"team": "Seattle Sounders",     "points": 19},
    {"team": "Minnesota United",     "points": 17},
    {"team": "Charlotte FC",         "points": 14},
    {"team": "New York Red Bulls",   "points": 12},
    {"team": "Columbus Crew",        "points": 12},
    {"team": "FC Cincinnati",        "points": 12},
    {"team": "LA Galaxy",            "points": 12},
    {"team": "San Diego FC",         "points": 11},
    {"team": "Orlando City",         "points": 7},
    {"team": "Philadelphia Union",   "points": 5},
]}

def compute_baseline_mls():
    picks = DRAFT_PICKS_2026.get('MLS', {})
    _d = load_data('mls')
    # If the local file has stale end-of-season data (>50 pts), ignore it
    if _d and _d.get('standings') and max((e.get('points', 0) for e in _d['standings']), default=0) > 50:
        _d = None
    data = _d if (_d and _d.get('standings')) else MLS_2026_STANDINGS_STATIC
    return compute_baseline_sports('MLS', 'mls', 'points', reverse=True, static_data=data)


# NASCAR Cup standings after Race 12 (Watkins Glen, May 10 2026)
NASCAR_2026_STANDINGS_STATIC = {"standings": [
    {"driver": "Tyler Reddick",         "points": 567},
    {"driver": "Denny Hamlin",          "points": 438},
    {"driver": "Chase Elliott",         "points": 422},
    {"driver": "Ryan Blaney",           "points": 405},
    {"driver": "Chris Buescher",        "points": 375},
    {"driver": "Ty Gibbs",              "points": 372},
    {"driver": "Carson Hocevar",        "points": 342},
    {"driver": "Kyle Larson",           "points": 332},
    {"driver": "Brad Keselowski",       "points": 318},
    {"driver": "Bubba Wallace",         "points": 313},
    {"driver": "Christopher Bell",      "points": 311},
    {"driver": "William Byron",         "points": 309},
    {"driver": "Ryan Preece",           "points": 296},
    {"driver": "Daniel Suarez",         "points": 295},
    {"driver": "Austin Cindric",        "points": 287},
    {"driver": "Shane van Gisbergen",   "points": 283},
    {"driver": "Chase Briscoe",         "points": 277},
    {"driver": "Joey Logano",           "points": 245},
    {"driver": "Ross Chastain",         "points": 236},
    {"driver": "AJ Allmendinger",       "points": 235},
]}

def compute_baseline_nascar():
    picks = DRAFT_PICKS_2026.get('NASCAR', {})
    _d = load_data('nascar')
    data = _d if (_d and _d.get('standings')) else NASCAR_2026_STANDINGS_STATIC

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


def compute_baseline_actor_actress(category):
    picks = DRAFT_PICKS_2026.get(category, {})
    data = load_data(category.lower())

    raw_values = {}
    for player, name in picks.items():
        composite = None
        if data:
            for entry in data.get('scores', []):
                if name_matches(name, entry.get('name', '')):
                    composite = entry.get('composite_score')
                    break
        raw_values[player] = composite if composite is not None else -1

    valid = {p: (v if v >= 0 else 0) for p, v in raw_values.items()}
    ranks = rank_avg(valid, reverse=True)

    result = {}
    for player, name in picks.items():
        raw = raw_values[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        result[player] = {
            'pick': name, 'raw_value': round(raw, 2) if raw >= 0 else None,
            'rank': rank, 'baseline_pts': pts, 'bonus_pts': 0,
        }
    return result


def compute_baseline_musician():
    picks = DRAFT_PICKS_2026.get('Musician', {})
    data = load_data('musician')

    raw_values = {}
    for player, name in picks.items():
        score = None
        if data:
            for entry in data.get('scores', []):
                if name_matches(name, entry.get('artist', '')):
                    num1   = entry.get('num1_weeks', 0) or 0
                    hot100 = entry.get('hot100_weeks', 0) or 0
                    score  = (2 * num1) + hot100
                    break
        raw_values[player] = score if score is not None else -1

    valid = {p: (v if v >= 0 else 0) for p, v in raw_values.items()}
    ranks = rank_avg(valid, reverse=True)

    result = {}
    for player, name in picks.items():
        raw = raw_values[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        result[player] = {
            'pick': name, 'raw_value': raw if raw >= 0 else None,
            'rank': rank, 'baseline_pts': pts, 'bonus_pts': 0,
        }
    return result


def compute_baseline_country():
    picks = DRAFT_PICKS_2026.get('Country', {})
    data = load_data('country')

    raw_values = {}
    for player, country in picks.items():
        gdp = None
        if data:
            for entry in data.get('gdp', []):
                if country.lower() in entry.get('country', '').lower() or \
                   entry.get('country', '').lower() in country.lower():
                    gdp = entry.get('gdp_growth_pct')
                    break
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
        'NCAAB':    lambda: compute_baseline_poll('NCAAB',   'ncaab'),
        'Tennis':   compute_baseline_tennis,
        'Golf':     compute_baseline_golf,
        'NASCAR':   compute_baseline_nascar,
        'MLS':      compute_baseline_mls,
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
            cat_total = base + bonus
            total    += cat_total
            cat_breakdown[cat] = {
                'pick':         p_data.get('pick', '—'),
                'raw_value':    p_data.get('raw_value'),
                'raw_display':  p_data.get('raw_display'),
                'rank':         p_data.get('rank'),
                'baseline_pts': round(base, 2),
                'bonus_pts':    round(bonus, 2),
                'total_pts':    round(cat_total, 2),
            }
        player_totals[player] = {
            'name':       player,
            'total':      round(total, 2),
            'categories': {k.lower(): v for k, v in cat_breakdown.items()},
            'is_premium': player == PREMIUM_PLAYER,
        }

    sorted_players = sorted(player_totals.values(), key=lambda x: x['total'], reverse=True)
    for i, p in enumerate(sorted_players):
        p['place'] = i + 1

    return {
        'players':      sorted_players,
        'last_updated': get_last_updated(),
        'season':       SEASON,
    }


# ── Fuzzy matching ────────────────────────────────────────────────────────────

def team_matches(pick_name, data_name):
    if not pick_name or not data_name:
        return False
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
        'knicks': 'new york knicks',
        'lafc': 'lafc', 'los angeles fc': 'lafc',
        'la galaxy': 'la galaxy', 'los angeles galaxy': 'la galaxy',
        'seattle sounders fc': 'seattle sounders',
        'inter miami cf': 'inter miami',
        'columbus crew sc': 'columbus crew',
        'minnesota united fc': 'minnesota united',
    }
    pick = pick_name.lower().strip()
    data = data_name.lower().strip()
    if pick == data:
        return True
    # Normalize via NICKNAMES on original names first
    pick_norm = NICKNAMES.get(pick, pick)
    data_norm = NICKNAMES.get(data, data)
    if pick_norm == data_norm:
        return True
    if len(pick_norm) >= 4 and len(data_norm) >= 4:
        if pick_norm in data_norm or data_norm in pick_norm:
            return True
    # Strip common suffixes/words and try again
    for word in ['fc', 'sc', 'city', 'united', 'the', 'de', 'af', 'afc']:
        pick = pick.replace(word, '').strip()
        data = data.replace(word, '').strip()
    if pick and data and len(pick) >= 4 and len(data) >= 4 and (pick in data or data in pick):
        return True
    return False


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


def generate_news_headline(scores_data: dict) -> str | None:
    """Generate an FL News ticker headline via Claude. Returns None on failure."""
    try:
        import anthropic
        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

        players = scores_data.get('players', [])
        standings = '\n'.join(
            f"{p['place']}. {p['name']}: {p['total']} pts"
            for p in players
        )

        msg = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=120,
            messages=[{
                'role': 'user',
                'content': f"""You write punchy one-sentence "FL News" ticker headlines for Fantasy Life 2026, a 13-person fantasy sports league covering NBA, NHL, MLB, Tennis, Golf, Actress, Actor, Musician, Stock, Country GDP, NASCAR, MLS, NCAAB, NCAAF, and NFL.

Current standings:
{standings}

Rules:
- One sentence only, max 25 words
- Find the most interesting story: tight race, big lead, dramatic surge, collapse, notable gap
- Use <em> tags around player names
- End with a fitting emoji
- Output ONLY the headline, no quotes, no explanation

Headline:""",
            }],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        print(f'  ✗ generate_news_headline: {e}')
        return None


if __name__ == '__main__':
    import json, os
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'scores.json')

    import datetime

    # Read previous scores.json to preserve headline and weekly baseline
    existing_headline = ''
    weekly_baseline: dict = {}
    try:
        with open(out_path) as _f:
            prev = json.load(_f)
            existing_headline = prev.get('headline', '')
            weekly_baseline = prev.get('weekly_baseline', {})
    except Exception:
        pass

    print('Computing scores...')
    data = compute_all_scores()
    data['headline'] = existing_headline

    # Build lookup of new scores/places
    new_totals = {p['name']: p['total'] for p in data.get('players', [])}
    new_places = {p['name']: p['place'] for p in data.get('players', [])}

    # Reset baseline every Tuesday; seed from scratch if missing
    today_utc = datetime.datetime.utcnow()
    is_reset_day = today_utc.weekday() == 1  # Tuesday
    if not weekly_baseline.get('totals') or is_reset_day:
        weekly_baseline = {
            'totals': new_totals,
            'places': new_places,
            'date': today_utc.strftime('%Y-%m-%d'),
        }
        print(f'  Weekly baseline {"reset" if is_reset_day else "seeded"} ({weekly_baseline["date"]})')

    data['weekly_baseline'] = weekly_baseline

    # Attach week-over-week deltas vs baseline
    base_totals = weekly_baseline.get('totals', {})
    base_places = weekly_baseline.get('places', {})
    for p in data.get('players', []):
        name = p['name']
        if name in base_totals:
            p['week_delta'] = round(p['total'] - base_totals[name], 2)
            p['place_change'] = base_places.get(name, p['place']) - p['place']
        else:
            p['week_delta'] = None
            p['place_change'] = None

    # Write scores first — headline failure must never block the leaderboard
    with open(out_path, 'w') as f:
        json.dump(data, f)
    n = len(data.get('players', []))
    print(f'✓ Wrote {out_path}  ({n} players, last_updated={data.get("last_updated")})')

    # Attempt headline update as a separate non-critical step
    print('Generating FL News headline...')
    new_headline = generate_news_headline(data)
    if new_headline:
        data['headline'] = new_headline
        with open(out_path, 'w') as f:
            json.dump(data, f)
        print(f'  ✓ Headline: {new_headline[:80]}')
    else:
        print(f'  – Keeping existing headline')
