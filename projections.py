#!/usr/bin/env python3
"""
projections.py

Reads docs/scores.json, fetches Kalshi prediction-market odds for in-progress
categories, runs 10,000 Monte Carlo simulations, and writes
docs/projections.json with projected year-end scores and win/top-4 probabilities.

Run:  python3 projections.py
Env:  KALSHI_API_KEY  (optional; falls back to static odds if unset/unavailable)
"""
import json
import os
import math
import random
import datetime
import requests

SCORES_PATH      = os.path.join(os.path.dirname(__file__), "docs", "scores.json")
PROJECTIONS_PATH = os.path.join(os.path.dirname(__file__), "docs", "projections.json")
KALSHI_BASE      = "https://api.kalshi.com/trade-api/v2"
KALSHI_KEY       = os.environ.get("KALSHI_API_KEY", "")
N_SIMS           = 10_000

# ─── Draft picks (subsets needed for projection lookups) ──────────────────
NBA_PICKS = {
    "Tim": "Denver Nuggets",        "Wu": "San Antonio Spurs",
    "Jens": "Cleveland Cavaliers",  "Todd": "Minnesota Timberwolves",
    "Mitchell": "Golden State Warriors", "Shep": "Boston Celtics",
    "Theo": "Los Angeles Lakers",   "Feder": "Oklahoma City Thunder",
    "Fryar": "Los Angeles Clippers","Korch": "Houston Rockets",
    "Molmen": "Milwaukee Bucks",    "Jamzee": "Orlando Magic",
    "Buckley": "New York Knicks",
}
NHL_PICKS = {
    "Tim": "Vegas Golden Knights",  "Wu": "New Jersey Devils",
    "Jens": "Toronto Maple Leafs",  "Todd": "Florida Panthers",
    "Mitchell": "Dallas Stars",     "Shep": "Boston Bruins",
    "Theo": "Detroit Red Wings",    "Feder": "Washington Capitals",
    "Fryar": "Tampa Bay Lightning", "Korch": "Colorado Avalanche",
    "Molmen": "New York Rangers",   "Jamzee": "Carolina Hurricanes",
    "Buckley": "Edmonton Oilers",
}
MLB_PICKS = {
    "Tim": "Chicago Cubs",          "Wu": "Los Angeles Dodgers",
    "Jens": "New York Yankees",     "Todd": "Atlanta Braves",
    "Mitchell": "Philadelphia Phillies", "Shep": "Houston Astros",
    "Theo": "San Diego Padres",     "Feder": "New York Mets",
    "Fryar": "Cleveland Guardians", "Korch": "Toronto Blue Jays",
    "Molmen": "Texas Rangers",      "Jamzee": "Seattle Mariners",
    "Buckley": "Milwaukee Brewers",
}
MLS_PICKS = {
    "Tim": "Charlotte FC",          "Wu": "Minnesota United",
    "Jens": "San Diego FC",         "Todd": "New York Red Bulls",
    "Mitchell": "Philadelphia Union","Shep": "Orlando City",
    "Theo": "Inter Miami",          "Feder": "Vancouver Whitecaps",
    "Fryar": "Columbus Crew",       "Korch": "FC Cincinnati",
    "Molmen": "LA Galaxy",          "Jamzee": "Seattle Sounders",
    "Buckley": "LAFC",
}
NASCAR_PICKS = {
    "Tim": "Bubba Wallace",         "Wu": "Christopher Bell",
    "Jens": "Chase Briscoe",        "Todd": "Chase Elliott",
    "Mitchell": "Shane van Gisbergen","Shep": "Daniel Suarez",
    "Theo": "Denny Hamlin",         "Feder": "Tyler Reddick",
    "Fryar": "Ryan Blaney",         "Korch": "William Byron",
    "Molmen": "Kyle Larson",        "Jamzee": "Joey Logano",
    "Buckley": "Ross Chastain",
}
GOLF_PICKS = {
    "Tim": "Xander Schauffele",     "Wu": "Scottie Scheffler",
    "Jens": "Russell Henley",       "Todd": "Patrick Cantlay",
    "Mitchell": "J.J. Spaun",       "Shep": "Jon Rahm",
    "Theo": "Justin Thomas",        "Feder": "Bryson DeChambeau",
    "Fryar": "Viktor Hovland",      "Korch": "Tommy Fleetwood",
    "Molmen": "Rory McIlroy",       "Jamzee": "Ludvig Aberg",
    "Buckley": "Collin Morikawa",
}
# Tennis: men's and women's tracked separately
TENNIS_MEN = {
    "Todd": "Carlos Alcaraz",   "Shep": "Novak Djokovic",
    "Theo": "Alexander Zverev", "Molmen": "Daniil Medvedev",
    "Mitchell": "Taylor Fritz", "Buckley": "Jannik Sinner",
}
TENNIS_WOMEN = {
    "Tim": "Madison Keys",      "Wu": "Coco Gauff",
    "Jens": "Jasmine Paolini",  "Feder": "Iga Swiatek",
    "Fryar": "Aryna Sabalenka", "Korch": "Jessica Pegula",
    "Jamzee": "Amanda Anisimova",
}

# ─── Upcoming 2026 film pipeline (Actor / Actress simulation) ─────────────────
# box_office: (p10, p50, p90) domestic gross in $M  — lognormal distribution
# rt:         (p10, p50, p90) Rotten Tomatoes score — normal distribution, capped 0–100
# actor/actress: {player_key: role_factor}  (1.0=lead, 0.5=supporting, 0.25=cameo)
FILM_PIPELINE = [
    {
        "title": "Mandalorian & Grogu",
        "box_office": (200, 300, 400),
        "rt": (65, 74, 85),
        "actor":   {"Mitchell": 1.0, "Shep": 0.5},
        "actress": {},
    },
    {
        "title": "Moana",
        "box_office": (130, 190, 260),
        "rt": (48, 62, 75),
        "actor":   {"Theo": 1.0},
        "actress": {},
    },
    {
        "title": "The Odyssey",
        "box_office": (175, 275, 375),
        "rt": (78, 88, 96),
        "actor":   {"Molmen": 1.0, "Feder": 1.0, "Buckley": 1.0, "Korch": 1.0},
        "actress": {"Korch": 1.0, "Wu": 1.0, "Mitchell": 1.0},
    },
    {
        "title": "Spider-Man: Brand New Day",
        "box_office": (450, 750, 1100),
        "rt": (72, 84, 94),
        "actor":   {"Feder": 1.0},
        "actress": {"Wu": 1.0},
    },
    {
        "title": "The Social Reckoning",
        "box_office": (50, 90, 150),
        "rt": (78, 89, 97),
        "actor":   {"Shep": 1.0},
        "actress": {},
    },
    {
        "title": "Flowervale Street",
        "box_office": (15, 35, 60),
        "rt": (62, 75, 88),
        "actor":   {},
        "actress": {"Korch": 1.0},
    },
    {
        "title": "Verity",
        "box_office": (40, 75, 110),
        "rt": (55, 68, 80),
        "actor":   {},
        "actress": {"Korch": 1.0},
    },
    {
        "title": "Avengers: Doomsday",
        "box_office": (350, 500, 700),
        "rt": (68, 80, 90),
        "actor":   {"Mitchell": 1.0, "Fryar": 0.25},
        "actress": {"Fryar": 1.0},
    },
    {
        "title": "Dune: Part Three",
        "box_office": (180, 280, 400),
        "rt": (82, 91, 97),
        "actor":   {"Jamzee": 1.0, "Buckley": 1.0},
        "actress": {"Wu": 0.5, "Fryar": 1.0, "Buckley": 1.0},
    },
    {
        "title": "Focker-in-Law",
        "box_office": (55, 95, 145),
        "rt": (40, 58, 72),
        "actor":   {},
        "actress": {"Tim": 1.0},
    },
    {
        "title": "Jumanji",
        "box_office": (120, 175, 240),
        "rt": (60, 72, 80),
        "actor":   {"Theo": 1.0},
        "actress": {},
    },
]

# ─── Stock simulation parameters ─────────────────────────────────────────────
# (expected_additional_return_pct, std_dev_pct) for rest of 2026 (~7 months).
# Values are from the PLAYER's perspective: positive = good for the pick.
# For SHORT positions this is already sign-flipped (CVNA short: +5 means CVNA
# expected to fall another 5%).
STOCK_SIM = {
    "Jamzee": (-10.0, 40.0),  # INTC Long: at +172%, mean-reversion risk
    "Mitchell": ( 5.0, 50.0), # CVNA Short: volatile, expected continued decline
    "Fryar":   ( 8.0, 25.0),  # AVGO Long: strong semiconductor fundamentals
    "Todd":    (12.0, 30.0),  # NVDA Long: AI spending still accelerating
    "Shep":    (-5.0, 40.0),  # TSLA Short: recovery risk for short position
    "Buckley": ( 3.0, 15.0),  # NEE Long: stable regulated utility
    "Korch":   ( 5.0, 45.0),  # SMCI Long: high volatility AI server play
    "Molmen":  (15.0, 25.0),  # TTWO Long: GTA VI launch catalyst
    "Theo":    ( 5.0, 18.0),  # CMG Long: steady restaurant recovery
    "Feder":   (15.0, 35.0),  # PLTR Long: AI/government data momentum
    "Tim":     ( 5.0, 45.0),  # COIN Long: crypto correlation, high vol
    "Wu":      ( 8.0, 25.0),  # LULU Long: athleisure recovery from lows
    "Jens":    (10.0, 35.0),  # SOFI Long: fintech recovery potential
}

# ─── Country simulation parameters ───────────────────────────────────────────
# (expected_revision_pct, std_dev_pct): models uncertainty in the October 2026
# IMF WEO GDP growth forecast revision relative to the current April 2026 forecast.
COUNTRY_SIM = {
    "Korch":    ( 0.0,  5.0),  # Guyana: oil-driven boom, can miss projections
    "Todd":     ( 0.0,  3.0),  # Guinea: small economy, moderate forecast risk
    "Jamzee":   ( 0.0,  0.8),  # Spain: stable EU, tight revision band
    "Feder":    ( 0.0,  1.5),  # Brazil: emerging market, moderate uncertainty
    "Wu":       ( 0.0,  0.4),  # United States: large stable, IMF rarely revises much
    "Fryar":    ( 0.0,  0.8),  # Norway: small stable open economy
    "Buckley":  ( 0.0,  0.5),  # Canada: closely correlated to US
    "Theo":     ( 0.0,  0.4),  # Switzerland: very stable, tight revision band
    "Shep":     ( 0.0,  0.4),  # France: stable EU economy
    "Tim":      ( 0.0,  0.4),  # Netherlands: stable EU economy
    "Jens":     ( 0.5,  0.8),  # Germany: in recession, slight upside bias
    "Molmen":   ( 0.5,  5.0),  # Argentina: Milei reforms → high uncertainty
    "Mitchell": ( 0.0,  8.0),  # South Sudan: conflict economy, extreme uncertainty
}

# ─── Bonus milestone values ─────────────────────────────────────────────────
MILESTONES = {
    "champion": 13.0, "runner_up": 9.0, "semi": 6.5,
    "quarter": 4.0,   "round16": 2.5,   "none": 0.0,
}

# ─── Kalshi API ──────────────────────────────────────────────────────────────
def _kalshi_get(path, params=None):
    if not KALSHI_KEY:
        return None
    try:
        r = requests.get(
            f"{KALSHI_BASE}{path}",
            headers={"Authorization": f"Bearer {KALSHI_KEY}", "Accept": "application/json"},
            params=params or {},
            timeout=8,
        )
        if r.status_code == 200:
            return r.json()
        print(f"  ✗ Kalshi {path}: HTTP {r.status_code}")
    except Exception as e:
        print(f"  ✗ Kalshi {path}: {e}")
    return None


def _fetch_markets_for_series(series_ticker):
    data = _kalshi_get("/markets", {"series_ticker": series_ticker, "limit": 200, "status": "open"})
    return data.get("markets", []) if data else []


def _name_matches(kalshi_title, pick_name):
    """True if any word ≥4 chars from pick_name appears in kalshi_title (case-insensitive)."""
    title = kalshi_title.lower()
    for word in pick_name.split():
        if len(word) >= 4 and word.lower() in title:
            return True
    return False


def _extract_probs(markets, picks_dict):
    """
    Given a list of Kalshi markets and a {player: pick_name} dict,
    return {player: yes_ask_probability (0–1)}.
    Uses the midpoint of bid/ask when both are present, else yes_ask alone.
    """
    probs = {}
    for player, pick in picks_dict.items():
        for m in markets:
            if _name_matches(m.get("title", ""), pick):
                yes_ask = m.get("yes_ask")
                yes_bid = m.get("yes_bid")
                if yes_ask is not None and yes_bid is not None:
                    probs[player] = (yes_ask + yes_bid) / 200.0
                elif yes_ask is not None:
                    probs[player] = yes_ask / 100.0
                break
    return probs


def fetch_kalshi_championship_probs(series_ticker, picks_dict, label):
    """Fetch win-probability dict {player: float} from Kalshi, or {} on failure."""
    markets = _fetch_markets_for_series(series_ticker)
    if not markets:
        print(f"  ℹ {label}: no Kalshi markets found for series '{series_ticker}'")
        return {}
    probs = _extract_probs(markets, picks_dict)
    if probs:
        found = ", ".join(f"{p}={v:.1%}" for p, v in sorted(probs.items()))
        print(f"  ✓ Kalshi {label}: {found}")
    else:
        print(f"  ℹ Kalshi {label}: markets found but no picks matched")
    return probs


# ─── Static fallback odds (as of 2026-05-20) ─────────────────────────────────
# Championship win probabilities for each pick.
# "OTHER" = probability the winner is a team/player not in any pick.

FALLBACK = {
    # NBA Conference Finals (all 4 remaining teams are picks — no OTHER)
    "nba_champ": {
        "Wu": 0.35, "Feder": 0.27, "Buckley": 0.22, "Jens": 0.16,
    },
    # NBA: which player's team reaches Finals (needed for runner_up modelling)
    # WCF: Wu (Spurs) vs Feder (Thunder) — roughly 56/44
    # ECF: Buckley (Knicks) vs Jens (Cavaliers) — roughly 55/45
    "nba_conf_finals_west": {"Wu": 0.56, "Feder": 0.44},
    "nba_conf_finals_east": {"Buckley": 0.55, "Jens": 0.45},

    # NHL Conference Finals (Tim & Korch in WCF; Jamzee + unknown in ECF)
    "nhl_champ": {
        "Korch": 0.34, "Tim": 0.29, "Jamzee": 0.20,  # ~17% to OTHER team
    },
    "nhl_conf_finals_west": {"Korch": 0.58, "Tim": 0.42},
    "nhl_conf_finals_east": {"Jamzee": 0.55},  # 0.45 to OTHER

    # MLB World Series (regular season, May 2026)
    "mlb_champ": {
        "Wu": 0.16, "Jens": 0.12, "Todd": 0.08, "Mitchell": 0.07,
        "Shep": 0.06, "Feder": 0.05, "Theo": 0.04, "Tim": 0.04,
        "Korch": 0.03, "Fryar": 0.03, "Jamzee": 0.03, "Buckley": 0.03,
        "Molmen": 0.02,  # ~24% OTHER
    },
    # MLS Cup (regular season)
    "mls_champ": {
        "Molmen": 0.09, "Buckley": 0.08, "Theo": 0.08,
        "Feder": 0.07, "Jamzee": 0.06, "Korch": 0.06, "Fryar": 0.05,
        "Mitchell": 0.04, "Todd": 0.04, "Wu": 0.04,
        "Shep": 0.03, "Tim": 0.03, "Jens": 0.03,  # ~30% OTHER
    },
    # NASCAR Cup Series
    "nascar_champ": {
        "Molmen": 0.14, "Korch": 0.11, "Theo": 0.09, "Fryar": 0.08,
        "Todd": 0.07, "Mitchell": 0.05, "Feder": 0.05, "Wu": 0.04,
        "Jamzee": 0.04, "Buckley": 0.03, "Jens": 0.03,
        "Shep": 0.02, "Tim": 0.02,  # ~23% OTHER
    },

    # Golf: win probability per major per pick
    "golf_us_open_win": {
        "Wu": 0.14, "Tim": 0.08, "Feder": 0.07, "Molmen": 0.10,
        "Buckley": 0.07, "Korch": 0.06, "Shep": 0.05, "Jens": 0.05,
        "Mitchell": 0.04, "Jamzee": 0.04, "Theo": 0.03, "Fryar": 0.03, "Todd": 0.03,
    },
    "golf_the_open_win": {
        "Wu": 0.13, "Molmen": 0.12, "Korch": 0.08, "Shep": 0.08,
        "Buckley": 0.07, "Tim": 0.06, "Feder": 0.05, "Fryar": 0.04,
        "Jamzee": 0.04, "Jens": 0.04, "Theo": 0.03, "Mitchell": 0.03, "Todd": 0.03,
    },
    # runner-up ≈ 1.35 × win, capped and independently sampled
    "golf_us_open_ru_mult":  1.35,
    "golf_the_open_ru_mult": 1.35,

    # Tennis: win probability per remaining slam
    # French Open (Alcaraz withdrew; men's: Zverev/Sinner/Djokovic; women's: Swiatek/Sabalenka/Gauff)
    "tennis_french_men_win": {
        "Buckley": 0.12, "Theo": 0.12, "Shep": 0.09,
        "Molmen": 0.06, "Mitchell": 0.03,
        # Todd (Alcaraz) withdrew — 0%
    },
    "tennis_french_women_win": {
        "Feder": 0.26, "Fryar": 0.18, "Wu": 0.09,
        "Tim": 0.05, "Jens": 0.06, "Korch": 0.04, "Jamzee": 0.03,
    },
    "tennis_wimbledon_men_win": {
        "Todd": 0.20, "Buckley": 0.15, "Shep": 0.12, "Theo": 0.08,
        "Molmen": 0.05, "Mitchell": 0.04,
    },
    "tennis_wimbledon_women_win": {
        "Feder": 0.12, "Fryar": 0.10, "Wu": 0.06, "Jens": 0.04,
        "Tim": 0.04, "Korch": 0.03, "Jamzee": 0.03,
    },
    "tennis_usopen_men_win": {
        "Buckley": 0.13, "Todd": 0.12, "Shep": 0.08, "Theo": 0.07,
        "Molmen": 0.05, "Mitchell": 0.04,
    },
    "tennis_usopen_women_win": {
        "Feder": 0.12, "Fryar": 0.12, "Wu": 0.08, "Tim": 0.06,
        "Korch": 0.05, "Jens": 0.04, "Jamzee": 0.04,
    },
    "tennis_ru_mult": 1.30,  # runner-up ≈ 1.30 × win for all slams
}


# ─── Odds helpers ─────────────────────────────────────────────────────────────
def _merge_probs(kalshi_probs, fallback_probs):
    """Use Kalshi if we got any data, otherwise fallback. Log the source."""
    if kalshi_probs:
        return kalshi_probs, "kalshi"
    return fallback_probs, "fallback"


def _normalize(probs):
    """Return a copy of probs normalized so values sum to ≤ 1 (capped at 1)."""
    total = sum(probs.values())
    if total <= 0:
        return probs
    scale = min(1.0, 1.0 / total)
    return {k: v * scale for k, v in probs.items()}


def _other_prob(probs):
    """Probability that the winner is not any of our picks."""
    return max(0.0, 1.0 - sum(probs.values()))


def _weighted_sample(probs):
    """
    Sample one key from probs dict (or None for 'other').
    probs: {key: probability}, need not sum to 1 — remaining goes to OTHER.
    """
    r = random.random()
    cumulative = 0.0
    for key, p in probs.items():
        cumulative += p
        if r < cumulative:
            return key
    return None  # OTHER (no pick wins)


# ─── Film composite helpers ───────────────────────────────────────────────────
def _sample_lognormal(p10, p50, p90):
    """Sample from lognormal defined by (p10, median, p90) percentile anchors."""
    mu = math.log(p50)
    sigma = math.log(p90 / p10) / (2 * 1.28)
    return math.exp(random.gauss(mu, sigma))


def _sample_normal_capped(p10, p50, p90, lo=0.0, hi=100.0):
    """Sample from normal distribution anchored at (p10, p50, p90), capped at [lo, hi]."""
    sigma = (p90 - p10) / (2 * 1.28)
    return max(lo, min(hi, random.gauss(p50, sigma)))


def _expected_lognormal(p10, p50, p90):
    """E[X] for lognormal parameterized by (p10, median, p90)."""
    mu = math.log(p50)
    sigma = math.log(p90 / p10) / (2 * 1.28)
    return math.exp(mu + 0.5 * sigma * sigma)


def _rank_composites(players_list, comp_dict):
    """
    Rank players by composite score, averaging ranks for ties.
    Returns {player: baseline_pts} where rank 1 → 13 pts, rank 13 → 1 pt.
    """
    sorted_p = sorted(players_list, key=lambda x: -comp_dict.get(x, 0.0))
    pts = {}
    i = 0
    while i < len(sorted_p):
        j = i
        val = comp_dict.get(sorted_p[i], 0.0)
        while j < len(sorted_p) and comp_dict.get(sorted_p[j], 0.0) == val:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        avg_pts = max(0.0, 14.0 - avg_rank)
        for k in range(i, j):
            pts[sorted_p[k]] = avg_pts
        i = j
    return pts


# ─── Expected bonus helpers ──────────────────────────────────────────────────
def _expected_bonus_preseason(p_champ):
    """
    Expected bonus for a team with championship probability p_champ and no
    current bonus (regular season / pre-playoff).
    Approximation: E[bonus] ≈ 46.5 × p_champ  (sum of tier-prob × tier-value).
    """
    return 46.5 * p_champ


def _expected_bonus_conf_finals(p_champ, p_finalist):
    """
    Expected ADDITIONAL bonus for a team currently at semi (6.5) in conf finals.
    E[additional] = p_champ × 4 + p_finalist × 2.5   (over current 6.5)
    """
    return p_champ * 4.0 + p_finalist * 2.5


# ─── Kalshi fetch + merge ─────────────────────────────────────────────────────
KNOWN_SERIES = {
    # Kalshi series tickers to try; fallback gracefully if 403/empty.
    "nba":    ["NBACHAMP", "KXNBA",  "NBA-CHAMPION"],
    "nhl":    ["NHLCHAMP", "KXNHL",  "NHL-CUP"],
    "mlb":    ["MLBCHAMP", "KXMLB",  "MLB-WS"],
    "mls":    ["MLSCUP",   "KXMLS"],
    "nascar": ["NASCARWIN","KXNASC", "NASCAR-CUP"],
    "golf_uso": ["KXGOLF-USO", "GOLF-USO"],
    "golf_open": ["KXGOLF-OPEN", "GOLF-THEOPEN"],
    "tennis_fo_m": ["TENNISFO-M", "RG-MEN"],
    "tennis_fo_w": ["TENNISFO-W", "RG-WOMEN"],
    "tennis_wb_m": ["TENNISWB-M", "WIM-MEN"],
    "tennis_wb_w": ["TENNISWB-W", "WIM-WOMEN"],
    "tennis_uso_m": ["TENNISUSO-M", "USO-MEN"],
    "tennis_uso_w": ["TENNISUSO-W", "USO-WOMEN"],
}


def _try_kalshi_series(series_list, picks_dict, label):
    for ticker in series_list:
        result = fetch_kalshi_championship_probs(ticker, picks_dict, label)
        if result:
            return result
    return {}


def build_odds(markets_used):
    """
    Fetch all category odds from Kalshi; fall back to statics.
    Returns a big dict of {category_key: {player: probability}}.
    """
    odds = {}

    def get(key, picks, series_key, label):
        kalshi = _try_kalshi_series(KNOWN_SERIES[series_key], picks, label)
        merged, source = _merge_probs(kalshi, FALLBACK[key])
        if source == "kalshi":
            markets_used.append(label)
        return merged

    odds["nba_champ"]           = get("nba_champ", NBA_PICKS, "nba", "NBA-championship")
    odds["nba_conf_finals_west"] = FALLBACK["nba_conf_finals_west"]
    odds["nba_conf_finals_east"] = FALLBACK["nba_conf_finals_east"]
    odds["nhl_champ"]           = get("nhl_champ", NHL_PICKS, "nhl", "NHL-StanleyCup")
    odds["nhl_conf_finals_west"] = FALLBACK["nhl_conf_finals_west"]
    odds["nhl_conf_finals_east"] = FALLBACK["nhl_conf_finals_east"]
    odds["mlb_champ"]           = get("mlb_champ", MLB_PICKS, "mlb", "MLB-WorldSeries")
    odds["mls_champ"]           = get("mls_champ", MLS_PICKS, "mls", "MLS-Cup")
    odds["nascar_champ"]        = get("nascar_champ", NASCAR_PICKS, "nascar", "NASCAR-Cup")

    # Golf
    golf_uso_w = get("golf_us_open_win", GOLF_PICKS, "golf_uso", "Golf-USOpen-win")
    golf_open_w = get("golf_the_open_win", GOLF_PICKS, "golf_open", "Golf-TheOpen-win")
    odds["golf_uso_win"]  = golf_uso_w
    odds["golf_open_win"] = golf_open_w
    odds["golf_uso_ru"]   = {p: min(v * FALLBACK["golf_us_open_ru_mult"], 0.25)
                             for p, v in golf_uso_w.items()}
    odds["golf_open_ru"]  = {p: min(v * FALLBACK["golf_the_open_ru_mult"], 0.25)
                             for p, v in golf_open_w.items()}

    # Tennis
    for key, picks, series_key, label in [
        ("tennis_french_men_win",  TENNIS_MEN,   "tennis_fo_m",  "Tennis-FO-Men"),
        ("tennis_french_women_win",TENNIS_WOMEN, "tennis_fo_w",  "Tennis-FO-Women"),
        ("tennis_wimbledon_men_win",TENNIS_MEN,  "tennis_wb_m",  "Tennis-Wimbledon-Men"),
        ("tennis_wimbledon_women_win",TENNIS_WOMEN,"tennis_wb_w", "Tennis-Wimbledon-Women"),
        ("tennis_usopen_men_win",  TENNIS_MEN,   "tennis_uso_m", "Tennis-USO-Men"),
        ("tennis_usopen_women_win",TENNIS_WOMEN, "tennis_uso_w", "Tennis-USO-Women"),
    ]:
        w = get(key, picks, series_key, label)
        odds[key] = w
        ru_key = key.replace("_win", "_ru")
        odds[ru_key] = {p: min(v * FALLBACK["tennis_ru_mult"], 0.30) for p, v in w.items()}

    return odds


# ─── Expected additional points (deterministic) ──────────────────────────────
def compute_expected_additional(current_scores, odds):
    """
    For each player, compute expected additional points from live categories.
    Returns {player: {category: expected_additional_pts}}.
    """
    players = {p["name"]: p for p in current_scores}
    result = {name: {} for name in players}

    # ── NBA ──────────────────────────────────────────────────────────────────
    nba_champ = _normalize(odds["nba_champ"])
    west = odds["nba_conf_finals_west"]
    east = odds["nba_conf_finals_east"]
    for player, pick in NBA_PICKS.items():
        current_bonus = players[player]["categories"].get("nba", {}).get("bonus_pts", 0)
        p_champ = nba_champ.get(player, 0)
        if current_bonus >= 6.5:
            # In conference finals → model finalist and champion probabilities
            if player in west:
                p_finalist = west[player]
            elif player in east:
                p_finalist = east[player]
            else:
                p_finalist = 2 * p_champ  # rough estimate
            additional = _expected_bonus_conf_finals(p_champ, p_finalist)
        elif current_bonus >= 2.5:
            additional = 0.0  # already eliminated
        else:
            additional = _expected_bonus_preseason(p_champ)
        result[player]["nba"] = additional

    # ── NHL ──────────────────────────────────────────────────────────────────
    nhl_champ = _normalize(odds["nhl_champ"])
    nhl_west = odds["nhl_conf_finals_west"]
    nhl_east = odds["nhl_conf_finals_east"]
    for player, pick in NHL_PICKS.items():
        current_bonus = players[player]["categories"].get("nhl", {}).get("bonus_pts", 0)
        p_champ = nhl_champ.get(player, 0)
        if current_bonus >= 6.5:
            if player in nhl_west:
                p_finalist = nhl_west[player]
            elif player in nhl_east:
                p_finalist = nhl_east.get(player, 0.50)
            else:
                p_finalist = 2 * p_champ
            additional = _expected_bonus_conf_finals(p_champ, p_finalist)
        elif current_bonus >= 2.5:
            additional = 0.0
        else:
            additional = _expected_bonus_preseason(p_champ)
        result[player]["nhl"] = additional

    # ── MLB / MLS / NASCAR (pre-playoff, use preseason formula) ──────────────
    for cat, picks_dict, key in [
        ("mlb",    MLB_PICKS,    "mlb_champ"),
        ("mls",    MLS_PICKS,    "mls_champ"),
        ("nascar", NASCAR_PICKS, "nascar_champ"),
    ]:
        champ_probs = _normalize(odds[key])
        for player in picks_dict:
            p_champ = champ_probs.get(player, 0)
            result[player][cat] = _expected_bonus_preseason(p_champ)

    # ── Golf (2 remaining majors, additive) ──────────────────────────────────
    golf_pairs = [
        (odds["golf_uso_win"],  odds["golf_uso_ru"],  6.0, 2.5),
        (odds["golf_open_win"], odds["golf_open_ru"],  6.0, 2.5),
    ]
    for player in GOLF_PICKS:
        total = 0.0
        for win_probs, ru_probs, win_pts, ru_pts in golf_pairs:
            p_win = win_probs.get(player, 0)
            p_ru  = ru_probs.get(player, 0)
            total += p_win * win_pts + p_ru * ru_pts
        result[player]["golf"] = total

    # ── Tennis (3 remaining slams × 2 genders, additive) ─────────────────────
    tennis_pairs = [
        ("tennis_french_men_win",    "tennis_french_men_ru",    4.0, 2.5),
        ("tennis_french_women_win",  "tennis_french_women_ru",  4.0, 2.5),
        ("tennis_wimbledon_men_win", "tennis_wimbledon_men_ru",  4.0, 2.5),
        ("tennis_wimbledon_women_win","tennis_wimbledon_women_ru",4.0, 2.5),
        ("tennis_usopen_men_win",    "tennis_usopen_men_ru",    4.0, 2.5),
        ("tennis_usopen_women_win",  "tennis_usopen_women_ru",  4.0, 2.5),
    ]
    all_tennis = {**TENNIS_MEN, **TENNIS_WOMEN}
    for player in all_tennis:
        total = 0.0
        for wk, rk, wp, rp in tennis_pairs:
            p_win = odds.get(wk, {}).get(player, 0)
            p_ru  = odds.get(rk, {}).get(player, 0)
            total += p_win * wp + p_ru * rp
        result[player]["tennis"] = total

    # ── Actor / Actress: expected composite from upcoming films → rank delta ──
    players_list = list(players.keys())
    for cat in ("actor", "actress"):
        # Start from current composites (already-released films)
        composites = {
            name: (players[name]["categories"].get(cat, {}).get("raw_value") or 0.0)
            for name in players_list
        }
        # Add expected composite from each upcoming film (E[lognormal] × median RT/100)
        for film in FILM_PIPELINE:
            e_box = _expected_lognormal(*film["box_office"])
            e_rt  = film["rt"][1]  # median RT as point estimate
            e_contrib = (e_rt / 100.0) * e_box
            for player, factor in film[cat].items():
                composites[player] = composites.get(player, 0.0) + e_contrib * factor
        # Rank by expected composite → pts
        expected_pts = _rank_composites(players_list, composites)
        # Delta vs current baseline_pts (bonus_pts stay frozen)
        for name in players_list:
            current_base = players[name]["categories"].get(cat, {}).get("baseline_pts") or 0.0
            result[name][cat] = expected_pts.get(name, 0.0) - current_base

    # ── Stock: expected rank delta from remaining-year return distributions ───
    stock_exp = {}
    for player in STOCK_SIM:
        current = players[player]["categories"].get("stock", {}).get("raw_value") or 0.0
        exp_add, _ = STOCK_SIM[player]
        stock_exp[player] = current + exp_add
    expected_stock_pts = _rank_composites(players_list, stock_exp)
    for name in players_list:
        current_base = players[name]["categories"].get("stock", {}).get("baseline_pts") or 0.0
        result[name]["stock"] = expected_stock_pts.get(name, 0.0) - current_base

    # ── Country: expected rank delta from Oct 2026 IMF revision ─────────────
    country_exp = {}
    for player in COUNTRY_SIM:
        current = players[player]["categories"].get("country", {}).get("raw_value") or 0.0
        exp_rev, _ = COUNTRY_SIM[player]
        country_exp[player] = current + exp_rev
    expected_country_pts = _rank_composites(players_list, country_exp)
    for name in players_list:
        current_base = players[name]["categories"].get("country", {}).get("baseline_pts") or 0.0
        result[name]["country"] = expected_country_pts.get(name, 0.0) - current_base

    return result


# ─── Monte Carlo simulation ───────────────────────────────────────────────────
def _sample_major(win_probs, ru_probs):
    """
    Sample (winner, runner_up) for a single major.
    Returns (winner_player_or_None, runner_up_player_or_None).
    """
    winner = _weighted_sample(win_probs)
    ru_pool = {p: v for p, v in ru_probs.items() if p != winner}
    runner_up = _weighted_sample(ru_pool)
    return winner, runner_up


def _sample_playoff_sport(champ_probs):
    """
    Sample full playoff results for one sport given championship odds.
    Returns {player: bonus_pts}: champion=13, runner_up=9, semis=6.5.
    Remaining probability goes to OTHER teams at each stage.
    """
    results = {}
    remaining = dict(champ_probs)

    champion = _weighted_sample(remaining)
    if champion:
        results[champion] = 13.0
        remaining.pop(champion)

    runner_up = _weighted_sample(remaining)
    if runner_up:
        results[runner_up] = 9.0
        remaining.pop(runner_up)

    for _ in range(2):
        if not remaining:
            break
        semi = _weighted_sample(remaining)
        if semi:
            results[semi] = 6.5
            remaining.pop(semi)

    return results


def _simulate_playoffs_conf(conf_west_probs, conf_east_probs, champ_probs):
    """
    Simulate a conference-finals-style playoff (NBA or NHL).
    Returns {player: final_milestone} for the 4 remaining picks.
    West winner beats East winner in finals; champion is determined by
    relative championship probabilities.
    """
    west_players = list(conf_west_probs.keys())
    west_winner = _weighted_sample(conf_west_probs) or west_players[0]
    west_loser = west_players[1] if west_winner == west_players[0] else west_players[0]

    # ECF may include an "OTHER" team (not a pick)
    east_pick_players = list(conf_east_probs.keys())
    p_other_east = max(0.0, 1.0 - sum(conf_east_probs.values()))
    if random.random() < p_other_east:
        east_winner = None  # OTHER team wins ECF
    else:
        east_winner = _weighted_sample(conf_east_probs) or (east_pick_players[0] if east_pick_players else None)
    east_pick_losers = [p for p in east_pick_players if p != east_winner]

    results = {}

    # Conference losers stay at semi (no change)
    results[west_loser] = "semi"
    for p in east_pick_losers:
        results[p] = "semi"

    # Determine Finals: west_winner vs east_winner (or OTHER)
    # Weight champion by relative championship odds
    p_west_champ = champ_probs.get(west_winner, 0) if west_winner else 0
    p_east_champ = champ_probs.get(east_winner, 0) if east_winner else 0
    total = p_west_champ + p_east_champ
    if total > 0 and random.random() < p_west_champ / total:
        champion = west_winner
        runner_up = east_winner
    else:
        champion = east_winner
        runner_up = west_winner

    if champion and champion != "OTHER":
        results[champion] = "champion"
    if runner_up and runner_up != "OTHER" and runner_up in NBA_PICKS or runner_up in NHL_PICKS:
        results[runner_up] = "runner_up"

    return results


def simulate(current_scores, odds, n=N_SIMS):
    """
    Run n Monte Carlo simulations.
    Returns {player: {win_pct, top4_pct, projected_total, projected_p10, projected_p90, ...}}.
    """
    players_list = [p["name"] for p in current_scores]

    # Base totals: strip the portions we re-sample each run.
    # Sports: subtract bonus_pts only (baseline rank is frozen).
    # Actor/Actress/Stock/Country: subtract baseline_pts (ranking re-simulated);
    #   bonus_pts stay frozen (already earned).
    base = {}
    for p in current_scores:
        name = p["name"]
        total = p["total"]
        for cat in ("nba", "nhl", "mlb", "mls", "nascar", "golf", "tennis"):
            total -= p["categories"].get(cat, {}).get("bonus_pts", 0) or 0
        for cat in ("actor", "actress", "stock", "country"):
            total -= p["categories"].get(cat, {}).get("baseline_pts", 0) or 0
        base[name] = total

    # Pre-extract composite/raw scores for re-ranked categories
    current_actor_comp = {
        p["name"]: p["categories"].get("actor", {}).get("raw_value") or 0.0
        for p in current_scores
    }
    current_actress_comp = {
        p["name"]: p["categories"].get("actress", {}).get("raw_value") or 0.0
        for p in current_scores
    }
    current_stock_raw = {
        p["name"]: p["categories"].get("stock", {}).get("raw_value") or 0.0
        for p in current_scores
    }
    current_country_raw = {
        p["name"]: p["categories"].get("country", {}).get("raw_value") or 0.0
        for p in current_scores
    }

    # Current bonuses for in-progress playoff categories
    current_nba = {p["name"]: p["categories"].get("nba", {}).get("bonus_pts", 0) or 0
                   for p in current_scores}
    current_nhl = {p["name"]: p["categories"].get("nhl", {}).get("bonus_pts", 0) or 0
                   for p in current_scores}

    # Pre-normalize championship odds for per-sim sampling
    nba_norm    = _normalize(odds["nba_champ"])
    nhl_norm    = _normalize(odds["nhl_champ"])
    mlb_norm    = _normalize(odds["mlb_champ"])
    mls_norm    = _normalize(odds["mls_champ"])
    nascar_norm = _normalize(odds["nascar_champ"])

    tennis_pairs = [
        ("tennis_french_men_win",     "tennis_french_men_ru"),
        ("tennis_french_women_win",   "tennis_french_women_ru"),
        ("tennis_wimbledon_men_win",  "tennis_wimbledon_men_ru"),
        ("tennis_wimbledon_women_win","tennis_wimbledon_women_ru"),
        ("tennis_usopen_men_win",     "tennis_usopen_men_ru"),
        ("tennis_usopen_women_win",   "tennis_usopen_women_ru"),
    ]
    golf_pairs = [
        ("golf_uso_win",  "golf_uso_ru"),
        ("golf_open_win", "golf_open_ru"),
    ]

    sim_totals = {name: [] for name in players_list}
    wins  = {name: 0 for name in players_list}
    top4s = {name: 0 for name in players_list}

    for _ in range(n):
        totals = dict(base)

        # ── NBA: sample conference finals + Finals ──────────────────────────
        nba_results = _simulate_playoffs_conf(
            odds["nba_conf_finals_west"], odds["nba_conf_finals_east"], nba_norm
        )
        for player in NBA_PICKS:
            old = current_nba[player]
            if old >= 6.5:
                new = MILESTONES.get(nba_results.get(player, "semi"), 6.5)
                totals[player] += max(0, new - old)

        # ── NHL: sample conference finals + Finals ──────────────────────────
        nhl_results = _simulate_playoffs_conf(
            odds["nhl_conf_finals_west"], odds["nhl_conf_finals_east"], nhl_norm
        )
        for player in NHL_PICKS:
            old = current_nhl[player]
            if old >= 6.5:
                new = MILESTONES.get(nhl_results.get(player, "semi"), 6.5)
                totals[player] += max(0, new - old)

        # ── MLB / MLS / NASCAR: sample full playoff outcomes ────────────────
        for player, pts in _sample_playoff_sport(mlb_norm).items():
            totals[player] += pts
        for player, pts in _sample_playoff_sport(mls_norm).items():
            totals[player] += pts
        for player, pts in _sample_playoff_sport(nascar_norm).items():
            totals[player] += pts

        # ── Golf: sample each remaining major independently ─────────────────
        for wk, rk in golf_pairs:
            winner, runner_up = _sample_major(odds[wk], odds[rk])
            if winner:     totals[winner]     += 6.0
            if runner_up:  totals[runner_up]  += 2.5

        # ── Tennis: sample each remaining slam independently ────────────────
        for wk, rk in tennis_pairs:
            winner, runner_up = _sample_major(odds.get(wk, {}), odds.get(rk, {}))
            if winner:     totals[winner]     += 4.0
            if runner_up:  totals[runner_up]  += 2.5

        # ── Actor / Actress: sample each upcoming film's box office + RT ────
        actor_comp   = dict(current_actor_comp)
        actress_comp = dict(current_actress_comp)
        for film in FILM_PIPELINE:
            box    = _sample_lognormal(*film["box_office"])
            rt     = _sample_normal_capped(*film["rt"])
            contrib = (rt / 100.0) * box
            for player, factor in film["actor"].items():
                actor_comp[player]   = actor_comp.get(player, 0.0)   + contrib * factor
            for player, factor in film["actress"].items():
                actress_comp[player] = actress_comp.get(player, 0.0) + contrib * factor
        for comp_dict in (actor_comp, actress_comp):
            for player, pts in _rank_composites(players_list, comp_dict).items():
                totals[player] += pts

        # ── Stock: sample additional return, re-rank ────────────────────────
        stock_sim = {}
        for player in STOCK_SIM:
            exp_add, std = STOCK_SIM[player]
            stock_sim[player] = current_stock_raw.get(player, 0.0) + random.gauss(exp_add, std)
        for player, pts in _rank_composites(players_list, stock_sim).items():
            totals[player] += pts

        # ── Country: sample Oct IMF revision, re-rank ──────────────────────
        country_sim = {}
        for player in COUNTRY_SIM:
            exp_rev, std = COUNTRY_SIM[player]
            country_sim[player] = current_country_raw.get(player, 0.0) + random.gauss(exp_rev, std)
        for player, pts in _rank_composites(players_list, country_sim).items():
            totals[player] += pts

        # Rank and tally
        ranked = sorted(players_list, key=lambda x: -totals[x])
        wins[ranked[0]] += 1
        for name in ranked[:4]:
            top4s[name] += 1
        for name in players_list:
            sim_totals[name].append(totals[name])

    # Compile results
    out = {}
    for name in players_list:
        sims = sorted(sim_totals[name])
        out[name] = {
            "win_pct":         round(wins[name] / n * 100, 2),
            "top4_pct":        round(top4s[name] / n * 100, 2),
            "projected_total": round(sum(sims) / n, 1),
            "projected_p10":   round(sims[int(n * 0.10)], 1),
            "projected_p90":   round(sims[int(n * 0.90)], 1),
        }
    return out


# ─── Main ──────────────────────────────────────────────────────────────────────
def run():
    print("=== Fantasy Life Projections ===")

    with open(SCORES_PATH) as f:
        scores_data = json.load(f)
    current_scores = scores_data["players"]
    print(f"  Loaded {len(current_scores)} players from scores.json")

    markets_used = []
    print("\n── Fetching odds ─────────────────────────────────────────────")
    odds = build_odds(markets_used)

    print("\n── Computing expected additional points ───────────────────────")
    expected = compute_expected_additional(current_scores, odds)

    print("\n── Running Monte Carlo simulation ─────────────────────────────")
    sim_results = simulate(current_scores, odds)

    # Assemble output
    players_out = []
    for p in current_scores:
        name = p["name"]
        cat_exp = expected.get(name, {})
        total_additional = sum(cat_exp.values())
        sr = sim_results[name]
        players_out.append({
            "name":               name,
            "current_total":      p["total"],
            "projected_additional": round(total_additional, 1),
            "projected_total":    sr["projected_total"],
            "projected_p10":      sr["projected_p10"],
            "projected_p90":      sr["projected_p90"],
            "win_pct":            sr["win_pct"],
            "top4_pct":           sr["top4_pct"],
            "category_expected":  {k: round(v, 2) for k, v in cat_exp.items() if v > 0.01},
        })

    # Sort by projected total
    players_out.sort(key=lambda x: -x["projected_total"])

    output = {
        "generated_at":    datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kalshi_markets_used": markets_used,
        "n_simulations":   N_SIMS,
        "players":         players_out,
    }

    with open(PROJECTIONS_PATH, "w") as f:
        json.dump(output, f, separators=(",", ":"))

    print(f"\n── Results ─────────────────────────────────────────────────────")
    print(f"{'Player':10} {'Curr':7} {'+Exp':7} {'Proj':7} {'P10':7} {'P90':7} {'Win%':6} {'Top4%':6}")
    for p in players_out:
        print(f"{p['name']:10} {p['current_total']:7.1f} "
              f"{p['projected_additional']:7.1f} {p['projected_total']:7.1f} "
              f"{p['projected_p10']:7.1f} {p['projected_p90']:7.1f} "
              f"{p['win_pct']:6.2f}% {p['top4_pct']:6.2f}%")
    print(f"\nWrote {PROJECTIONS_PATH}")
    if markets_used:
        print(f"Live Kalshi markets: {', '.join(markets_used)}")
    else:
        print("Note: all odds from static fallback (no KALSHI_API_KEY or no markets matched)")


if __name__ == "__main__":
    run()
