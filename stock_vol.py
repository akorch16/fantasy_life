"""Correlated stock-move model for projections.simulate().

Each pick's rest-of-season price move is drawn jointly with the others, from Yahoo daily closes:

* volatility = realized vol of the last WINDOW trading days (annualised), blended VOL_BLEND with the hand-set
  STOCK_SIM_ANNUAL vol so one quiet or wild quarter doesn't swing it too far;
* correlation = sample correlation of the same daily log returns, shrunk toward the identity (SHRINK) so
  the matrix stays well-conditioned; the AI/semis cluster (NVDA, AVGO, SMCI, PLTR, INTC) and the risk-on
  names (COIN, SOFI) then move together instead of independently;
* moves are lognormal on the PRICE (drift from STOCK_SIM_ANNUAL, player's perspective; shorts gain when the
  price falls), scaled to the time left: log-return ~ N(ln(1 + drift*T) - sd^2*T/2, sd^2*T).

If Yahoo can't be reached for a ticker, that pick falls back to its STOCK_SIM_ANNUAL vol with zero
correlation to the rest.
"""
import math
import random

import requests

WINDOW = 63            # ~3 months of trading days
VOL_BLEND = 0.75       # weight on realized vol (rest = hand-set vol)
SHRINK = 0.15          # correlation shrinkage toward the identity
TRADING_DAYS = 252
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{t}?interval=1d&range=6mo"


def fetch_closes(ticker, timeout=10):
    """{unix_ts: close} of daily closes, or {} on failure."""
    try:
        r = requests.get(CHART_URL.format(t=ticker), timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        res = (r.json().get("chart", {}).get("result") or [])[0]
        ts = res.get("timestamp") or []
        cl = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
        return {t: c for t, c in zip(ts, cl) if c}
    except Exception:
        return {}


def _cholesky(a):
    n = len(a)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = a[i][j] - sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                L[i][i] = math.sqrt(max(s, 1e-12))
            else:
                L[i][j] = s / L[j][j]
    return L


class StockModel:
    def __init__(self, picks, annual, closes, window=WINDOW):
        """picks: {player: (ticker, is_short)}; annual: {player: (drift_pct, vol_pct)} (player's perspective);
        closes: {ticker: {ts: close}}."""
        self.players = [p for p in picks if p in annual]
        self.short = {p: picks[p][1] for p in self.players}
        # drift is stated from the player's side; convert to the price's side
        self.price_drift = {p: (-1 if self.short[p] else 1) * annual[p][0] / 100.0 for p in self.players}
        rets = {}
        live = [p for p in self.players if len(closes.get(picks[p][0]) or {}) > window]
        if live:
            common = sorted(set.intersection(*(set(closes[picks[p][0]]) for p in live)))[-(window + 1):]
            if len(common) > 20:
                for p in live:
                    c = closes[picks[p][0]]
                    rets[p] = [math.log(c[b] / c[a]) for a, b in zip(common, common[1:])]
        self.source = {}
        self.vol = {}
        for p in self.players:
            hand = annual[p][1] / 100.0
            if p in rets:
                r = rets[p]
                m = sum(r) / len(r)
                realized = math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1) * TRADING_DAYS)
                self.vol[p] = VOL_BLEND * realized + (1 - VOL_BLEND) * hand
                self.source[p] = ("yahoo", realized)
            else:
                self.vol[p] = hand
                self.source[p] = ("hand-set", hand)
        n = len(self.players)
        corr = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
        for i, a in enumerate(self.players):
            for j, b in enumerate(self.players):
                if i < j and a in rets and b in rets:
                    c = _corr(rets[a], rets[b]) * (1 - SHRINK)
                    corr[i][j] = corr[j][i] = c
        self.corr = corr
        self.L = _cholesky(corr)

    def sample_moves(self, t, rng=random):
        """{player: move_pct from the player's perspective} over T = t years."""
        z = [rng.gauss(0.0, 1.0) for _ in self.players]
        out = {}
        for i, p in enumerate(self.players):
            eps = sum(self.L[i][k] * z[k] for k in range(i + 1))
            sd = self.vol[p]
            mu = math.log(max(1e-6, 1 + self.price_drift[p] * t)) - 0.5 * sd * sd * t
            ratio = math.exp(mu + sd * math.sqrt(t) * eps)
            out[p] = (1 - ratio) * 100.0 if self.short[p] else (ratio - 1) * 100.0
        return out

    def summary(self):
        lines = []
        for p in self.players:
            src, v = self.source[p]
            lines.append(f"{p}: vol {self.vol[p]*100:.0f}% ({src} {v*100:.0f}%)")
        return lines


def _corr(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    sa = math.sqrt(sum((x - ma) ** 2 for x in a))
    sb = math.sqrt(sum((y - mb) ** 2 for y in b))
    if not sa or not sb:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb)


def build_model(stock_picks, annual):
    """stock_picks: DRAFT_PICKS_2026['Stock'] ({player: {ticker, direction}}). Never raises."""
    picks = {p: (info["ticker"], info.get("direction") == "S") for p, info in stock_picks.items()}
    closes = {t: fetch_closes(t) for t in {tk for tk, _ in picks.values()}}
    return StockModel(picks, annual, closes)
