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
import time
import base64
import requests

SCORES_PATH      = os.path.join(os.path.dirname(__file__), "docs", "scores.json")
PROJECTIONS_PATH = os.path.join(os.path.dirname(__file__), "docs", "projections.json")
KALSHI_BASE      = "https://api.elections.kalshi.com/trade-api/v2"
# Auth priority: (1) RSA-PSS via KALSHI_API_KEY_ID + KALSHI_PRIVATE_KEY,
# (2) Bearer token via KALSHI_API_KEY, (3) unauthenticated (public endpoints).
KALSHI_KEY_ID    = os.environ.get("KALSHI_API_KEY_ID", "")
KALSHI_PEM       = os.environ.get("KALSHI_PRIVATE_KEY", "").replace('\\n', '\n')
KALSHI_API_KEY   = os.environ.get("KALSHI_API_KEY", "")
_KALSHI_PRIVATE_KEY  = None   # loaded lazily on first use
_KALSHI_KEY_WARNED   = False
N_SIMS           = 10_000

# ─── Draft picks (canonical source: draft_picks_2026.py) ──────────────────
from draft_picks_2026 import DRAFT_PICKS_2026, TENNIS_GENDER

NBA_PICKS    = DRAFT_PICKS_2026["NBA"]
NHL_PICKS    = DRAFT_PICKS_2026["NHL"]
MLB_PICKS    = DRAFT_PICKS_2026["MLB"]
MLS_PICKS    = DRAFT_PICKS_2026["MLS"]
NASCAR_PICKS = DRAFT_PICKS_2026["NASCAR"]
GOLF_PICKS   = DRAFT_PICKS_2026["Golf"]
# Tennis: men's and women's tracked separately
TENNIS_MEN   = {p: n for p, n in DRAFT_PICKS_2026["Tennis"].items() if TENNIS_GENDER.get(n) == "M"}
TENNIS_WOMEN = {p: n for p, n in DRAFT_PICKS_2026["Tennis"].items() if TENNIS_GENDER.get(n) == "F"}

# ─── Upcoming 2026 film pipeline (Actor / Actress simulation) ─────────────────
# box_office: (p10, p50, p90) domestic gross in $M  — lognormal distribution
# rt:         (p10, p50, p90) Rotten Tomatoes score — normal distribution, capped 0–100
# actor/actress: [player_key, ...]  — just need to be in the movie
FILM_PIPELINE = [
    {
        "title": "Moana",
        "box_office": (130, 190, 260),
        "rt": (48, 62, 75),
        "actor":   ["Theo"],
        "actress": [],
    },
    {
        "title": "The Odyssey",
        "box_office": (175, 275, 375),
        "rt": (78, 88, 96),
        "actor":   ["Molmen", "Feder", "Buckley", "Korch"],
        "actress": ["Korch", "Wu", "Mitchell"],
    },
    {
        "title": "Spider-Man: Brand New Day",
        "box_office": (450, 750, 1100),
        "rt": (72, 84, 94),
        "actor":   ["Feder"],
        "actress": ["Wu"],
    },
    {
        "title": "The Social Reckoning",
        "box_office": (60, 100, 160),  # Oct 9; Social Network comp ($97M); award-season prestige
        "rt": (76, 88, 96),            # Sorkin direction, Jeremy Allen White / Jeremy Strong
        "actor":   ["Shep"],
        "actress": [],
    },
    {
        "title": "Flowervale Street",
        "box_office": (15, 35, 60),
        "rt": (62, 75, 88),
        "actor":   [],
        "actress": ["Korch"],
    },
    {
        "title": "Verity",
        "box_office": (40, 75, 110),
        "rt": (55, 68, 80),
        "actor":   [],
        "actress": ["Korch"],
    },
    {
        "title": "Avengers: Doomsday",
        "box_office": (350, 500, 700),
        "rt": (68, 80, 90),
        "actor":   ["Mitchell", "Fryar"],
        "actress": ["Fryar"],
    },
    {
        "title": "Dune: Part Three",
        "box_office": (180, 280, 400),
        "rt": (82, 91, 97),
        "actor":   ["Jamzee", "Buckley"],
        "actress": ["Wu", "Fryar", "Buckley"],
    },
    {
        "title": "Focker-in-Law",
        "box_office": (55, 95, 145),
        "rt": (40, 58, 72),
        "actor":   [],
        "actress": ["Tim"],
    },
    {
        "title": "Jumanji",
        "box_office": (120, 175, 240),
        "rt": (60, 72, 80),
        "actor":   ["Theo"],
        "actress": [],
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
def _load_kalshi_private_key():
    """Load and cache the RSA private key from KALSHI_PRIVATE_KEY env var (PEM string)."""
    global _KALSHI_PRIVATE_KEY
    if _KALSHI_PRIVATE_KEY is not None:
        return _KALSHI_PRIVATE_KEY
    if not KALSHI_PEM:
        return None
    try:
        from cryptography.hazmat.primitives import serialization
        _KALSHI_PRIVATE_KEY = serialization.load_pem_private_key(
            KALSHI_PEM.encode(), password=None
        )
        return _KALSHI_PRIVATE_KEY
    except Exception as e:
        print(f"  ✗ Kalshi: failed to load private key: {e}")
        return None


def _kalshi_sign(path: str) -> dict:
    """Return signed auth headers for a GET request to the given path (no query string)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    ts = str(int(time.time() * 1000))
    message = f"{ts}GET/trade-api/v2{path}"
    key = _load_kalshi_private_key()
    if key is None:
        raise RuntimeError("Kalshi private key unavailable — check KALSHI_PRIVATE_KEY (PEM) is set and parseable")
    sig = key.sign(
        message.encode(),
        asym_padding.PSS(
            mgf=asym_padding.MGF1(hashes.SHA256()),
            salt_length=asym_padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY":       KALSHI_KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        "Accept":                  "application/json",
    }


def _kalshi_get(path, params=None):
    global _KALSHI_KEY_WARNED
    url = f"{KALSHI_BASE}{path}"

    # Attempt 1: RSA-PSS signed request
    if KALSHI_KEY_ID and KALSHI_PEM:
        try:
            r = requests.get(url, headers=_kalshi_sign(path), params=params or {}, timeout=8)
            if r.status_code == 200:
                return r.json()
            print(f"  ✗ Kalshi RSA {path}: HTTP {r.status_code} — {r.text[:200]}")
        except Exception as e:
            print(f"  ✗ Kalshi RSA {path}: {e}")

    # Attempt 2: Bearer token (KALSHI_API_KEY)
    if KALSHI_API_KEY:
        try:
            r = requests.get(url, headers={"Authorization": f"Bearer {KALSHI_API_KEY}"}, params=params or {}, timeout=8)
            if r.status_code == 200:
                return r.json()
            print(f"  ✗ Kalshi Bearer {path}: HTTP {r.status_code}")
        except Exception as e:
            print(f"  ✗ Kalshi Bearer {path}: {e}")

    # Attempt 3: unauthenticated (public market data)
    try:
        r = requests.get(url, params=params or {}, timeout=8)
        if r.status_code == 200:
            return r.json()
        if not _KALSHI_KEY_WARNED:
            print(f"  ✗ Kalshi: unauthenticated request returned HTTP {r.status_code} — using static fallback")
            _KALSHI_KEY_WARNED = True
    except Exception as e:
        if not _KALSHI_KEY_WARNED:
            print(f"  ✗ Kalshi: {e} — using static fallback")
            _KALSHI_KEY_WARNED = True
    return None


_MARKETS_CACHE = {}   # series_ticker -> raw markets list (one fetch per run)


def _fetch_markets_for_series(series_ticker):
    if series_ticker in _MARKETS_CACHE:
        return _MARKETS_CACHE[series_ticker]
    # Pass 1: query by series_ticker without status filter (avoids missing in-progress markets)
    data = _kalshi_get("/markets", {"series_ticker": series_ticker, "limit": 200})
    markets = data.get("markets", []) if data else []
    if not markets and "-" in series_ticker:
        # Pass 1.5: dashed tickers are usually EVENT tickers (e.g. KXATP-26WIM =
        # Wimbledon men's inside the KXATP series) — query by event_ticker
        data15 = _kalshi_get("/markets", {"event_ticker": series_ticker, "limit": 200})
        markets = data15.get("markets", []) if data15 else []
    if not markets:
        # Pass 2: try the /events/{ticker}/markets endpoint (Kalshi v2 multi-outcome events)
        data2 = _kalshi_get(f"/events/{series_ticker}/markets", {"limit": 200})
        markets = data2.get("markets", []) if data2 else []
    _MARKETS_CACHE[series_ticker] = markets
    return markets


def _name_matches(kalshi_title, pick_name):
    """True if any word ≥4 chars from pick_name appears in kalshi_title (case-insensitive)."""
    title = kalshi_title.lower()
    for word in pick_name.split():
        if len(word) >= 4 and word.lower() in title:
            return True
    return False


def _market_haystack(m):
    """All the fields where Kalshi may put the team/player name.
    The API stopped guaranteeing full names in `title` (mid-2026 responses carry
    fragments like 'yes St. Louis' there) — subtitle/yes_sub_title usually have
    the real name now."""
    return " ".join(str(m.get(k) or "") for k in
                    ("title", "subtitle", "yes_sub_title", "no_sub_title", "ticker"))


def _pick_market(markets, pick_name):
    """Best ACTIVE market for a pick. Exact yes_sub_title match first — Kalshi
    uses city-style names ('New York Y', 'Los Angeles D'), so fuzzy word overlap
    alone would hit both New York teams. Fuzzy haystack match is the fallback."""
    words = pick_name.split()
    cands = {pick_name.lower().strip()}
    if len(words) >= 2:
        city = " ".join(words[:-1]).lower()
        cands.add(city)                                # 'tampa bay'
        cands.add(city + " " + words[-1][0].lower())   # 'new york y'
        if city == "la":
            cands.add("los angeles")                   # Kalshi lists LA Galaxy as 'Los Angeles'
    # NOTE: active markets have result == '' (empty string), NOT null —
    # a `result is not None` check would skip every live market.
    active = [m for m in markets if not m.get("result")]
    for m in active:
        if str(m.get("yes_sub_title") or "").lower().strip() in cands:
            return m
    for m in active:
        if _name_matches(_market_haystack(m), pick_name):
            return m
    return None


def _extract_probs(markets, picks_dict):
    """
    Given a list of Kalshi markets and a {player: pick_name} dict,
    return {player: yes_probability (0–1)}.
    Prices: midpoint of yes_bid_dollars/yes_ask_dollars, falling back to
    last_price_dollars when the book is empty.
    """
    probs = {}
    for player, pick in picks_dict.items():
        m = _pick_market(markets, pick)
        if m is None:
            continue
        try:
            yes_ask = m.get("yes_ask_dollars")
            yes_bid = m.get("yes_bid_dollars")
            if yes_ask is not None and yes_bid is not None and float(yes_ask) > 0:
                prob = (float(yes_ask) + float(yes_bid)) / 2.0
            elif yes_ask is not None and float(yes_ask) > 0:
                prob = float(yes_ask)
            else:
                prob = float(m.get("last_price_dollars") or 0)
            if prob > 0:
                probs[player] = prob
        except (TypeError, ValueError):
            pass
    return probs


def fetch_kalshi_championship_probs(series_ticker, picks_dict, label):
    """Fetch win-probability dict {player: float} from Kalshi, or {} on failure."""
    markets = _fetch_markets_for_series(series_ticker)
    if not markets:
        return {}
    probs = _extract_probs(markets, picks_dict)
    if probs:
        found = ", ".join(f"{p}={v:.1%}" for p, v in sorted(probs.items()))
        print(f"  ✓ Kalshi {label} [{series_ticker}]: {found}")
    else:
        all_titles = [m.get("title") or m.get("subtitle") or m.get("question") or str(list(m.keys())[:4]) for m in markets]
        print(f"  ℹ Kalshi {label} [{series_ticker}]: {len(markets)} markets, no picks matched")
        print(f"    All titles: {all_titles[:20]}")
    return probs


# ─── Static fallback odds ─────────────────────────────────────────────────────
# Championship win probabilities for each pick.
# "OTHER" = probability the winner is a team/player not in any pick.
# Bump FALLBACK_AS_OF whenever entries below are refreshed or pruned —
# it is printed in the run log so stale fallbacks are visible in CI.

FALLBACK_AS_OF = "2026-06-15"

FALLBACK = {
    # NBA Finals: SETTLED — Knicks (Buckley) won
    "nba_champ": {"Buckley": 1.0},
    # WCF: SETTLED — Spurs (Wu) won Game 7 over Thunder (Feder)
    "nba_conf_finals_west": {"Wu": 1.0},
    "nba_conf_finals_east": {"Buckley": 1.0},  # SETTLED: Knicks swept Cavaliers 4-0

    # NHL Finals: SETTLED — Hurricanes (Jamzee) won the Stanley Cup
    "nhl_champ": {"Jamzee": 1.0},
    "nhl_conf_finals_west": {"Tim": 1.0},  # SETTLED: Golden Knights swept Avalanche 4-0
    "nhl_conf_finals_east": {"Jamzee": 1.0},  # SETTLED: Hurricanes won ECF

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
    # French Open MEN: SETTLED — Zverev (Theo) won Roland Garros 2026
    "tennis_french_men_win": {
        "Theo": 1.0,
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
    # Kalshi tickers, verified against the live series catalog 2026-07-05
    # (probe.yml mode=kalshi dumps it). Undashed = series ticker; dashed =
    # EVENT ticker (queried via ?event_ticker= — see _fetch_markets_for_series).
    # 2027 slams / next-season events will need new event tickers here.
    #
    # NBA/NHL 2025-26 are DECIDED (Knicks, Hurricanes) — deliberately empty so
    # Kalshi's next-season futures (KXNBA now carries 2027 markets) can never
    # override the pinned FALLBACK results. Same for finished conf finals,
    # French Open, and US Open golf.
    "nba":    [],
    "nhl":    [],
    "mlb":    ["KXMLB"],                 # KXMLB-26 · 'Will Tampa Bay win the 2026 Pro Baseball Championship?'
    "mls":    ["KXMLSCUP"],              # KXMLSCUP-26 · 'Will Vancouver win the MLS Cup?'
    "nascar": ["KXNASCARCUPSERIES"],     # KXNASCARCUPSERIES-NCS26 · full driver names
    "golf_uso":  [],
    "golf_open": ["KXPGAWIN"],           # 'Golfer to Win' per-major series
    "tennis_fo_m":  [],
    "tennis_fo_w":  [],
    "tennis_wb_m":  ["KXATP-26WIM"],     # Wimbledon men's event inside KXATP
    "tennis_wb_w":  ["KXWTA-26WIM"],
    "tennis_uso_m": ["KXATP-26USO"],
    "tennis_uso_w": ["KXWTA-26USO"],
    # Conference finals — all decided, fallback only
    "nba_ecf": [],
    "nba_wcf": [],
    "nhl_wcf": [],
    # World Cup (auto-settlement sources, not category odds)
    "wc_ro16":   ["KXWCROUND-26RO16"],   # 'Will USA qualify for FIFA World Cup Round of 16?'
    "wc_winner": ["KXMENWORLDCUP"],      # KXMENWORLDCUP-26 · full country names
}


def _h2h(a, b):
    """Head-to-head YES probability (0–100 int) for first player given win probs."""
    total = a + b
    return round(a / total * 100) if total > 0 else None


def _mlb_h2h(player_a, player_b):
    """P(A's team ends July 1 with higher win% than B's) via normal approximation."""
    def fn(o):
        wp_a = o.get("mlb_win_pct", {}).get(player_a)
        wp_b = o.get("mlb_win_pct", {}).get(player_b)
        if wp_a is None or wp_b is None:
            return None
        today        = datetime.date.today()
        season_start = datetime.date(today.year, 4, 1)
        bet_close    = datetime.date(today.year, 7, 1)
        games_per_day = 162 / 183
        days_played  = max(1, (today - season_start).days)
        days_left    = max(0, (bet_close - today).days)
        gr = days_left * games_per_day
        if gr <= 0:
            return 100 if wp_a > wp_b else (0 if wp_a < wp_b else 50)
        gp = days_played * games_per_day
        diff = (wp_a - wp_b) * (gp + gr)
        var  = (wp_a * (1 - wp_a) + wp_b * (1 - wp_b)) * gr
        if var <= 0:
            return None
        z = diff / math.sqrt(var)
        p = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        return round(p * 100)
    return fn


def _mls_h2h(player_a, player_b):
    """P(A's team ends July 1 with more MLS points than B's) via normal approximation."""
    def fn(o):
        pts_a = o.get("mls_points", {}).get(player_a)
        pts_b = o.get("mls_points", {}).get(player_b)
        if pts_a is None or pts_b is None:
            return None
        today        = datetime.date.today()
        season_start = datetime.date(today.year, 3, 1)
        bet_close    = datetime.date(today.year, 7, 1)
        games_per_day = 34 / 245
        days_played  = max(1, (today - season_start).days)
        days_left    = max(0, (bet_close - today).days)
        gr = days_left * games_per_day
        if gr <= 0:
            return 100 if pts_a > pts_b else (0 if pts_a < pts_b else 50)
        gp = max(1, days_played * games_per_day)
        ppg_a = pts_a / gp
        ppg_b = pts_b / gp
        diff = (pts_a - pts_b) + (ppg_a - ppg_b) * gr
        var  = 2 * 1.63 * gr  # ~1.63 pts variance per MLS game per team
        if var <= 0:
            return None
        z = diff / math.sqrt(var)
        p = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        return round(p * 100)
    return fn


def _pts_h2h(player_a, player_b):
    """Return a prop fn giving P(A total > B total) from simulation pairwise data."""
    def fn(o):
        p = o.get("pairwise", {}).get((player_a, player_b))
        return round(p * 100) if p is not None else None
    return fn


# Prop definitions: (id, static_yes_pct, fn(odds)->int|None, source_category_label)
# fn returns a computed YES% from odds dict, or None to use static.
# source_category_label must match a string in markets_used to be marked "kalshi".
#
# Settled props are NOT listed here — data/sb_settled.json is the single source
# of truth for settlement. compute_prop_odds() reads it and pins settled props
# at 100 (yes) / 0 (no) / 50 (push) with settled+outcome flags in the output.

SB_SETTLED_PATH = os.path.join(os.path.dirname(__file__), "data", "sb_settled.json")

_SETTLED_PCT = {"yes": 100, "no": 0, "push": 50}


def _load_settled_ledger():
    """{prop_id: outcome} from data/sb_settled.json (outcome: yes|no|push)."""
    try:
        with open(SB_SETTLED_PATH) as f:
            return {e["id"]: e["outcome"] for e in json.load(f)}
    except Exception:
        return {}


# Wagering/resolution schedule per prop: (closes_at, resolves_by) — both UTC ISO.
# closes_at:   wagering stops (enforced client-side in sportsbook.html, live).
# resolves_by: if the prop is still unsettled after this, the hourly odds job
#              flags it for manual settlement (NEEDS_SETTLEMENT line → GitHub issue).
_PROP_SCHEDULE = {
    # MLB / MLS standings bets close Jul 1 per league rules
    "mlb-wu-v-mitchell":     ("2026-07-01T00:00:00Z", "2026-09-28T00:00:00Z"),
    "mlb-jens-v-buckley":    ("2026-07-01T00:00:00Z", "2026-09-28T00:00:00Z"),
    "mls-buckley-v-molmen":  ("2026-07-01T00:00:00Z", "2026-10-19T00:00:00Z"),
    # Wimbledon (Jun 29 – Jul 12)
    "wimb-m-buckley-sinner-wins": ("2026-07-12T12:00:00Z", "2026-07-13T00:00:00Z"),
    "wimb-w-fryar-v-feder":       ("2026-07-09T00:00:00Z", "2026-07-12T00:00:00Z"),
    "wimb-m-theo-v-shep":         ("2026-07-09T00:00:00Z", "2026-07-13T00:00:00Z"),
    "wimb-w-wu-v-tim":            ("2026-07-09T00:00:00Z", "2026-07-12T00:00:00Z"),
    # World Cup knockout stage
    "wc-shep-fra-r32":       ("2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z"),
    "wc-fryar-nor-r32":      ("2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z"),
    "wc-wu-usa-r32":         ("2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z"),
    "wc-jens-ger-r32":       ("2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z"),
    "wc-molmen-arg-wins-wc": ("2026-07-19T00:00:00Z", "2026-07-20T00:00:00Z"),
    # Season-long props
    "stocks-fryar-avgo-v-mitchell-cvna": ("2026-12-31T00:00:00Z", "2027-01-01T00:00:00Z"),
    "todd-wins-fl-2026":     ("2026-12-31T00:00:00Z", "2027-01-01T00:00:00Z"),
    "pts-wu-v-korch":        ("2026-12-31T00:00:00Z", "2027-01-01T00:00:00Z"),
    "pts-tim-v-molmen":      ("2026-12-31T00:00:00Z", "2027-01-01T00:00:00Z"),
    "pts-jamzee-v-fryar":    ("2026-12-31T00:00:00Z", "2027-01-01T00:00:00Z"),
    "pts-mitchell-v-todd":   ("2026-12-31T00:00:00Z", "2027-01-01T00:00:00Z"),
    "pts-buckley-v-theo":    ("2026-12-31T00:00:00Z", "2027-01-01T00:00:00Z"),
}

# Auto-settlement rules — evaluated against RESOLVED Kalshi markets each run.
#   ("wins", series_key, pick_name):
#       pick's market resolves yes → prop YES; resolves no → prop NO.
#   ("either_wins", series_key, pick_a, pick_b):
#       A's market resolves yes → YES; B's resolves yes → NO; otherwise stays open
#       (e.g. neither pick won the title — round-by-round comparison needs a human).
# Matching uses the pick's SURNAME only (stricter than _name_matches, which would
# let "Alexander Zverev" match an "Alexander Bublik" market).
_AUTO_SETTLE_RULES = {
    "wimb-m-buckley-sinner-wins": ("wins",        "tennis_wb_m", "Jannik Sinner"),
    "wimb-w-fryar-v-feder":       ("either_wins", "tennis_wb_w", "Aryna Sabalenka", "Iga Swiatek"),
    "wimb-m-theo-v-shep":         ("either_wins", "tennis_wb_m", "Alexander Zverev", "Novak Djokovic"),
    "wimb-w-wu-v-tim":            ("either_wins", "tennis_wb_w", "Coco Gauff", "Madison Keys"),
    # WC R32 "X beats Y" ≡ "X qualifies for the Round of 16" (matchups were fixed)
    "wc-shep-fra-r32":            ("wins", "wc_ro16", "France"),
    "wc-fryar-nor-r32":           ("wins", "wc_ro16", "Norway"),
    "wc-wu-usa-r32":              ("wins", "wc_ro16", "USA"),
    "wc-jens-ger-r32":            ("wins", "wc_ro16", "Germany"),
    "wc-molmen-arg-wins-wc":      ("wins", "wc_winner", "Argentina"),
}

_PROP_DEFS = [
    # ── Tennis · Roland Garros Women's ───────────────────────────────────────────
    ("rg-w-fryar-v-feder",  38, lambda o: _h2h(o.get("tennis_french_women_win",{}).get("Fryar",0), o.get("tennis_french_women_win",{}).get("Feder",0)), "Tennis-FO-Women"),
    ("rg-w-fryar-v-wu",     55, lambda o: _h2h(o.get("tennis_french_women_win",{}).get("Fryar",0), o.get("tennis_french_women_win",{}).get("Wu",0)),    "Tennis-FO-Women"),

    # ── US Open Golf ─────────────────────────────────────────────────────────────
    # uso-wu-v-molmen, uso-tim-v-shep settled — see _PROP_DEFS_SETTLED
    ("uso-molmen-v-feder", 48, lambda o: _h2h(o.get("golf_uso_win",{}).get("Molmen",0), o.get("golf_uso_win",{}).get("Feder",0)), "Golf-USOpen-win"),

    # ── MLB / MLS / NASCAR (model only) ──────────────────────────────────────────
    ("mlb-jens-v-tim",        54, _mlb_h2h("Jens",    "Tim"),      "mlb-standings"),
    ("mlb-wu-v-mitchell",     55, _mlb_h2h("Wu",      "Mitchell"), "mlb-standings"),
    ("mlb-feder-v-korch",     58, _mlb_h2h("Feder",   "Korch"),    "mlb-standings"),
    ("mls-buckley-v-molmen",  52, _mls_h2h("Buckley", "Molmen"),   "mls-standings"),
    ("mls-theo-v-shep",       57, _mls_h2h("Theo",    "Shep"),     "mls-standings"),
    ("nascar-molmen-v-korch", 53, None, None),

    # ── Wimbledon 2026 (Jun 29 – Jul 12) ────────────────────────────────────────────
    ("wimb-m-buckley-sinner-wins",  73, None, None),  # Sinner wins men's (Alcaraz/Todd withdrew)
    ("wimb-w-fryar-v-feder",        60, None, None),  # Sabalenka > Swiatek; different halves
    ("wimb-m-theo-v-shep",          38, None, None),  # Zverev > Djokovic (7x champion on grass)
    ("wimb-w-wu-v-tim",             62, None, None),  # Gauff > Keys

    # ── FIFA World Cup 2026 · Knockout Stage ─────────────────────────────────────
    # (group-stage props all settled — see _PROP_DEFS_SETTLED)
    ("wc-shep-fra-r32",             82, None, None),  # France beats Sweden R32
    ("wc-fryar-nor-r32",            65, None, None),  # Norway beats Ivory Coast R32
    ("wc-wu-usa-r32",               70, None, None),  # USA beats Bosnia R32
    ("wc-jens-ger-r32",             65, None, None),  # Germany beats Paraguay R32
    ("wc-molmen-arg-wins-wc",       20, None, None),  # Argentina wins the World Cup

    # ── Total Points (simulation-backed — updates every run from Monte Carlo) ──────
    ("pts-wu-v-korch",      47, _pts_h2h("Wu",      "Korch"),   "pts-model"),
    ("pts-tim-v-molmen",    55, _pts_h2h("Tim",      "Molmen"),  "pts-model"),
    ("pts-jamzee-v-fryar",  44, _pts_h2h("Jamzee",  "Fryar"),   "pts-model"),
    ("pts-mitchell-v-todd", 65, _pts_h2h("Mitchell", "Todd"),    "pts-model"),
    ("pts-buckley-v-theo",  80, _pts_h2h("Buckley",  "Theo"),    "pts-model"),
]


def compute_prop_odds(odds, markets_used, prev_props=None):
    """Returns {prop_id: {yes_pct, source, [settled, outcome], [closes_at]}}.

    Settled state comes from data/sb_settled.json (the settlement ledger).
    prev_props (odds-only mode): last published prop_odds — used to carry
    forward simulation-backed values when no fresh Monte Carlo ran this pass.
    """
    live_cats = set(markets_used)
    settled = _load_settled_ledger()
    result = {}
    for prop_id, static_pct, fn, src_cat in _PROP_DEFS:
        if prop_id in settled:
            continue  # pinned below from the ledger
        computed = None
        if fn is not None:
            try:
                computed = fn(odds)
            except Exception:
                computed = None
        if computed and 0 < computed < 100:
            source = "kalshi" if (src_cat and src_cat in live_cats) else "model"
            result[prop_id] = {"yes_pct": computed, "source": source}
        elif prev_props and src_cat == "pts-model" and prop_id in prev_props \
                and prev_props[prop_id].get("yes_pct") is not None:
            # odds-only run: no fresh simulation — keep the last sim-backed value
            result[prop_id] = {"yes_pct": prev_props[prop_id]["yes_pct"],
                               "source": prev_props[prop_id].get("source", "model")}
        else:
            result[prop_id] = {"yes_pct": static_pct, "source": "static"}
    for prop_id, outcome in settled.items():
        result[prop_id] = {"yes_pct": _SETTLED_PCT.get(outcome, 50), "source": "settled",
                           "settled": True, "outcome": outcome}
    # Attach wagering close timestamps (frontend enforces these live)
    for prop_id, (closes_at, _resolves_by) in _PROP_SCHEDULE.items():
        entry = result.setdefault(prop_id, {"yes_pct": None, "source": "none"})
        if not entry.get("settled"):
            entry["closes_at"] = closes_at
    return result


def _parse_iso_z(ts):
    return datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc)


def _surname_matches(kalshi_title, pick_name):
    """Settlement-grade matching: the pick's surname must appear in the title.
    Deliberately stricter than _name_matches — first names collide (Alexander
    Zverev vs Alexander Bublik) and settlement moves balances."""
    surname = pick_name.split()[-1].lower()
    return surname in kalshi_title.lower()


def _resolved_result(series_key, pick_name):
    """'yes'/'no' if the pick's Kalshi market has resolved, else None."""
    for ticker in KNOWN_SERIES.get(series_key, []):
        for m in _fetch_markets_for_series(ticker):
            if m.get("result") in ("yes", "no") and _surname_matches(_market_haystack(m), pick_name):
                return m["result"]
    return None


def auto_settle_from_kalshi():
    """Evaluate _AUTO_SETTLE_RULES against resolved Kalshi markets.
    Appends any newly decided props to data/sb_settled.json.
    Returns the list of new ledger entries."""
    settled = _load_settled_ledger()
    new_entries = []
    for prop_id, rule in _AUTO_SETTLE_RULES.items():
        if prop_id in settled:
            continue
        outcome = None
        if rule[0] == "wins":
            outcome = _resolved_result(rule[1], rule[2])
        elif rule[0] == "either_wins":
            if _resolved_result(rule[1], rule[2]) == "yes":
                outcome = "yes"
            elif _resolved_result(rule[1], rule[3]) == "yes":
                outcome = "no"
        if outcome:
            print(f"  🏁 AUTO-SETTLE {prop_id} → {outcome} (Kalshi market resolved)")
            new_entries.append({"id": prop_id, "outcome": outcome})
    if new_entries:
        try:
            with open(SB_SETTLED_PATH) as f:
                ledger = json.load(f)
        except Exception:
            ledger = []
        ledger.extend(new_entries)
        with open(SB_SETTLED_PATH, "w") as f:
            json.dump(ledger, f, indent=2)
            f.write("\n")
    return new_entries


def settle_ledger_in_supabase():
    """Pay out every ledger entry via db.settle_sb_bet (idempotent — only rows
    with settled_outcome IS NULL are touched). Rebuilds balances if anything paid.
    No-op without Supabase credentials."""
    ledger = _load_settled_ledger()
    if not ledger:
        return 0
    try:
        import db as _db
    except Exception as e:
        print(f"  ✗ settle: db import failed ({e})")
        return 0
    processed = 0
    for prop_id, outcome in ledger.items():
        try:
            processed += _db.settle_sb_bet(prop_id, outcome)
        except Exception as e:
            print(f"  ✗ settle_sb_bet({prop_id}): {e}")
    if processed:
        print(f"  ✓ {processed} bet(s) newly settled — recalculating BB balances")
        for p in ["Tim", "Wu", "Jens", "Todd", "Mitchell", "Shep", "Theo",
                  "Feder", "Fryar", "Korch", "Molmen", "Jamzee", "Buckley"]:
            try:
                _db.recalculate_sb_balance(p)
            except Exception as e:
                print(f"  ✗ recalculate_sb_balance({p}): {e}")
    return processed


def flag_needs_settlement():
    """Print a NEEDS_SETTLEMENT line for unsettled props past their resolves_by.
    The odds workflow greps for it and maintains a GitHub issue."""
    now = datetime.datetime.now(datetime.timezone.utc)
    settled = _load_settled_ledger()
    overdue = [pid for pid, (_c, resolves_by) in _PROP_SCHEDULE.items()
               if pid not in settled and now > _parse_iso_z(resolves_by)]
    if overdue:
        print("NEEDS_SETTLEMENT: " + ",".join(sorted(overdue)))
    return overdue


def _try_kalshi_series(series_list, picks_dict, label):
    # No keyword-search fallback: Kalshi's ?keyword= ignores the query and
    # returns arbitrary recent markets, which fuzzy matching can false-match.
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
    print(f"Static FALLBACK odds last refreshed: {FALLBACK_AS_OF}")
    odds = {}

    def get(key, picks, series_key, label):
        kalshi = _try_kalshi_series(KNOWN_SERIES[series_key], picks, label)
        merged, source = _merge_probs(kalshi, FALLBACK[key])
        if source == "kalshi":
            markets_used.append(label)
        return merged

    odds["nba_champ"]            = get("nba_champ", NBA_PICKS, "nba", "NBA-championship")
    odds["nba_conf_finals_west"] = get("nba_conf_finals_west",
                                       {"Wu": "San Antonio Spurs", "Feder": "Oklahoma City Thunder"},
                                       "nba_wcf", "NBA-WCF")
    odds["nba_conf_finals_east"] = get("nba_conf_finals_east",
                                       {"Buckley": "New York Knicks", "Jens": "Cleveland Cavaliers"},
                                       "nba_ecf", "NBA-ECF")
    odds["nhl_champ"]            = get("nhl_champ", NHL_PICKS, "nhl", "NHL-StanleyCup")
    odds["nhl_conf_finals_west"] = get("nhl_conf_finals_west",
                                       {"Korch": "Colorado Avalanche", "Tim": "Vegas Golden Knights"},
                                       "nhl_wcf", "NHL-WCF")
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
            for player in film[cat]:
                composites[player] = composites.get(player, 0.0) + e_contrib
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
    # If only one pick remains in the west (series already settled), there is no loser to assign
    if len(west_players) > 1:
        west_loser = west_players[1] if west_winner == west_players[0] else west_players[0]
    else:
        west_loser = None

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
    if west_loser:
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
    if runner_up and runner_up != "OTHER" and (runner_up in NBA_PICKS or runner_up in NHL_PICKS):
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
            for player in film["actor"]:
                actor_comp[player]   = actor_comp.get(player, 0.0)   + contrib
            for player in film["actress"]:
                actress_comp[player] = actress_comp.get(player, 0.0) + contrib
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

    # Pairwise head-to-head win rates: fraction of sims where A finishes above B
    pairwise = {}
    for i, a in enumerate(players_list):
        for b in players_list[i + 1:]:
            wins_a = sum(ta > tb for ta, tb in zip(sim_totals[a], sim_totals[b]))
            pairwise[(a, b)] = wins_a / n
            pairwise[(b, a)] = 1.0 - wins_a / n
    return out, pairwise


# ─── Main ──────────────────────────────────────────────────────────────────────
def run():
    print("=== Fantasy Life Projections ===")

    with open(SCORES_PATH) as f:
        scores_data = json.load(f)
    current_scores = scores_data["players"]
    print(f"  Loaded {len(current_scores)} players from scores.json")

    markets_used = []
    print("\n── Fetching odds ─────────────────────────────────────────────")
    if KALSHI_KEY_ID:
        print(f"  Kalshi key ID: {KALSHI_KEY_ID[:8]}... PEM set: {bool(KALSHI_PEM)}")
    odds = build_odds(markets_used)

    print("\n── Computing expected additional points ───────────────────────")
    expected = compute_expected_additional(current_scores, odds)

    print("\n── Running Monte Carlo simulation ─────────────────────────────")
    sim_results, pairwise = simulate(current_scores, odds)

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
            "category_expected":  {k: round(v, 2) for k, v in cat_exp.items() if abs(v) > 0.01},
        })

    # Sort by projected total
    players_out.sort(key=lambda x: -x["projected_total"])

    odds["pairwise"] = pairwise
    odds["mlb_win_pct"] = {
        p["name"]: (p.get("categories", {}).get("mlb", {}).get("raw_value") or None)
        for p in current_scores
    }
    odds["mls_points"] = {
        p["name"]: (p.get("categories", {}).get("mls", {}).get("raw_value") or None)
        for p in current_scores
    }

    # Auto-settle props whose Kalshi markets have resolved, pay out, flag overdue
    newly_settled = auto_settle_from_kalshi()
    if newly_settled:
        settle_ledger_in_supabase()
    flag_needs_settlement()

    prop_odds = compute_prop_odds(odds, markets_used)

    output = {
        "generated_at":    datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kalshi_markets_used": markets_used,
        "fallback_as_of":  FALLBACK_AS_OF,
        "n_simulations":   N_SIMS,
        "players":         players_out,
        "prop_odds":       prop_odds,
    }

    with open(PROJECTIONS_PATH, "w") as f:
        json.dump(output, f, separators=(",", ":"))

    # Sync odds into Buckley Bucks markets (no-op if Supabase not configured)
    try:
        from db import upsert_market
        for p in players_out:
            upsert_market("win",  p["name"], p["win_pct"])
            upsert_market("top4", p["name"], p["top4_pct"])
        print("Buckley Bucks markets synced")
    except Exception as _e:
        print(f"Note: BB market sync skipped ({_e})")

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
        print("Note: all odds from static fallback (no Kalshi credentials or no markets matched)")


def run_odds_only():
    """
    Lightweight hourly refresh (odds.yml): re-fetch Kalshi odds, auto-settle any
    resolved props, and patch ONLY the prop_odds section of projections.json —
    the Monte Carlo projections from the last full run are left untouched so
    they don't jitter hourly. Writes nothing if odds are unchanged.
    """
    print("=== FL Odds Refresh (--odds-only) ===")
    try:
        with open(PROJECTIONS_PATH) as f:
            prev = json.load(f)
    except Exception as e:
        print(f"  ✗ Cannot load {PROJECTIONS_PATH} ({e}) — run a full projections pass first")
        raise SystemExit(1)

    # Standings context for the MLB/MLS h2h models (scores.json is in the repo)
    try:
        with open(SCORES_PATH) as f:
            current_scores = json.load(f)["players"]
    except Exception:
        current_scores = []

    markets_used = []
    odds = build_odds(markets_used)
    odds["mlb_win_pct"] = {
        p["name"]: (p.get("categories", {}).get("mlb", {}).get("raw_value") or None)
        for p in current_scores
    }
    odds["mls_points"] = {
        p["name"]: (p.get("categories", {}).get("mls", {}).get("raw_value") or None)
        for p in current_scores
    }

    newly_settled = auto_settle_from_kalshi()
    prop_odds = compute_prop_odds(odds, markets_used, prev_props=prev.get("prop_odds"))
    flag_needs_settlement()

    # Pay out the whole ledger every pass (idempotent) so manual ledger appends
    # and auto-settles both credit winners within the hour, not at 08:00 UTC.
    settle_ledger_in_supabase()

    if prop_odds == prev.get("prop_odds") and not newly_settled:
        print("No odds changes — projections.json left untouched.")
        return

    prev["prop_odds"] = prop_odds
    prev["kalshi_markets_used"] = markets_used
    prev["odds_updated_at"] = datetime.datetime.now(
        datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(PROJECTIONS_PATH, "w") as f:
        json.dump(prev, f, separators=(",", ":"))
    print(f"Wrote {PROJECTIONS_PATH} (prop odds refreshed"
          f"{', ' + str(len(newly_settled)) + ' auto-settled' if newly_settled else ''})")


def probe():
    """
    Diagnostic mode: attempt every Kalshi series fetch and print what's found.
    Run: KALSHI_API_KEY_ID=xxx KALSHI_PRIVATE_KEY="$(cat key.pem)" python projections.py --probe
    Does NOT write any files.
    """
    print("── Kalshi Probe ────────────────────────────────────────────────────")
    if not KALSHI_KEY_ID or not KALSHI_PEM:
        missing = []
        if not KALSHI_KEY_ID: missing.append("KALSHI_API_KEY_ID")
        if not KALSHI_PEM:    missing.append("KALSHI_PRIVATE_KEY")
        print(f"  ✗ Not set: {', '.join(missing)}. Export both and re-run.")
        return
    key = _load_kalshi_private_key()
    if not key:
        print("  ✗ Failed to load private key from KALSHI_PRIVATE_KEY.")
        return
    print(f"  Key ID: {KALSHI_KEY_ID}")
    print(f"  Private key loaded: {key.key_size}-bit RSA")
    # ── 1. Series catalog: what does Kalshi actually call these series now? ──
    print("\n── Series catalog (category=Sports) ───────────────────────────────")
    keywords = ["tennis", "wimbledon", "atp", "wta", "us open", "mls", "soccer",
                "nascar", "golf", "pga", "open championship", "nba", "nhl", "mlb",
                "world series", "stanley", "world cup", "fifa"]
    cursor, page, all_series = None, 0, []
    while page < 10:
        params = {"category": "Sports", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = _kalshi_get("/series", params)
        if not data or not data.get("series"):
            break
        all_series.extend(data["series"])
        cursor = data.get("cursor")
        page += 1
        if not cursor:
            break
    print(f"  {len(all_series)} sports series total")
    for s in all_series:
        hay = (s.get("ticker", "") + " " + s.get("title", "")).lower()
        if any(k in hay for k in keywords):
            print(f"  {s.get('ticker',''):28} {s.get('title','')[:70]}")

    # ── 2. Candidate series: event structure + name/price fields per market ──
    print("\n── Candidate series detail ────────────────────────────────────────")
    candidates = ["KXMLB", "KXMLSCUP", "KXNASCARCUPCHAMP", "KXNASCARCUPSERIES",
                  "KXATP", "KXWTA", "KXPGAWIN", "KXTHEOPEN", "KXUSOPEN",
                  "KXMWORLDCUP", "KXMENWORLDCUP", "KXWCROUND"]
    for ticker in candidates:
        markets = _fetch_markets_for_series(ticker)
        events = sorted({m.get("event_ticker", "?") for m in markets})
        print(f"  {ticker}: {len(markets)} markets, events: {events[:15]}")
        for m in markets[:4]:
            print(f"    ev={m.get('event_ticker','?')} status={m.get('status')} result={m.get('result')!r} "
                  f"bid={m.get('yes_bid_dollars')!r} ask={m.get('yes_ask_dollars')!r} "
                  f"last={m.get('last_price_dollars')!r}")
            print(f"      title={str(m.get('title'))[:70]!r} yes_sub={str(m.get('yes_sub_title'))[:40]!r}")
    print("\n  Full raw KXMLB market for complete field inventory:")
    mlb = _fetch_markets_for_series("KXMLB")
    if mlb:
        print("  " + json.dumps(mlb[0], default=str))

    # ── 3. Current KNOWN_SERIES fetch attempts with pick matching ──────────────
    print("\n── KNOWN_SERIES fetch + match check ───────────────────────────────")
    probe_targets = [
        ("NBA-champ",  KNOWN_SERIES["nba"],          dict(NBA_PICKS)),
        ("NHL-champ",  KNOWN_SERIES["nhl"],          dict(NHL_PICKS)),
        ("MLB-champ",  KNOWN_SERIES["mlb"],          dict(MLB_PICKS)),
        ("MLS-Cup",    KNOWN_SERIES["mls"],          dict(MLS_PICKS)),
        ("NASCAR",     KNOWN_SERIES["nascar"],       dict(NASCAR_PICKS)),
        ("Golf-Open",  KNOWN_SERIES["golf_open"],    dict(GOLF_PICKS)),
        ("Tennis-WB-M", KNOWN_SERIES["tennis_wb_m"], dict(TENNIS_MEN)),
        ("Tennis-WB-W", KNOWN_SERIES["tennis_wb_w"], dict(TENNIS_WOMEN)),
        ("Tennis-USO-M", KNOWN_SERIES["tennis_uso_m"], dict(TENNIS_MEN)),
        ("Tennis-USO-W", KNOWN_SERIES["tennis_uso_w"], dict(TENNIS_WOMEN)),
    ]
    for label, tickers, picks in probe_targets:
        result = _try_kalshi_series(tickers, picks, label)
        if result:
            found = ", ".join(f"{p}={v:.1%}" for p, v in sorted(result.items()))
            print(f"  ✓ {label}: {found}")
        else:
            print(f"  ✗ {label}: no data (tried: {tickers})")

    # ── 4. Auto-settle rules DRY RUN (no ledger writes) ────────────────────────
    print("\n── Auto-settle rule evaluation (dry run) ──────────────────────────")
    settled = _load_settled_ledger()
    for prop_id, rule in _AUTO_SETTLE_RULES.items():
        already = " [already in ledger]" if prop_id in settled else ""
        if rule[0] == "wins":
            r = _resolved_result(rule[1], rule[2])
            print(f"  {prop_id}: {rule[2]} → {r or 'unresolved'}{already}")
        elif rule[0] == "either_wins":
            ra = _resolved_result(rule[1], rule[2])
            rb = _resolved_result(rule[1], rule[3])
            outcome = "yes" if ra == "yes" else ("no" if rb == "yes" else None)
            print(f"  {prop_id}: {rule[2]}={ra or '?'} {rule[3]}={rb or '?'} → {outcome or 'unresolved'}{already}")
    print("────────────────────────────────────────────────────────────────────")


if __name__ == "__main__":
    import sys
    if "--probe" in sys.argv:
        probe()
    elif "--odds-only" in sys.argv:
        run_odds_only()
    else:
        run()
