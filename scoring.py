"""
Fantasy Life 2026 — Scoring Engine
Handles baseline (rotisserie) + bonus point computation.
Reads all data from Supabase via db.py instead of local JSON files.
"""

import os

from datetime import datetime, timezone, timedelta

from draft_picks_2026 import DRAFT_PICKS_2026, PLAYERS, TENNIS_GENDER
from db import get_standing, get_all_standings, get_all_bonuses, get_last_updated, get_standing_updated_at

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

# Records which tier produced each category's data this run, for provenance in
# scores.json. Values: 'live' | 'wikipedia' | 'local_json' | 'static_fallback'.
# Populated by the compute_baseline_* functions; read into data_freshness.
_category_source: dict = {}

def _supabase_source(data, default='live'):
    """Read the _source stamp a scraper embedded in a Supabase blob, if any."""
    if isinstance(data, dict) and data.get('_source'):
        return data['_source']
    return default

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

def _load_local_json(name):
    """Load data/{name}.json if it exists. Returns the parsed dict or None."""
    import json as _json
    path = os.path.join(_DATA_DIR, f'{name}.json')
    try:
        with open(path) as f:
            return _json.load(f)
    except Exception:
        return None

def load_data(category_key):
    """Load category data from Supabase. Returns the data dict or None."""
    key = _KEY_MAP.get(category_key.lower(), category_key)
    if _bulk_standings:
        return _bulk_standings.get(key) or None
    data = get_standing(key)
    return data if data else None


def _parse_dt(s):
    """Parse an ISO date/datetime string to an aware UTC datetime, or None."""
    if not s:
        return None
    for cand in (str(s).replace('Z', '+00:00'), str(s)[:10]):
        try:
            dt = datetime.fromisoformat(cand)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def select_standings(category, data_key, local_name, static_data, static_date, reject=None):
    """Pick the best standings source by freshness, returning (data, source_label).

    Policy (per the golf/MLS/NASCAR precedence decision):
      1. Fresh live (Supabase row ≤3 days old) always wins.
      2. Otherwise use the NEWEST-dated of the remaining available sources —
         stale live, the manual data/{local_name}.json override (its `_updated`),
         and the in-code static dict (static_date). This keeps a fresh manual
         override above an older static dict, while preventing a months-stale
         override (e.g. golf.json) from beating fresher data.
    `reject(data)` optionally drops a candidate (used for the MLS >50-pts rule).
    source_label ∈ {live, wikipedia, local_json, static_fallback}.
    """
    now = datetime.now(timezone.utc)
    ok = lambda d: bool(d and d.get(data_key)) and (reject is None or not reject(d))

    live = load_data(category)
    live = live if ok(live) else None
    live_dt = _parse_dt(get_standing_updated_at(category)) if live else None

    local = _load_local_json(local_name)
    local = local if ok(local) else None
    local_dt = _parse_dt(local.get('_updated')) if local else None

    # 1. Fresh live wins outright.
    if live and live_dt and (now - live_dt).days <= 3:
        return live, _supabase_source(live)

    # 2. Newest-dated of the available sources.
    floor = datetime.min.replace(tzinfo=timezone.utc)
    candidates = [(_parse_dt(static_date) or floor, 'static_fallback', static_data)]
    if local:
        candidates.append((local_dt or floor, 'local_json', local))
    if live:
        candidates.append((live_dt or floor, _supabase_source(live), live))
    candidates.sort(key=lambda c: c[0], reverse=True)
    _, label, data = candidates[0]
    return data, label


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

    # Merge Country_WorldCup into Country, capped at 13 combined with Winter Olympics
    _COUNTRY_CAP = 13.0
    country_olympics = bonuses.get('Country', {})
    country_wc = bonuses.pop('Country_WorldCup', {})
    # Stash the uncapped per-source values for display (country page shows
    # Olympics and World Cup bonus as separate columns) — 'Country' itself
    # gets overwritten below with the capped combined total used for scoring.
    bonuses['_country_olympics'] = dict(country_olympics)
    bonuses['_country_worldcup'] = dict(country_wc)
    if country_wc:
        all_players = set(country_olympics) | set(country_wc)
        merged = {}
        for player in all_players:
            total = min(_COUNTRY_CAP, (country_olympics.get(player) or 0) + (country_wc.get(player) or 0))
            merged[player] = total
            wc_pts = country_wc.get(player, 0)
            if wc_pts:
                print(f'  🌍 Country WC: {player} Olympics={country_olympics.get(player, 0)} + WC={wc_pts} → {total} (cap={_COUNTRY_CAP})')
        bonuses['Country'] = merged

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
GOLF_2026_OWGR_STATIC = {"as_of": "2026-05-26", "rankings": [
    {"player": "Scottie Scheffler",   "rank": 1},
    {"player": "Rory McIlroy",        "rank": 2},
    {"player": "Cameron Young",       "rank": 3},
    {"player": "Justin Rose",         "rank": 4},
    {"player": "Matt Fitzpatrick",    "rank": 5},
    {"player": "Collin Morikawa",     "rank": 6},
    {"player": "Tommy Fleetwood",     "rank": 7},
    {"player": "Xander Schauffele",   "rank": 8},
    {"player": "Russell Henley",      "rank": 9},
    {"player": "J.J. Spaun",          "rank": 10},
    {"player": "Chris Gotterup",      "rank": 11},
    {"player": "Jon Rahm",            "rank": 12},
    {"player": "Robert MacIntyre",    "rank": 13},
    {"player": "Aaron Rai",           "rank": 14},
    {"player": "Ludvig Aberg",        "rank": 15},
    {"player": "Justin Thomas",       "rank": 16},
    {"player": "Hideki Matsuyama",    "rank": 17},
    {"player": "Alex Noren",          "rank": 18},
    {"player": "Jacob Bridgeman",     "rank": 19},
    {"player": "Harris English",      "rank": 21},
    {"player": "Sepp Straka",         "rank": 22},
    {"player": "Ben Griffin",         "rank": 24},
    {"player": "Viktor Hovland",      "rank": 30},
    {"player": "Bryson DeChambeau",   "rank": 32},
    {"player": "Patrick Cantlay",     "rank": 33},
]}

def compute_baseline_golf():
    picks = DRAFT_PICKS_2026.get('Golf', {})
    # Live (OWGR/ESPN via Supabase) → manual data/golf.json → static, by freshness.
    data, _category_source['golf'] = select_standings(
        'Golf', 'rankings', 'golf', GOLF_2026_OWGR_STATIC,
        GOLF_2026_OWGR_STATIC.get('as_of', '2026-05-26'))

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


# MLS 2026 standings as of May 27 2026 (pre-World Cup break, week ~14)
MLS_2026_STANDINGS_STATIC = {"standings": [
    {"team": "Vancouver Whitecaps",  "points": 32},
    {"team": "Inter Miami",          "points": 28},
    {"team": "LAFC",                 "points": 24},
    {"team": "Seattle Sounders",     "points": 24},
    {"team": "Minnesota United",     "points": 22},
    {"team": "Charlotte FC",         "points": 21},
    {"team": "LA Galaxy",            "points": 20},
    {"team": "New York Red Bulls",   "points": 19},
    {"team": "San Diego FC",         "points": 17},
    {"team": "FC Cincinnati",        "points": 16},
    {"team": "Columbus Crew",        "points": 16},
    {"team": "Orlando City",         "points": 14},
    {"team": "Philadelphia Union",   "points": 5},
]}

def compute_baseline_mls():
    # Live (Wikipedia/ESPN via Supabase) → manual data/mls.json → static, by
    # freshness. Reject any source whose max points >50 (end-of-season stale data).
    _mls_reject = lambda d: max((e.get('points', 0) for e in d.get('standings', [])), default=0) > 50
    data, _category_source['mls'] = select_standings(
        'MLS', 'standings', 'mls', MLS_2026_STANDINGS_STATIC, '2026-05-27', reject=_mls_reject)
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
    # Live (Wikipedia/ESPN via Supabase) → manual data/nascar.json → static, by freshness.
    data, _category_source['nascar'] = select_standings(
        'NASCAR', 'standings', 'nascar', NASCAR_2026_STANDINGS_STATIC, '2026-05-10')

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
    import json as _json
    _path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', f'{category.lower()}.json')
    data = None
    try:
        with open(_path) as _f:
            data = _json.load(_f)
    except Exception:
        data = load_data(category.lower())

    raw_values = {}
    movies_by_player = {}
    for player, name in picks.items():
        composite = None
        if data:
            for entry in data.get('scores', []):
                if name_matches(name, entry.get('name', '')):
                    composite = entry.get('composite_score')
                    if entry.get('movies'):
                        movies_by_player[player] = entry['movies']
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
            'movies': movies_by_player.get(player, []),
        }
    return result


def compute_baseline_musician():
    picks = DRAFT_PICKS_2026.get('Musician', {})
    data = load_data('musician')

    raw_values = {}
    chart_by_player = {}
    for player, name in picks.items():
        score = None
        if data:
            for entry in data.get('scores', []):
                if name_matches(name, entry.get('artist', '')):
                    num1   = entry.get('num1_weeks', 0) or 0
                    hot100 = entry.get('hot100_weeks', 0) or 0
                    score  = (2 * num1) + hot100
                    chart_by_player[player] = {
                        'num1_weeks': num1, 'hot100_weeks': hot100,
                        'songs': entry.get('songs', []),
                    }
                    break
        raw_values[player] = score if score is not None else -1

    valid = {p: (v if v >= 0 else 0) for p, v in raw_values.items()}
    ranks = rank_avg(valid, reverse=True)

    result = {}
    for player, name in picks.items():
        raw = raw_values[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        stats = chart_by_player.get(player, {})
        result[player] = {
            'pick': name, 'raw_value': raw if raw >= 0 else None,
            'rank': rank, 'baseline_pts': pts, 'bonus_pts': 0,
            'num1_weeks': stats.get('num1_weeks', 0),
            'hot100_weeks': stats.get('hot100_weeks', 0),
            'songs': stats.get('songs', []),
        }
    return result


def compute_baseline_country():
    picks = DRAFT_PICKS_2026.get('Country', {})
    # Primary: local file (IMF WEO data, updated April + October each year)
    # Supabase is NOT used for Country — it holds stale scraped data.
    import json as _json
    _path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'country.json')
    data = None
    try:
        with open(_path) as _f:
            data = _json.load(_f)
    except Exception:
        data = load_data('country')  # fallback only if file is missing

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
            entry = {
                'pick':         p_data.get('pick', '—'),
                'raw_value':    p_data.get('raw_value'),
                'raw_display':  p_data.get('raw_display'),
                'rank':         p_data.get('rank'),
                'baseline_pts': round(base, 2),
                'bonus_pts':    round(bonus, 2),
                'total_pts':    round(cat_total, 2),
            }
            if cat == 'Musician':
                entry['num1_weeks'] = p_data.get('num1_weeks', 0)
                entry['hot100_weeks'] = p_data.get('hot100_weeks', 0)
                entry['songs'] = p_data.get('songs', [])
            elif cat in ('Actor', 'Actress'):
                entry['movies'] = p_data.get('movies', [])
            elif cat == 'Country':
                # bonus_pts above is the capped combined total (used for scoring);
                # these two are the uncapped per-source values for display.
                entry['olympics_bonus_pts'] = round(bonuses.get('_country_olympics', {}).get(player, 0) or 0, 2)
                entry['world_cup_bonus_pts'] = round(bonuses.get('_country_worldcup', {}).get(player, 0) or 0, 2)
            cat_breakdown[cat] = entry
        player_totals[player] = {
            'name':       player,
            'total':      round(total, 2),
            'categories': {k.lower(): v for k, v in cat_breakdown.items()},
            'is_premium': player == PREMIUM_PLAYER,
        }

    sorted_players = sorted(player_totals.values(), key=lambda x: x['total'], reverse=True)
    for i, p in enumerate(sorted_players):
        p['place'] = i + 1

    # Staleness check: warn if golf data hasn't been refreshed within 7 days
    golf_data_stale = True  # conservative default — assume stale until proven otherwise
    golf_updated_at = get_standing_updated_at('Golf')
    if golf_updated_at:
        try:
            age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(golf_updated_at.replace('Z', '+00:00'))).days
            golf_data_stale = age_days > 7
            if golf_data_stale:
                print(f'  ⚠ Golf data is {age_days} days old (last updated {golf_updated_at})')
            else:
                print(f'  ✓ Golf data is {age_days} days old (fresh)')
        except Exception:
            pass

    # Data freshness per live-scraped category: age of the Supabase row + the
    # provenance tier that scoring actually used this run (live / wikipedia /
    # local_json / static_fallback). MLS/NASCAR/Golf can legitimately come from a
    # data/*.json override; the source field makes "running on fallback" visible in
    # the committed scores.json instead of only in ephemeral Actions logs.
    data_freshness = {}
    for cat in ['NBA', 'MLB', 'NHL', 'NCAAB', 'Tennis', 'Musician', 'Stock', 'MLS', 'NASCAR', 'Golf']:
        updated_at = get_standing_updated_at(cat)
        age_days = None
        if updated_at:
            try:
                age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(updated_at.replace('Z', '+00:00'))).days
            except Exception:
                pass
        # For categories with a known override/fallback tier, trust the recorded
        # source; otherwise it's a straight live Supabase read.
        source = _category_source.get(cat.lower(), _supabase_source(load_data(cat.lower()), default='live'))
        # "stale" = not running on fresh live data: any manual/static fallback, or
        # a live row older than 3 days.
        stale = source in ('local_json', 'static_fallback') or age_days is None or age_days > 3
        data_freshness[cat.lower()] = {
            'updated_at': updated_at, 'age_days': age_days, 'stale': stale, 'source': source,
        }
        if stale:
            print(f'  ⚠ {cat}: source={source}, Supabase row '
                  f'{age_days if age_days is not None else "unknown"} days old [STALE]')

    return {
        'players':         sorted_players,
        'last_updated':    get_last_updated(),
        'season':          SEASON,
        'golf_data_stale': golf_data_stale,
        'data_freshness':  data_freshness,
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
    if len(pick_last) > 3 and (pick_last in data.split() or data_last in pick.split()):
        return True
    return False



if __name__ == '__main__':
    import json, os
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'scores.json')

    # Read previous scores.json to preserve headline, headline timestamp, and score history
    existing_headline = ''
    existing_headline_ts = None
    score_history: list = []
    prev: dict = {}
    try:
        with open(out_path) as _f:
            prev = json.load(_f)
            existing_headline = prev.get('headline', '')
            existing_headline_ts = prev.get('headline_generated_at')
            score_history = prev.get('score_history', [])
            # One-time migration from old weekly_baseline
            if not score_history:
                wb = prev.get('weekly_baseline', {})
                if wb.get('totals') and wb.get('date'):
                    score_history = [{'date': wb['date'], 'totals': wb['totals'], 'places': wb.get('places', {})}]
    except Exception:
        pass

    # Settle any resolved sportsbook bets centrally so all players get credited
    _sb_settled_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'sb_settled.json')
    if os.path.exists(_sb_settled_path):
        import db as _db
        with open(_sb_settled_path) as _f:
            _sb_settled = json.load(_f)
        if _sb_settled:
            print('Settling sportsbook bets...')
            for _entry in _sb_settled:
                _db.settle_sb_bet(_entry['id'], _entry['outcome'])

        # Recalculate every player's balance from their actual bet records.
        # Self-heals any corruption (e.g. client-side RESET_AFTER overwriting Supabase balance).
        _all_sb_players = ['Tim','Wu','Jens','Todd','Mitchell','Shep','Theo',
                           'Feder','Fryar','Korch','Molmen','Jamzee','Buckley']
        print('Recalculating BB balances...')
        for _p in _all_sb_players:
            _db.recalculate_sb_balance(_p)

    print('Computing scores...')
    data = compute_all_scores()
    data['headline'] = existing_headline
    if existing_headline_ts:
        data['headline_generated_at'] = existing_headline_ts

    # Guard: if Supabase was unavailable, preserve previous non-None category values
    # rather than overwriting good CI data with None. Local-file-backed categories
    # (actor, actress, country, static sports) are always recomputed and take priority.
    if not _bulk_standings and prev.get('players'):
        prev_map = {p['name']: p for p in prev['players']}
        for player in data.get('players', []):
            prev_p = prev_map.get(player['name'], {})
            for cat, cat_data in player.get('categories', {}).items():
                if cat_data.get('raw_value') is None:
                    prev_cat = prev_p.get('categories', {}).get(cat, {})
                    if prev_cat.get('raw_value') is not None:
                        cat_data['raw_value']    = prev_cat['raw_value']
                        cat_data['rank']         = prev_cat.get('rank')
                        cat_data['baseline_pts'] = prev_cat.get('baseline_pts', 0)
        print('  ℹ Supabase unavailable — preserved previous values for live categories')

    # Build lookup of new scores/places
    new_totals = {p['name']: p['total'] for p in data.get('players', [])}
    new_places = {p['name']: p['place'] for p in data.get('players', [])}

    # 7-day rolling score history: update today's snapshot (overwrite if exists)
    today_utc = datetime.now(timezone.utc)
    today_str = today_utc.strftime('%Y-%m-%d')
    if score_history and score_history[-1].get('date') == today_str:
        score_history[-1] = {'date': today_str, 'totals': new_totals, 'places': new_places}
    else:
        score_history.append({'date': today_str, 'totals': new_totals, 'places': new_places})
    cutoff = (today_utc - timedelta(days=10)).strftime('%Y-%m-%d')
    score_history = [e for e in score_history if e.get('date', '') >= cutoff]
    target_date = (today_utc - timedelta(days=7)).strftime('%Y-%m-%d')
    baseline_entry = min(
        score_history,
        key=lambda e: abs(
            (datetime.strptime(e['date'], '%Y-%m-%d') -
             datetime.strptime(target_date, '%Y-%m-%d')).days
        )
    )
    data['score_history'] = score_history

    # Attach week-over-week deltas vs 7-day-ago baseline
    base_totals = baseline_entry.get('totals', {})
    base_places = baseline_entry.get('places', {})
    for p in data.get('players', []):
        name = p['name']
        if name in base_totals:
            p['week_delta'] = round(p['total'] - base_totals[name], 2)
            p['place_change'] = base_places.get(name, p['place']) - p['place']
        else:
            p['week_delta'] = None
            p['place_change'] = None

    with open(out_path, 'w') as f:
        json.dump(data, f)
    n = len(data.get('players', []))
    print(f'✓ Wrote {out_path}  ({n} players, last_updated={data.get("last_updated")})')
