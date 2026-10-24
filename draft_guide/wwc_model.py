"""2027 FIFA Women's World Cup model for the Country bonus (draft guide).

Prices in  : raw/kalshi_wwc_<date>.json (KXWCW-27 champion market, one price per team).
Output     : data/WWC.json — per team, probability of reaching each round and E[bonus].

32 teams -> 8 groups of 4 (pot draw by rating) -> top two advance -> Round of 16 -> QF -> SF -> Final.
Bonus ladder (league rule added Oct 2026; tier mapping ASSUMED, confirm with the commissioner):
    champion 13 / lost final 9 / lost semifinal 6.5 / lost quarterfinal 4 / lost Round of 16 2.5 / out in groups 0
Team strength is tilted (damped, clipped) until simulated title odds match the market's.

    python3 draft_guide/wwc_model.py --refresh-prices   # pull live Kalshi prices (needs network), then rebuild
    python3 draft_guide/wwc_model.py                    # rebuild WWC.json from the latest saved prices
"""
import datetime
import glob
import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
OUT = os.path.join(HERE, "data", "WWC.json")

LADDER = {"champ": 13.0, "final": 9.0, "semi": 6.5, "quarter": 4.0, "r16": 2.5}
SCALE = 1.0          # rating gap -> win log-odds in a knockout game
GROUP_SCALE = 1.1    # group games are more lopsided (weak teams in the field)
DRAW = 0.20          # draw probability between equal teams in a group game
HOST = "Brazil"
HOST_BONUS = 0.15
ALIASES = {"USA": "United States", "Korea Republic": "South Korea", "China PR": "China", "England": "United Kingdom"}


def _sig(x):
    return 1.0 / (1.0 + math.exp(-x))


# ── prices ───────────────────────────────────────────────────────────────────
def refresh_prices():
    import requests
    base = "https://api.elections.kalshi.com/trade-api/v2"
    ev = requests.get(base + "/events", params={"series_ticker": "KXWCW", "with_nested_markets": "true"},
                      timeout=25).json()["events"][0]
    teams = {}
    for m in ev["markets"]:
        f = lambda k: float(m.get(k) or 0)
        bid, ask, last = f("yes_bid_dollars"), f("yes_ask_dollars"), f("last_price_dollars")
        mid = (bid + ask) / 2 if ask else last
        teams[m["yes_sub_title"]] = {"bid": bid, "ask": ask, "last": last, "mid": round(mid, 4),
                                     "volume": f("volume_fp"), "open_interest": f("open_interest_fp")}
    snap = {"series": "KXWCW-27", "title": ev["title"], "pulled": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "teams": teams}
    path = os.path.join(RAW, f"kalshi_wwc_{datetime.date.today()}.json")
    with open(path, "w") as fh:
        json.dump(snap, fh, indent=1)
    print(f"saved {len(teams)} team prices -> {path}")
    return path


def load_prices():
    files = sorted(glob.glob(os.path.join(RAW, "kalshi_wwc_*.json")))
    if not files:
        raise SystemExit("no raw/kalshi_wwc_*.json — run with --refresh-prices")
    snap = json.load(open(files[-1]))
    mids = {t: max(v["mid"], 0.004) for t, v in snap["teams"].items()}       # 0.4c floor for dead markets
    tot = sum(mids.values())
    return {t: p / tot for t, p in mids.items()}, os.path.basename(files[-1])    # remove the overround


# ── simulation ───────────────────────────────────────────────────────────────
class Tournament:
    def __init__(self, probs, seed=7):
        self.teams = sorted(probs, key=lambda t: -probs[t])
        self.target = dict(probs)
        self.rng = random.Random(seed)
        # initial ratings: log of title probability, scaled so the spread is plausible
        mx = math.log(max(probs.values()))
        self.r = {t: 0.55 * (math.log(p) - mx) for t, p in probs.items()}
        self.r = {t: max(v, -3.0) for t, v in self.r.items()}

    def _rating(self, t):
        return self.r[t] + (HOST_BONUS if t == HOST else 0.0)

    def _group_game(self, a, b):
        d = (self._rating(a) - self._rating(b)) * GROUP_SCALE
        draw = max(0.10, DRAW - 0.05 * min(abs(d), 2.0))
        pa = (1 - draw) * _sig(d)
        u = self.rng.random()
        return 3 if u < pa else (1 if u < pa + draw else 0)      # points to a (b gets 3/1/0 mirrored)

    def _ko(self, a, b):
        return a if self.rng.random() < _sig(SCALE * (self._rating(a) - self._rating(b))) else b

    def season(self):
        """Returns (reach dict {team: deepest stage index}, champion). stage: 0 groups, 1 R16, 2 QF, 3 SF, 4 F, 5 champ"""
        rng = self.rng
        order = sorted(self.teams, key=lambda t: -self._rating(t))
        pots = [order[i * 8:(i + 1) * 8] for i in range(4)]
        for p in pots:
            rng.shuffle(p)
        groups = [[pots[k][g] for k in range(4)] for g in range(8)]
        stage = {t: 0 for t in self.teams}
        win, runner = {}, {}
        for g, members in enumerate(groups):
            pts = {t: 0 for t in members}
            for i in range(4):
                for j in range(i + 1, 4):
                    a, b = members[i], members[j]
                    x = self._group_game(a, b)
                    if x == 3: pts[a] += 3
                    elif x == 1: pts[a] += 1; pts[b] += 1
                    else: pts[b] += 3
            ranked = sorted(members, key=lambda t: (pts[t], rng.random()), reverse=True)
            win[g], runner[g] = ranked[0], ranked[1]
        L = "ABCDEFGH"
        pairs = [(0, 2), (2, 0), (4, 6), (6, 4), (1, 3), (3, 1), (5, 7), (7, 5)]   # 1X v 2Y (A-C, C-A, E-G, G-E, B-D, D-B, F-H, H-F)
        r16 = [self._ko(win[a], runner[b]) for a, b in pairs]
        for t in [x for a, b in pairs for x in (win[a], runner[b])]:
            stage[t] = 1
        qf = [self._ko(r16[i], r16[i + 1]) for i in range(0, 8, 2)]
        for t in r16: stage[t] = 2
        sf = [self._ko(qf[0], qf[1]), self._ko(qf[2], qf[3])]
        for t in qf: stage[t] = 3
        for t in sf: stage[t] = 4
        champ = self._ko(sf[0], sf[1])
        stage[champ] = 5
        return stage, champ

    def reach(self, sims):
        n = {t: [0] * 6 for t in self.teams}
        for _ in range(sims):
            st, _c = self.season()
            for t, s in st.items():
                for k in range(s + 1):
                    n[t][k] += 1
        return {t: [c / sims for c in v] for t, v in n.items()}

    def calibrate(self, iters=14, sims=3000, damp=0.5):
        for it in range(iters):
            r = self.reach(sims)
            worst = 0.0
            for t in self.teams:
                p = max(r[t][5], 0.5 / sims)
                step = damp * math.log(self.target[t] / p)
                self.r[t] += max(-0.35, min(0.35, step))
                worst = max(worst, abs(p - self.target[t]))
        return worst


def build(seed=7, final_sims=40000):
    probs, src = load_prices()
    tour = Tournament(probs, seed)
    tour.calibrate()
    reach = tour.reach(final_sims)
    out = {}
    for t, v in reach.items():
        p_r16, p_qf, p_sf, p_f, p_c = v[1], v[2], v[3], v[4], v[5]
        ev = (LADDER["champ"] * p_c + LADDER["final"] * (p_f - p_c) + LADDER["semi"] * (p_sf - p_f)
              + LADDER["quarter"] * (p_qf - p_sf) + LADDER["r16"] * (p_r16 - p_qf))
        out[ALIASES.get(t, t)] = {"kalshi_title": round(probs[t], 4), "p_r1": round(p_r16, 4), "p_quarter": round(p_qf, 4),
                                  "p_semi": round(p_sf, 4), "p_final": round(p_f, 4), "p_champ": round(p_c, 4),
                                  "wwc_ev": round(ev, 3), "wwc_name": t}
    doc = {"as_of": str(datetime.date.today()), "source": f"Kalshi KXWCW-27 ({src}); 32-team Monte Carlo ({final_sims} sims) calibrated to title prices",
           "note": "p_r1 = reach Round of 16 (2.5 floor), p_quarter = reach QF (4), p_semi = reach SF (6.5), p_final = reach Final (9), p_champ = win (13). "
                   "Group draw not held yet: random pot draw by rating. Tier mapping is an assumption (lost R16 = 2.5).",
           "teams": dict(sorted(out.items(), key=lambda kv: -kv[1]["wwc_ev"]))}
    with open(OUT, "w") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")
    return doc


if __name__ == "__main__":
    if "--refresh-prices" in sys.argv:
        refresh_prices()
    d = build()
    print(f"wrote {OUT}")
    print(f"{'team':16}{'Kalshi':>8}{'R16':>7}{'QF':>7}{'SF':>7}{'Final':>7}{'Win':>7}{'E[bonus]':>10}")
    for t, v in list(d["teams"].items())[:14]:
        print(f"{t:16}{v['kalshi_title']*100:>7.1f}%{v['p_r1']*100:>6.0f}%{v['p_quarter']*100:>6.0f}%{v['p_semi']*100:>6.0f}%{v['p_final']*100:>6.0f}%{v['p_champ']*100:>6.1f}%{v['wwc_ev']:>9.2f}")
