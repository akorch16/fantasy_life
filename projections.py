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
N_SIMS           = 200_000   # 0.01% = 20 sims, so the 2-decimal long-shot odds on projections.html are not single-sim noise

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
# box_office: (p10, p50, p90) FULL-RUN domestic gross in $M — lognormal distribution
# release:    domestic opening date; only the share grossed by Dec 31 scores (BOM's 2026 year listing is calendar
#             gross and the season ends Dec 31) — see _in_season_share(). A Dec 18 opener banks ~2/3 of its run.
# rt:         (p10, p50, p90) Rotten Tomatoes score — normal distribution, capped 0–100
# actor/actress: [player_key, ...]  — just need to be in the movie
FILM_PIPELINE = [
    # Moana, The Odyssey, and Spider-Man: Brand New Day all released and got
    # real confirmed box office/RT/composite in data/actor.json + actress.json
    # months ago — they were left in here as "pending" long after release, so
    # every simulation draw was adding a SECOND random contribution on top of
    # the already-known real value for 7 of 13 players (Korch, Wu, Molmen,
    # Feder, Buckley, Mitchell, Theo), double-counting resolved outcomes as
    # if they were still uncertain. Removed. A film belongs here only from
    # the moment it's added until its real numbers land in data/actor.json /
    # data/actress.json — check both files before adding a new title, and
    # prune it the same day its composite gets filled in.
    {
        "title": "The Social Reckoning",
        "release": "2026-10-09",
        "box_office": (60, 100, 160),  # Oct 9; Social Network comp ($97M); award-season prestige
        "rt": (76, 88, 96),            # Sorkin direction, Jeremy Allen White / Jeremy Strong
        "actor":   ["Shep"],
        "actress": [],
    },
    {
        "title": "Avengers: Doomsday",
        "release": "2026-12-18",
        "box_office": (350, 500, 700),
        "rt": (68, 80, 90),
        "actor":   ["Mitchell", "Fryar"],
        "actress": ["Fryar"],
    },
    {
        "title": "Dune: Part Three",
        "release": "2026-12-18",
        "box_office": (180, 280, 400),
        "rt": (82, 91, 97),
        "actor":   ["Jamzee", "Buckley"],
        "actress": ["Wu", "Fryar", "Buckley"],
    },
    {
        "title": "Behemoth!",
        "release": "2026-12-04",
        "box_office": (25, 55, 100),   # Dec 4; mid-budget original — wide uncertainty
        "rt": (50, 66, 80),
        "actor":   ["Mitchell"],
        "actress": [],
    },
    {
        "title": "Focker-in-Law",
        "release": "2026-11-25",
        "box_office": (55, 95, 145),
        "rt": (40, 58, 72),
        "actor":   [],
        "actress": ["Tim"],
    },
    {
        "title": "Jumanji: Open World",
        "release": "2026-12-25",
        "box_office": (120, 175, 240),
        "rt": (60, 72, 80),
        "actor":   ["Theo"],
        "actress": [],
    },
]

FILM_DECAY_DAYS = 12.0   # share grossed after d days of release ≈ 1 - exp(-d/12): 7d 44%, 14d 69%, 27d 89%, 36d 95%
                          # (holiday comps: No Way Home ~70% of its run by Dec 31 after 15 days, Aquaman ~56% after 11)


def _in_season_share(release, today=None):
    """Fraction of a film's full domestic run earned by Dec 31 (days in release counted through Dec 31)."""
    if not release:
        return 1.0
    d = (SEASON_END - datetime.date.fromisoformat(release)).days + 1
    return 0.0 if d <= 0 else 1.0 - math.exp(-d / FILM_DECAY_DAYS)


# ─── Stock simulation parameters ─────────────────────────────────────────────
# ANNUALISED (drift_pct, volatility_pct) of the pick's price, from the PLAYER's perspective (positive =
# good for the pick; shorts are already sign-flipped). simulate() scales them to the time left in the
# season (drift × T, vol × √T, T = days to Dec 31 / 365) via _stock_params(), so the spread shrinks as
# the year runs out. (Until Oct 2026 these were fixed "rest of 2026 (~7 months)" values that were never
# shrunk, so by October the stock re-rank was ~1.7x too noisy.) Converted from those 7-month values:
# drift / (7/12), vol / sqrt(7/12).
STOCK_SIM_ANNUAL = {
    "Jamzee":   (-17.0, 52.0),  # INTC Long: big YTD run, mean-reversion risk
    "Mitchell": (  9.0, 65.0),  # CVNA Short: volatile, expected continued decline
    "Fryar":    ( 14.0, 33.0),  # AVGO Long: strong semiconductor fundamentals
    "Todd":     ( 21.0, 39.0),  # NVDA Long: AI spending still accelerating
    "Shep":     ( -9.0, 52.0),  # TSLA Short: recovery risk for short position
    "Buckley":  (  5.0, 20.0),  # NEE Long: stable regulated utility
    "Korch":    (  9.0, 59.0),  # SMCI Long: high volatility AI server play
    "Molmen":   ( 26.0, 33.0),  # TTWO Long: GTA VI launch catalyst
    "Theo":     (  9.0, 24.0),  # CMG Long: steady restaurant recovery
    "Feder":    ( 26.0, 46.0),  # PLTR Long: AI/government data momentum
    "Tim":      (  9.0, 59.0),  # COIN Long: crypto correlation, high vol
    "Wu":       ( 14.0, 33.0),  # LULU Long: athleisure recovery from lows
    "Jens":     ( 17.0, 46.0),  # SOFI Long: fintech recovery potential
}
SEASON_END = datetime.date(2026, 12, 31)


def _season_frac_left(today=None):
    today = today or datetime.datetime.now(datetime.timezone.utc).date()
    return max(0.0, (SEASON_END - today).days) / 365.0


def _stock_params(today=None):
    """{player: (mean_pct, sd_pct)} of the pick's remaining-season move (player's perspective)."""
    t = _season_frac_left(today)
    return {pl: (mu * t, sd * math.sqrt(t)) for pl, (mu, sd) in STOCK_SIM_ANNUAL.items()}


def _compound_stock(raw_pct, move_pct, short):
    """Apply a further move (player's perspective, %) to a YTD return (%). Returns compound on the
    current price, so +10% on a stock already up 128% adds ~23 points of YTD, not 10. Shorts are scored
    as -(price change), so the price ratio is 1 - raw for them."""
    move = max(move_pct, -95.0) / 100.0
    if short:
        ratio = (1 - raw_pct / 100.0) * (1 - move)
        return (1 - ratio) * 100.0
    ratio = (1 + raw_pct / 100.0) * (1 + move)
    return (ratio - 1) * 100.0


# ─── Country simulation parameters ───────────────────────────────────────────
# (expected_revision_pct, std_dev_pct): models uncertainty in the October 2026
# IMF WEO GDP growth forecast revision relative to the current April 2026 forecast.
# The October 2026 WEO (published 2026-10-13, now in data/country.json) is the last IMF edition before the
# Dec 31 season end, so there is no further revision to simulate: noise is zero (kept per player for the shape).
COUNTRY_SIM = {pl: (0.0, 0.0) for pl in ["Korch", "Todd", "Jamzee", "Feder", "Wu", "Fryar", "Buckley",
                                         "Theo", "Shep", "Tim", "Jens", "Molmen", "Mitchell"]}

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
    """Best market for a pick. Exact yes_sub_title match first, searched across
    ALL markets regardless of resolution status — Kalshi uses city-style names
    ('New York Y', 'Los Angeles D'), so fuzzy word overlap alone would hit both
    New York teams. Fuzzy haystack match (ACTIVE markets only) is the fallback.

    The exact-match tier deliberately does NOT restrict to active markets: a
    team that's been eliminated has its market resolved (result='no'), and
    that's real, useful information (see _extract_probs) -- excluding it here
    used to mean an eliminated team's exact match was silently skipped, falling
    through to the fuzzy tier, which then matched a *different* team sharing
    the same city purely on the word 'York'/'Angeles'/'Chicago' overlap
    (confirmed live: New York Mets, resolved/eliminated, fell through and
    fuzzy-matched the still-active New York Yankees market instead)."""
    words = pick_name.split()
    cands = {pick_name.lower().strip()}
    if len(words) >= 2:
        city = " ".join(words[:-1]).lower()
        cands.add(city)                                # 'tampa bay'
        cands.add(city + " " + words[-1][0].lower())   # 'new york y'
        if city == "la":
            cands.add("los angeles")                   # Kalshi lists LA Galaxy as 'Los Angeles'
    for m in markets:
        if str(m.get("yes_sub_title") or "").lower().strip() in cands:
            return m
    # NOTE: active markets have result == '' (empty string), NOT null —
    # a `result is not None` check would skip every live market.
    active = [m for m in markets if not m.get("result")]
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

    A resolved market (result='yes'/'no') is priced from that result directly,
    NOT from bid/ask — a dead market's orderbook is stale noise, not a signal.
    Confirmed live: an eliminated team's finalized market still reported
    yes_ask_dollars=1.0000/yes_bid_dollars=0.0000 (leftover pre-resolution
    quotes), which the old bid/ask-midpoint logic would have averaged into a
    nonsensical 50% instead of the correct 0%.
    """
    probs = {}
    for player, pick in picks_dict.items():
        m = _pick_market(markets, pick)
        if m is None:
            continue
        try:
            result = m.get("result")
            if result == "yes":
                probs[player] = 1.0
                continue
            if result == "no":
                continue  # resolved loser: 0% — omit, same as "not found"
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


def _scores_updated():
    """UTC datetime scores.json was generated (the snapshot MLS points reflect)."""
    try:
        with open(SCORES_PATH) as f:
            ts = json.load(f)["last_updated"]
        return datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M UTC").replace(
            tzinfo=datetime.timezone.utc)
    except Exception:
        return None


def _mlb_champ_pct(owner):
    """Kalshi World Series win probability (1-99) for an owner's team. A present
    but ~0 probability (eliminated) clamps to 1 rather than falling back to the
    static price, which would let bettors take stale odds on a dead outcome."""
    def fn(o):
        p = o.get("mlb_champ", {}).get(owner)
        return None if p is None else min(99, max(1, round(p * 100)))
    return fn


def _mlb_nlcs_wu_v_buckley(o):
    """P(Dodgers beat Brewers) ≈ Wu's share of the two teams' World Series odds,
    clamped to 1-99 so a decided series can't revert to the static price."""
    c = o.get("mlb_champ", {})
    a, b = c.get("Wu"), c.get("Buckley")
    if a is None or b is None or a + b <= 0:
        return None
    return min(99, max(1, round(a / (a + b) * 100)))


def _mlb_alcs_fryar(o):
    """P(Guardians win the ALCS) from Kalshi's Guardians World Series price.
    Rays aren't an owner pick, so there is no direct series market. Winning the
    ALCS is necessary to win the title, and the pennant winner is roughly a coin
    flip against the NL champion, so P(ALCS) ≈ P(title) / 0.5, clamped to 1-99.
    Collapses toward 1 as Cleveland falls behind and toward 99 once it advances."""
    p = o.get("mlb_champ", {}).get("Fryar")
    return None if p is None else min(99, max(1, round(p / 0.5 * 100)))


# MLS regular-season kickoffs (UTC) through Oct 31 for the Oct 31 snapshot bets,
# from ESPN's scoreboard on 2026-10-15, plus matches played (for points-per-game).
# Remaining matches = kickoffs after scores.json was generated, so price and
# standings always describe the same moment.
_MLS_OCT31 = {
    "Feder":  {"gp": 29, "kickoffs": ["2026-10-18T00:30Z", "2026-10-25T00:30Z", "2026-10-29T02:30Z"]},
    "Theo":   {"gp": 29, "kickoffs": ["2026-10-17T23:30Z", "2026-10-24T21:30Z", "2026-10-28T23:30Z"]},
    "Korch":  {"gp": 28, "kickoffs": ["2026-10-18T21:00Z", "2026-10-21T23:00Z", "2026-10-24T23:30Z",
                                     "2026-10-28T23:30Z", "2026-10-31T18:00Z"]},
    "Molmen": {"gp": 30, "kickoffs": ["2026-10-18T02:30Z", "2026-10-26T01:00Z", "2026-10-31T21:00Z"]},
}


def _mls_points_dist(pts, gp, n_games):
    """Distribution of points gained over n_games: win 3 / draw 1 / loss 0 with a
    league-typical 25% draw rate and a points-per-game estimate shrunk 40% toward
    the league mean (1.35) so a short sample doesn't dominate."""
    ppg = 0.6 * (pts / max(gp, 1)) + 0.4 * 1.35
    draw = 0.25
    win = max(0.02, min(0.7, (ppg - draw) / 3))
    step = {0: 1 - win - draw, 1: draw, 3: win}
    dist = {0: 1.0}
    for _ in range(n_games):
        nxt = {}
        for have, p in dist.items():
            for gain, q in step.items():
                nxt[have + gain] = nxt.get(have + gain, 0) + p * q
        dist = nxt
    return dist


def _mls_oct31_h2h(owner_a, owner_b):
    """P(A's team has strictly more MLS points than B's after the Oct 31 matches),
    conditional on no tie (a tie is a push). Uses live leaderboard points and only
    the matches not yet reflected in them. Staleness: scores.json refreshes daily,
    so a match played since the last scoring run still counts as 'remaining'."""
    def fn(o):
        pts = o.get("mls_points", {})
        pa, pb = pts.get(owner_a), pts.get(owner_b)
        if pa is None or pb is None:
            return None
        since = o.get("scores_updated") or datetime.datetime.now(datetime.timezone.utc)

        def remaining(owner):
            return sum(1 for k in _MLS_OCT31[owner]["kickoffs"]
                       if datetime.datetime.strptime(k, "%Y-%m-%dT%H:%MZ").replace(
                           tzinfo=datetime.timezone.utc) > since)
        da = _mls_points_dist(pa, _MLS_OCT31[owner_a]["gp"], remaining(owner_a))
        db = _mls_points_dist(pb, _MLS_OCT31[owner_b]["gp"], remaining(owner_b))
        win = tie = 0.0
        for x, px in da.items():
            for y, py in db.items():
                if pa + x > pb + y:
                    win += px * py
                elif pa + x == pb + y:
                    tie += px * py
        p = 0.5 if tie >= 0.999999 else win / (1 - tie)
        return min(99, max(1, round(p * 100)))
    return fn


def _pts_oct31_buckley_v_jamzee(o):
    """P(Buckley > Jamzee on Oct 31). They're tied at 146.5 and Jamzee has no
    postseason team, so it's driven by Milwaukee winning the NLCS (+2.5 bonus):
    q ≈ Brewers' share of the Dodgers+Brewers World Series odds. If Milwaukee
    wins, Buckley stays ahead ~95% (other categories can still flip it); if it
    loses, it's a ~42% coin flip decided by MLS/stock/tennis/chart drift."""
    c = o.get("mlb_champ", {})
    q = _h2h(c.get("Buckley", 0), c.get("Wu", 0))
    if q is None:
        return None
    q /= 100
    return round((q * 0.95 + (1 - q) * 0.42) * 100)


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
    # "By July 1" snapshot props — titles/display all say Jul 1; these were
    # miscategorized as season-long (Dec 31) when the schedule was first built,
    # which left wagering open on them for three weeks past their real close.
    "stocks-fryar-avgo-v-mitchell-cvna": ("2026-07-01T00:00:00Z", "2026-07-05T00:00:00Z"),
    "pts-wu-v-korch":        ("2026-07-01T00:00:00Z", "2026-07-05T00:00:00Z"),
    "pts-tim-v-molmen":      ("2026-07-01T00:00:00Z", "2026-07-05T00:00:00Z"),
    "pts-jamzee-v-fryar":    ("2026-07-01T00:00:00Z", "2026-07-05T00:00:00Z"),
    "pts-mitchell-v-todd":   ("2026-07-01T00:00:00Z", "2026-07-05T00:00:00Z"),
    "pts-buckley-v-theo":    ("2026-07-01T00:00:00Z", "2026-07-05T00:00:00Z"),
    # MLB postseason — stay open until the series can no longer be undecided (G7 first
    # pitch); settlement locks them earlier. Prices track Kalshi so they move with the games.
    "mlb-nlcs-wu-v-buckley":     ("2026-10-20T00:00:00Z", "2026-10-21T00:00:00Z"),  # NLCS G7 first pitch
    "mlb-alcs-fryar-wins":       ("2026-10-21T00:00:00Z", "2026-10-22T12:00:00Z"),  # ALCS G7 first pitch
    "mlb-ws-buckley-wins":       ("2026-10-24T00:00:00Z", "2026-11-03T00:00:00Z"),  # WS G1
    # Snapshot props stay open until the last relevant match/race; live-priced where possible
    "mls-oct31-feder-v-theo":    ("2026-10-28T23:30:00Z", "2026-11-02T12:00:00Z"),  # first kickoff of their last matches
    "mls-oct31-korch-v-molmen":  ("2026-10-31T18:00:00Z", "2026-11-02T12:00:00Z"),  # first kickoff of their last matches
    "nascar-talladega-theo-v-wu": ("2026-10-18T19:00:00Z", "2026-10-26T12:00:00Z"),  # Phoenix green flag
    "pts-oct31-buckley-v-jamzee": ("2026-10-20T00:00:00Z", "2026-11-02T12:00:00Z"),  # closes with the NLCS
    # Genuinely season-long
    "todd-wins-fl-2026":     ("2026-12-31T00:00:00Z", "2027-01-01T00:00:00Z"),
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
    # KXMLB titles use the city ("Will Tampa Bay win the 2026 Pro Baseball Championship?")
    "mlb-ws-buckley-wins":        ("wins", "mlb", "Milwaukee"),
    # Series winners with no Kalshi market: Tavily news + Claude extraction
    # (settle_rules.tavily_series). Eligible from the earliest possible clincher.
    "mlb-nlcs-wu-v-buckley":      ("tavily_series", "NLCS", "Los Angeles Dodgers",
                                   "Milwaukee Brewers", "2026-10-16T00:00:00Z"),
    "mlb-alcs-fryar-wins":        ("tavily_series", "ALCS", "Cleveland Guardians",
                                   "Tampa Bay Rays", "2026-10-17T00:00:00Z"),
    # Oct 31 snapshots settle off the leaderboard generated on the Nov 1 (UTC) run
    # (settle_rules.score_cmp): A > B -> yes, A < B -> no, tie -> push.
    "mls-oct31-feder-v-theo":     ("score_cmp", "mls",   "Feder",   "Theo",
                                   "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z"),
    "mls-oct31-korch-v-molmen":   ("score_cmp", "mls",   "Korch",   "Molmen",
                                   "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z"),
    "pts-oct31-buckley-v-jamzee": ("score_cmp", "total", "Buckley", "Jamzee",
                                   "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z"),
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

    # ── MLB postseason (Oct 2026) ────────────────────────────────────────────────
    # NLCS/pts odds are Kalshi-derived (share of WS odds); ALCS has no Kalshi series.
    ("mlb-nlcs-wu-v-buckley",   40, _mlb_nlcs_wu_v_buckley, "MLB-WorldSeries"),
    ("mlb-alcs-fryar-wins",     38, _mlb_alcs_fryar, "MLB-WorldSeries"),  # Kalshi title price / 0.5
    ("mlb-ws-buckley-wins",     30, _mlb_champ_pct("Buckley"), "MLB-WorldSeries"),

    # ── MLS through Oct 31 (live: leaderboard points + remaining fixtures) ─────────
    ("mls-oct31-feder-v-theo",   73, _mls_oct31_h2h("Feder", "Theo"),    "mls-standings"),
    ("mls-oct31-korch-v-molmen", 78, _mls_oct31_h2h("Korch", "Molmen"),  "mls-standings"),

    # ── NASCAR playoff points after Talladega (static, priced 2026-10-12) ──────────
    ("nascar-talladega-theo-v-wu", 49, None, None),  # Hamlin 2318 v Bell 2316

    # ── Total Points by Oct 31 ────────────────────────────────────────────────────
    ("pts-oct31-buckley-v-jamzee", 74, _pts_oct31_buckley_v_jamzee, "MLB-WorldSeries"),

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


def auto_settle():
    """Evaluate _AUTO_SETTLE_RULES: resolved Kalshi markets, leaderboard
    snapshots, and Tavily-sourced series results (see settle_rules.py).
    Appends any newly decided props to data/sb_settled.json.
    Returns the list of new ledger entries."""
    import settle_rules
    settled = _load_settled_ledger()
    new_entries = []
    for prop_id, rule in _AUTO_SETTLE_RULES.items():
        if prop_id in settled:
            continue
        outcome = None
        if rule[0] == "score_cmp":
            outcome = settle_rules.score_cmp(rule)
        elif rule[0] == "tavily_series":
            outcome = settle_rules.tavily_series(rule)
        elif rule[0] == "wins":
            outcome = _resolved_result(rule[1], rule[2])
        elif rule[0] == "either_wins":
            if _resolved_result(rule[1], rule[2]) == "yes":
                outcome = "yes"
            elif _resolved_result(rule[1], rule[3]) == "yes":
                outcome = "no"
        if outcome:
            print(f"  🏁 AUTO-SETTLE {prop_id} → {outcome} ({rule[0]})")
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


# NASCAR's 2026 Chase has no eliminations: the champion is whoever has the most
# points after all 10 postseason races (Nov 8, Homestead), and the bonus pays the
# final standings positions 1-5 (rules.html). Position odds come from Plackett-Luce
# sampling off the Kalshi champion odds, over the 16-driver Chase field.
NASCAR_FINISH_PTS = (13.0, 9.0, 6.5, 4.0, 2.5)
NASCAR_CHASE_FIELD = 16
# Picks who did not make the 16-car Chase (data/nascar.json: below the 2000-2100 reset scale) can't finish top 5.
# Kalshi's champion market still quotes them at a stale ~1c, which used to hand Mitchell/Buckley a NASCAR
# title in thousands of sims — so they are zeroed, and they don't use up Chase-field slots either.
NASCAR_MISSED_CHASE = {"Shane van Gisbergen", "Ross Chastain"}


def _sample_nascar_finish(champ_probs):
    """Sample the top-5 final standings. Returns {player: bonus_pts} for picks only.
    Probability mass not held by our picks is spread over dummy field drivers, so
    other drivers can take podium spots (and the pick's points) too."""
    weights = {k: v for k, v in champ_probs.items()
               if v > 0 and NASCAR_PICKS.get(k) not in NASCAR_MISSED_CHASE}
    n_other = max(1, NASCAR_CHASE_FIELD - len(weights))
    other = _other_prob(champ_probs)
    for i in range(n_other):
        weights[("_other", i)] = other / n_other if other > 0 else 1e-9
    results = {}
    for pts in NASCAR_FINISH_PTS:
        key = _weighted_sample({k: w / sum(weights.values()) for k, w in weights.items()})
        if key is None:
            break
        if not isinstance(key, tuple):
            results[key] = pts
        weights.pop(key)
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


# Last day of each recurring event. Once it has passed, the result is history that is
# already in scores.json (as baseline/bonus points) — NOT a forecast. All four golf majors
# and all four slams are done for 2026; simulating them again from stale June FALLBACK
# odds was handing out phantom bonus points.
EVENT_END = {
    "golf_uso":         datetime.date(2026, 6, 21),
    "golf_open":        datetime.date(2026, 7, 19),
    "tennis_french":    datetime.date(2026, 6, 7),
    "tennis_wimbledon": datetime.date(2026, 7, 12),
    "tennis_usopen":    datetime.date(2026, 9, 13),
}


def _event_done(odds_key, today=None):
    """True once the event behind an odds key (golf_uso_win, tennis_french_men_ru…) has ended."""
    end = EVENT_END.get("_".join(odds_key.split("_")[:2]))
    return bool(end) and (today or datetime.date.today()) > end


# Categories whose points are re-ranked from sampled raw values each run.
RERANKED = ("actor", "actress", "stock", "country")
SIM_CATS = ("nba", "nhl", "mlb", "mls", "nascar", "golf", "tennis") + RERANKED


def _build_mls_playoff_model(odds, markets_used):
    """Full-table MLS playoff model for simulate(), or None to fall back to the
    champion-only sampler. Needs the stored 30-team MLS table, fresh enough that
    no scheduled match since it was saved is missing from it."""
    try:
        import db as _db
        import mls_playoffs as _mp
        rows = (_db.get_standing("MLS") or {}).get("standings") or []
        updated = _db.get_standing_updated_at("MLS")
        if not rows or not updated:
            print("  ℹ MLS playoff model: no stored MLS table — using champion-only sampler")
            return None
        since = datetime.datetime.fromisoformat(updated.replace("Z", "+00:00"))
        if since.tzinfo is None:
            since = since.replace(tzinfo=datetime.timezone.utc)
        sched = _mp.load_schedule()
        now = datetime.datetime.now(datetime.timezone.utc)
        if sched:
            missed = [f for f in sched["fixtures"]
                      if since < _mp._parse_ts(f["t"]) < now - datetime.timedelta(hours=36)]
            if missed:
                print(f"  ℹ MLS playoff model: table is {len(missed)} match(es) behind — using champion-only sampler")
                return None
        targets = None
        if "MLS-Cup" in markets_used:
            targets = {}
            for owner, q in odds.get("mls_champ", {}).items():
                k = _mp.team_key(MLS_PICKS.get(owner))
                if k and q:
                    targets[k] = q
        model = _mp.build_model({r["team"]: r["points"] for r in rows}, since, targets, sched)
        if model is None:
            print("  ℹ MLS playoff model: table incomplete — using champion-only sampler")
        else:
            print(f"  ✓ MLS playoff model: {len(model.fixtures)} fixtures left"
                  f"{', calibrated to Kalshi' if model.calibration else ''}")
        return model
    except Exception as e:
        print(f"  ⚠ MLS playoff model failed ({e}) — using champion-only sampler")
        return None


def simulate(current_scores, odds, n=N_SIMS):
    """
    Run n Monte Carlo simulations.
    Returns ({player: {win_pct, top4_pct, projected_total, projected_p10, projected_p90,
    category_expected}}, pairwise).

    Bookkeeping invariant: every player starts from their CURRENT total, minus only the
    baseline points of the categories that are re-ranked each run (actor/actress/stock/country).
    Earned bonus points are never stripped. Each bonus block adds only what can still change,
    as a delta over what is already banked. So Σ(projected_total − current_total) over the
    league is >= 0 (re-ranking is zero-sum; bonuses only add), and
    projected_total == current_total + Σ category_expected for every player.
    """
    players_list = [p["name"] for p in current_scores]
    by_name = {p["name"]: p for p in current_scores}

    base, cur_pts = {}, {c: {} for c in RERANKED}
    for p in current_scores:
        total = p["total"]
        for cat in RERANKED:
            bp = p["categories"].get(cat, {}).get("baseline_pts", 0) or 0
            cur_pts[cat][p["name"]] = bp
            total -= bp
        base[p["name"]] = total

    def raw(cat):
        return {nm: by_name[nm]["categories"].get(cat, {}).get("raw_value") or 0.0 for nm in players_list}

    def bonus(cat):
        return {nm: by_name[nm]["categories"].get(cat, {}).get("bonus_pts", 0) or 0 for nm in players_list}

    current_actor_comp, current_actress_comp = raw("actor"), raw("actress")
    current_stock_raw, current_country_raw = raw("stock"), raw("country")
    current_nba, current_nhl = bonus("nba"), bonus("nhl")
    current_mlb, current_mls, current_nascar = bonus("mlb"), bonus("mls"), bonus("nascar")

    # Once a champion (bonus_pts == 13.0) is crowned the season is fully decided and nobody's
    # bonus can change further — nothing to sample.
    nba_decided = any(v >= 13.0 for v in current_nba.values())
    nhl_decided = any(v >= 13.0 for v in current_nhl.values())

    # Full-table model (qualification, play-in, every round) while no MLS bonus is banked.
    # Once real playoff bonuses exist the sampler below must not re-roll a bracket that
    # already has results, so fall back to it (its Kalshi odds zero out eliminated teams).
    mls_model = odds.get("mls_playoff_model")
    if mls_model and any(v > 0 for v in current_mls.values()):
        mls_model = None
    mls_owner_keys = {}
    if mls_model:
        import mls_playoffs as _mp
        mls_owner_keys = {o: _mp.team_key(t) for o, t in MLS_PICKS.items()}

    nba_norm    = _normalize(odds["nba_champ"])
    nhl_norm    = _normalize(odds["nhl_champ"])
    mlb_norm    = _normalize(odds["mlb_champ"])
    mls_norm    = _normalize(odds["mls_champ"])
    nascar_norm = _normalize(odds["nascar_champ"])

    tennis_pairs = [pr for pr in [
        ("tennis_french_men_win",     "tennis_french_men_ru"),
        ("tennis_french_women_win",   "tennis_french_women_ru"),
        ("tennis_wimbledon_men_win",  "tennis_wimbledon_men_ru"),
        ("tennis_wimbledon_women_win","tennis_wimbledon_women_ru"),
        ("tennis_usopen_men_win",     "tennis_usopen_men_ru"),
        ("tennis_usopen_women_win",   "tennis_usopen_women_ru"),
    ] if not _event_done(pr[0])]
    golf_pairs = [pr for pr in [
        ("golf_uso_win",  "golf_uso_ru"),
        ("golf_open_win", "golf_open_ru"),
    ] if not _event_done(pr[0])]

    sim_totals = {name: [] for name in players_list}
    cat_add = {c: {name: 0.0 for name in players_list} for c in SIM_CATS}
    wins  = {name: 0 for name in players_list}
    top4s = {name: 0 for name in players_list}
    totals = {}

    def add(cat, player, pts):
        if pts:
            totals[player] += pts
            cat_add[cat][player] += pts

    def add_bonus(cat, player, new, old):
        """Playoff bonuses replace what is banked: only the increase is new points."""
        if new > old:
            add(cat, player, new - old)

    def add_reranked(cat, ranked_pts):
        for player, pts in ranked_pts.items():
            totals[player] += pts
            cat_add[cat][player] += pts - cur_pts[cat][player]

    stock_params = _stock_params()
    stock_short = {pl: info.get("direction") == "S" for pl, info in DRAFT_PICKS_2026["Stock"].items()}
    today = datetime.datetime.now(datetime.timezone.utc).date()
    film_share = {f["title"]: _in_season_share(f.get("release"), today) for f in FILM_PIPELINE}

    for _ in range(n):
        totals = dict(base)

        # ── NBA / NHL: sample conference finals + Finals (skip if already decided) ─
        if not nba_decided:
            res = _simulate_playoffs_conf(odds["nba_conf_finals_west"], odds["nba_conf_finals_east"], nba_norm)
            for player in NBA_PICKS:
                old = current_nba[player]
                if old >= 6.5:
                    add_bonus("nba", player, MILESTONES.get(res.get(player, "semi"), 6.5), old)
        if not nhl_decided:
            res = _simulate_playoffs_conf(odds["nhl_conf_finals_west"], odds["nhl_conf_finals_east"], nhl_norm)
            for player in NHL_PICKS:
                old = current_nhl[player]
                if old >= 6.5:
                    add_bonus("nhl", player, MILESTONES.get(res.get(player, "semi"), 6.5), old)

        # ── MLB / MLS / NASCAR: sample full playoff outcomes ────────────────
        # Eliminated teams keep what they banked; teams still alive keep their floor unless
        # the sampled outcome beats it.
        for player, pts in _sample_playoff_sport(mlb_norm).items():
            add_bonus("mlb", player, pts, current_mlb[player])
        mls_sample = (mls_model.sample_owner_bonuses(mls_owner_keys) if mls_model
                      else _sample_playoff_sport(mls_norm))
        for player, pts in mls_sample.items():
            add_bonus("mls", player, pts, current_mls[player])
        for player, pts in _sample_nascar_finish(nascar_norm).items():
            add_bonus("nascar", player, pts, current_nascar[player])

        # ── Golf / Tennis: only events that have not happened yet ───────────
        for wk, rk in golf_pairs:
            winner, runner_up = _sample_major(odds[wk], odds[rk])
            if winner:     add("golf", winner, 6.0)
            if runner_up:  add("golf", runner_up, 2.5)
        for wk, rk in tennis_pairs:
            winner, runner_up = _sample_major(odds.get(wk, {}), odds.get(rk, {}))
            if winner:     add("tennis", winner, 4.0)
            if runner_up:  add("tennis", runner_up, 2.5)

        # ── Actor / Actress: sample each upcoming film's box office + RT ────
        actor_comp   = dict(current_actor_comp)
        actress_comp = dict(current_actress_comp)
        for film in FILM_PIPELINE:
            box    = _sample_lognormal(*film["box_office"]) * film_share[film["title"]]
            rt     = _sample_normal_capped(*film["rt"])
            contrib = (rt / 100.0) * box
            for player in film["actor"]:
                actor_comp[player]   = actor_comp.get(player, 0.0)   + contrib
            for player in film["actress"]:
                actress_comp[player] = actress_comp.get(player, 0.0) + contrib
        add_reranked("actor",   _rank_composites(players_list, actor_comp))
        add_reranked("actress", _rank_composites(players_list, actress_comp))

        # ── Stock: sample additional return, re-rank ────────────────────────
        stock_sim = {pl: _compound_stock(current_stock_raw.get(pl, 0.0), random.gauss(*stock_params[pl]),
                                         stock_short.get(pl, False)) for pl in stock_params}
        add_reranked("stock", _rank_composites(players_list, stock_sim))

        # ── Country: re-rank (Oct 2026 WEO is final for the season → zero noise) ─
        country_sim = {pl: current_country_raw.get(pl, 0.0) + random.gauss(*COUNTRY_SIM[pl]) for pl in COUNTRY_SIM}
        add_reranked("country", _rank_composites(players_list, country_sim))

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
            "win_pct":         round(wins[name] / n * 100, 4),   # 4 dp: long shots are 1-in-10,000s
            "top4_pct":        round(top4s[name] / n * 100, 2),
            "projected_total": round(sum(sims) / n, 1),
            "projected_p10":   round(sims[int(n * 0.10)], 1),
            "projected_p90":   round(sims[int(n * 0.90)], 1),
            "category_expected": {c: round(cat_add[c][name] / n, 2) for c in SIM_CATS
                                  if abs(cat_add[c][name] / n) > 0.01},
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
    odds["mls_playoff_model"] = _build_mls_playoff_model(odds, markets_used)

    print("\n── Running Monte Carlo simulation ─────────────────────────────")
    sim_results, pairwise = simulate(current_scores, odds)

    # Assemble output. projected_additional is derived from the SAME simulation as
    # projected_total, so PROJ == NOW + EXP always holds (a separate heuristic used to disagree).
    players_out = []
    for p in current_scores:
        name = p["name"]
        sr = sim_results[name]
        players_out.append({
            "name":               name,
            "current_total":      p["total"],
            "projected_additional": round(sr["projected_total"] - p["total"], 1),
            "projected_total":    sr["projected_total"],
            "projected_p10":      sr["projected_p10"],
            "projected_p90":      sr["projected_p90"],
            "win_pct":            sr["win_pct"],
            "top4_pct":           sr["top4_pct"],
            "category_expected":  sr["category_expected"],
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
    odds["scores_updated"] = _scores_updated()

    # Auto-settle props whose Kalshi markets have resolved, pay out, flag overdue
    newly_settled = auto_settle()
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
    append_projection_history(output)

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


HISTORY_PATH = os.path.join(os.path.dirname(__file__), "docs", "projection_history.json")


def append_projection_history(output):
    """Keep one snapshot per UTC day of every player's win% / top-4% / projected / current total
    (the last full run of the day wins). Read by the trend chart on docs/projections.html.
    --odds-only runs never call this: they don't re-run the Monte Carlo."""
    try:
        with open(HISTORY_PATH) as f:
            hist = json.load(f)
    except (OSError, ValueError):
        hist = {"days": []}
    gen = output["generated_at"]
    snap = {"date": gen[:10], "generated_at": gen,
            "players": {p["name"]: {"win": round(p["win_pct"], 2), "top4": round(p["top4_pct"], 2),
                                    "proj": round(p["projected_total"], 1), "cur": round(p["current_total"], 1)}
                        for p in output["players"]}}
    days = [d for d in hist.get("days", []) if d.get("date") != snap["date"]]
    days.append(snap)
    hist["days"] = sorted(days, key=lambda d: d["date"])
    with open(HISTORY_PATH, "w") as f:
        json.dump(hist, f, separators=(",", ":"))


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
    odds["scores_updated"] = _scores_updated()

    newly_settled = auto_settle()
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
    print("\n  All KXMLB tickers, with status/result (checking whether the Mets")
    print("  market has already been finalized/excluded from the active-only")
    print("  list _pick_market's exact-match tier searches, forcing a fallback")
    print("  to fuzzy matching that could latch onto the still-active Yankees):")
    for m in sorted(mlb, key=lambda m: m.get("ticker", "")):
        print(f"    ticker={m.get('ticker'):20} yes_sub={str(m.get('yes_sub_title')):20} "
              f"status={m.get('status'):12} result={m.get('result')!r:6} "
              f"ask={m.get('yes_ask_dollars')!r}")

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
