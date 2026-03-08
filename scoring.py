"""
Fantasy Life 2026 — Scoring Engine
Handles baseline (rotisserie) + bonus point computation.
"""

import json
import os
from datetime import datetime

from draft_picks_2026 import DRAFT_PICKS_2026, PLAYERS, TENNIS_GENDER

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

# Bonus points per Amendment 7.14 (13-member inflation)
BONUS_POINTS = {
    'sports_championship': {
        'champion': 13,
        'runner_up': 9,
        'semi': 6.5,
        'quarter': 4,
        'round16': 2.5,
    },
    'tennis': {
        'major_win_men': 4,
        'major_runnerup_men': 2.5,
        'major_win_women': 4,     # disputed — Amendment 7.20
        'major_runnerup_women': 2.5,
    },
    'golf': {
        'major_win': 6,
        'major_runnerup': 2.5,
    },
    'oscar': {
        'lead_win': 13,
        'supporting_win': 9,
        'lead_nom': 4,
        'supporting_nom': 2.5,
    },
    'grammy': {
        'best_song_album_record': 7,
        'other_win': 3,
        'nomination': 1,
        'cap': 13,
    },
    'country': {  # Olympics / World Cup top 5
        1: 13, 2: 9, 3: 6.5, 4: 4, 5: 2.5,
    },
    'nascar': {
        1: 13, 2: 9, 3: 6.5, 4: 4, 5: 2.5,
    }
}


def load_data(category_key):
    """Load scraped data from JSON file"""
    path = os.path.join(DATA_DIR, f'{category_key}.json')
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def load_bonuses():
    """Load manually-entered bonus points"""
    path = os.path.join(DATA_DIR, 'bonuses.json')
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def rank_avg(values, reverse=True):
    """
    Compute RANK.AVG style ranks.
    values: dict of {name: numeric_value}
    reverse=True means higher value = better rank (rank 1)
    Returns dict of {name: rank_float} where rank 1 = best
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
    """Convert rank (1=best) to fantasy points. Rank 1 = 13 pts, Rank 13 = 1 pt."""
    return max(0, n - rank + 1)


def compute_baseline_sports(category, data_key, value_key, reverse=True):
    """
    Generic baseline scorer for sports with standings (NFL, NBA, MLB, NHL, MLS).
    Returns dict of {player: {pick, raw_value, rank, baseline_pts}}
    """
    picks = DRAFT_PICKS_2026.get(category, {})
    data = load_data(data_key)

    result = {}
    raw_values = {}

    for player, team in picks.items():
        raw = None
        if data:
            # Try to find the team in data
            for entry in data.get('standings', []):
                if team_matches(team, entry.get('team', '')):
                    raw = entry.get(value_key)
                    break
        raw_values[player] = raw if raw is not None else -1

    # Rank among players (exclude -1 / no data)
    valid = {p: v for p, v in raw_values.items() if v >= 0}
    if valid:
        ranks = rank_avg(valid, reverse=reverse)
    else:
        ranks = {}

    for player, team in picks.items():
        raw = raw_values[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        result[player] = {
            'pick': team,
            'raw_value': raw if raw >= 0 else None,
            'rank': rank,
            'baseline_pts': pts,
            'bonus_pts': 0,
        }
    return result


def compute_baseline_poll(category, data_key, reverse=False):
    """For NCAAF/NCAAB — lower AP poll rank number = better (rank 1 = #1 in poll)"""
    picks = DRAFT_PICKS_2026.get(category, {})
    data = load_data(data_key)

    result = {}
    raw_values = {}

    for player, team in picks.items():
        raw = None
        if data:
            for entry in data.get('poll', []):
                if team_matches(team, entry.get('team', '')):
                    raw = entry.get('rank')
                    break
        # Unranked = 26 (per 2025 spreadsheet convention)
        raw_values[player] = raw if raw is not None else 26

    # Lower poll rank number = better, so reverse=False means we want rank 1 poll = lowest value
    ranks = rank_avg(raw_values, reverse=False)

    for player, team in picks.items():
        raw = raw_values[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        result[player] = {
            'pick': team,
            'raw_value': raw if raw != 26 else None,
            'rank': rank,
            'baseline_pts': pts,
            'bonus_pts': 0,
        }
    return result


def compute_baseline_tennis():
    """
    Tennis: rank ATP/WTA by world ranking (lower = better).
    Women get adjusted rank = raw_rank + 0.5 (Amendment 7.4)
    """
    picks = DRAFT_PICKS_2026.get('Tennis', {})
    data = load_data('tennis')

    result = {}
    adjusted = {}

    for player, name in picks.items():
        raw = None
        gender = TENNIS_GENDER.get(name, 'M')
        if data:
            for entry in data.get('rankings', []):
                if name_matches(name, entry.get('player', '')):
                    raw = entry.get('rank')
                    break
        if raw is None:
            raw = 999  # unranked
        adj = raw + 0.5 if gender == 'F' else float(raw)
        adjusted[player] = adj

    ranks = rank_avg(adjusted, reverse=False)  # lower adj rank = better

    for player, name in picks.items():
        raw_adj = adjusted[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        result[player] = {
            'pick': name,
            'raw_value': raw_adj if raw_adj < 900 else None,
            'rank': rank,
            'baseline_pts': pts,
            'bonus_pts': 0,
            'gender': TENNIS_GENDER.get(name, 'M'),
        }
    return result


def compute_baseline_golf():
    """Golf: OWGR ranking, lower = better"""
    picks = DRAFT_PICKS_2026.get('Golf', {})
    data = load_data('golf')

    result = {}
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

    for player, name in picks.items():
        raw = raw_values[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        result[player] = {
            'pick': name,
            'raw_value': raw if raw < 900 else None,
            'rank': rank,
            'baseline_pts': pts,
            'bonus_pts': 0,
        }
    return result


def compute_baseline_nascar():
    """NASCAR: regular season points (higher = better), Week 26 cutoff"""
    picks = DRAFT_PICKS_2026.get('NASCAR', {})
    data = load_data('nascar')

    result = {}
    raw_values = {}

    for player, driver in picks.items():
        raw = None
        if data:
            for entry in data.get('standings', []):
                if name_matches(driver, entry.get('driver', '')):
                    raw = entry.get('points')
                    break
        raw_values[player] = raw if raw is not None else -1

    valid = {p: v for p, v in raw_values.items() if v >= 0}
    ranks = rank_avg(valid, reverse=True) if valid else {}

    for player, driver in picks.items():
        raw = raw_values[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        result[player] = {
            'pick': driver,
            'raw_value': raw if raw >= 0 else None,
            'rank': rank,
            'baseline_pts': pts,
            'bonus_pts': 0,
        }
    return result


def compute_baseline_actor_actress(category):
    """Actor/Actress: composite = sum of (box_office_$M × RT_score_decimal)"""
    picks = DRAFT_PICKS_2026.get(category, {})
    data = load_data(category.lower())

    result = {}
    raw_values = {}

    for player, name in picks.items():
        composite = None
        if data:
            for entry in data.get('scores', []):
                if name_matches(name, entry.get('name', '')):
                    composite = entry.get('composite_score')
                    break
        raw_values[player] = composite if composite is not None else -1

    valid = {p: v for p, v in raw_values.items() if v >= 0}
    ranks = rank_avg(valid, reverse=True) if valid else {}

    for player, name in picks.items():
        raw = raw_values[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        result[player] = {
            'pick': name,
            'raw_value': round(raw, 2) if raw >= 0 else None,
            'rank': rank,
            'baseline_pts': pts,
            'bonus_pts': 0,
        }
    return result


def compute_baseline_musician():
    """Musician: (2 × #1 weeks) + (1 × Hot 100 weeks)"""
    picks = DRAFT_PICKS_2026.get('Musician', {})
    data = load_data('musician')

    result = {}
    raw_values = {}

    for player, name in picks.items():
        score = None
        if data:
            for entry in data.get('scores', []):
                if name_matches(name, entry.get('artist', '')):
                    num1 = entry.get('num1_weeks', 0) or 0
                    hot100 = entry.get('hot100_weeks', 0) or 0
                    score = (2 * num1) + hot100
                    break
        raw_values[player] = score if score is not None else -1

    valid = {p: v for p, v in raw_values.items() if v >= 0}
    ranks = rank_avg(valid, reverse=True) if valid else {}

    for player, name in picks.items():
        raw = raw_values[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        result[player] = {
            'pick': name,
            'raw_value': raw if raw >= 0 else None,
            'rank': rank,
            'baseline_pts': pts,
            'bonus_pts': 0,
        }
    return result


def compute_baseline_country():
    """Country: GDP growth % (higher = better)"""
    picks = DRAFT_PICKS_2026.get('Country', {})
    data = load_data('country')

    result = {}
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

    valid = {p: v for p, v in raw_values.items() if v > -999}
    ranks = rank_avg(valid, reverse=True) if valid else {}

    for player, country in picks.items():
        raw = raw_values[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        result[player] = {
            'pick': country,
            'raw_value': raw if raw > -999 else None,
            'rank': rank,
            'baseline_pts': pts,
            'bonus_pts': 0,
        }
    return result


def compute_baseline_stock():
    """Stock: YTD % change. Long = today/jan1-1. Short = -(today/jan1-1)."""
    picks = DRAFT_PICKS_2026.get('Stock', {})
    data = load_data('stock')

    result = {}
    raw_values = {}

    for player, info in picks.items():
        ticker = info['ticker']
        direction = info['direction']
        pct_change = None
        if data:
            for entry in data.get('prices', []):
                if entry.get('ticker', '').upper() == ticker.upper():
                    today = entry.get('current_price')
                    jan1 = entry.get('jan1_price')
                    if today and jan1 and jan1 > 0:
                        raw_pct = (today / jan1 - 1)
                        pct_change = -raw_pct if direction == 'S' else raw_pct
                    break
        raw_values[player] = pct_change if pct_change is not None else -999

    valid = {p: v for p, v in raw_values.items() if v > -999}
    ranks = rank_avg(valid, reverse=True) if valid else {}

    for player, info in picks.items():
        raw = raw_values[player]
        rank = ranks.get(player)
        pts = rank_to_points(rank) if rank is not None else 0
        result[player] = {
            'pick': f"{info['ticker']} ({'Long' if info['direction']=='L' else 'Short'})",
            'raw_value': round(raw * 100, 2) if raw > -999 else None,
            'raw_display': f"{raw*100:+.1f}%" if raw > -999 else None,
            'rank': rank,
            'baseline_pts': pts,
            'bonus_pts': 0,
        }
    return result


def apply_bonuses(category_scores, bonuses, category):
    """Apply manually-entered bonus points to category scores."""
    cat_bonuses = bonuses.get(category, {})
    for player, bonus_pts in cat_bonuses.items():
        if player in category_scores:
            category_scores[player]['bonus_pts'] = bonus_pts
    return category_scores


def compute_all_scores():
    """Main scoring function — returns full leaderboard data."""
    bonuses = load_bonuses()

    categories = {
        'NFL':      lambda: compute_baseline_sports('NFL', 'nfl', 'win_pct'),
        'NBA':      lambda: compute_baseline_sports('NBA', 'nba', 'win_pct'),
        'MLB':      lambda: compute_baseline_sports('MLB', 'mlb', 'win_pct'),
        'NHL':      lambda: compute_baseline_sports('NHL', 'nhl', 'points_pct'),
        'NCAAF':    lambda: compute_baseline_poll('NCAAF', 'ncaaf'),
        'NCAAB':    lambda: compute_baseline_poll('NCAAB', 'ncaab'),
        'Tennis':   compute_baseline_tennis,
        'Golf':     compute_baseline_golf,
        'NASCAR':   compute_baseline_nascar,
        'MLS':      lambda: compute_baseline_sports('MLS', 'mls', 'points', reverse=True),
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

    # Aggregate per player
    player_totals = {}
    for player in PLAYERS:
        total = 0
        cat_breakdown = {}
        for cat, scores in all_cat_scores.items():
            p_data = scores.get(player, {})
            base = p_data.get('baseline_pts', 0) or 0
            bonus = p_data.get('bonus_pts', 0) or 0
            cat_total = base + bonus
            total += cat_total
            cat_breakdown[cat] = {
                'pick': p_data.get('pick', '—'),
                'raw_value': p_data.get('raw_value'),
                'raw_display': p_data.get('raw_display'),
                'rank': p_data.get('rank'),
                'baseline_pts': round(base, 2),
                'bonus_pts': round(bonus, 2),
                'total_pts': round(cat_total, 2),
            }
        player_totals[player] = {
            'name': player,
            'total': round(total, 2),
            'categories': cat_breakdown,
            'is_premium': player == 'Todd',
        }

    # Sort by total descending
    sorted_players = sorted(player_totals.values(), key=lambda x: x['total'], reverse=True)

    # Add rank
    for i, p in enumerate(sorted_players):
        p['place'] = i + 1

    return {
        'players': sorted_players,
        'last_updated': get_last_updated(),
        'season': 2026,
    }


def get_last_updated():
    """Get the most recent update timestamp across all data files."""
    if not os.path.exists(DATA_DIR):
        return None
    timestamps = []
    for f in os.listdir(DATA_DIR):
        if f.endswith('.json'):
            path = os.path.join(DATA_DIR, f)
            timestamps.append(os.path.getmtime(path))
    if not timestamps:
        return None
    latest = max(timestamps)
    return datetime.fromtimestamp(latest).strftime('%Y-%m-%d %H:%M UTC')


# --- Fuzzy matching helpers ---

def team_matches(pick_name, data_name):
    """Fuzzy team matching — handles nicknames, abbreviations."""
    if not pick_name or not data_name:
        return False
    pick = pick_name.lower().strip()
    data = data_name.lower().strip()

    # Direct or substring match
    if pick in data or data in pick:
        return True

    # Remove common words
    for word in ['fc', 'sc', 'city', 'united', 'the', 'de', 'af', 'afc']:
        pick = pick.replace(word, '').strip()
        data = data.replace(word, '').strip()

    if pick and data and (pick in data or data in pick):
        return True

    # Nickname mapping
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
        'lafc': 'los angeles fc', 'la galaxy': 'los angeles galaxy',
        'rory': 'rory mcilroy', 'rory mcilroy': 'rory mcilroy',
    }
    pick_norm = NICKNAMES.get(pick, pick)
    data_norm = NICKNAMES.get(data, data)
    return pick_norm in data_norm or data_norm in pick_norm


def name_matches(pick_name, data_name):
    """Fuzzy name matching for players."""
    if not pick_name or not data_name:
        return False
    pick = pick_name.lower().strip()
    data = data_name.lower().strip()
    if pick in data or data in pick:
        return True
    # Last name matching
    pick_last = pick.split()[-1] if pick.split() else pick
    data_last = data.split()[-1] if data.split() else data
    if len(pick_last) > 3 and (pick_last in data or data_last in pick):
        return True
    return False
