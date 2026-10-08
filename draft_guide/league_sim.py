"""Season + playoff Monte Carlo for NFL / NBA / NHL (replaces the 2x/4x/8x/16x ladder rule and hand-set win%).

Inputs per league (raw/<lg>_games_<date>.json from an ESPN runner pull): every regular-season game with date, away,
home, scores, status. Played games are banked; remaining games are simulated with a team-rating model
    P(home wins) = logistic(r_home - r_away + HFA).
Ratings are fitted (iterative proportional adjustment, common random numbers) so simulated championship / final
probabilities match Kalshi where available and current records elsewhere. Playoff structure is the real one:
  NFL  7 seeds per conference (4 division winners + 3 wild cards, #1 bye, reseeded rounds)
  NBA  top 6 direct + play-in for 7-10, 16-team bracket, best-of-7
  NHL  3 per division + 2 wild cards per conference, divisional bracket, best-of-7
Outputs per team: P(make playoffs / reach round 2 / conference final / final / champion) = the league bonus ladder
(13 / 9 / 6.5 / 4 / 2.5 by round eliminated), plus the simulated final regular-season win% distribution.
"""
import json
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
HFA = {"NFL": 0.20, "NBA": 0.30, "NHL": 0.15}          # logit points
SERIES_HFA = 0.0

NFL_DIV = {
    "AFC East": ["Buffalo Bills", "Miami Dolphins", "New England Patriots", "New York Jets"],
    "AFC North": ["Baltimore Ravens", "Cincinnati Bengals", "Cleveland Browns", "Pittsburgh Steelers"],
    "AFC South": ["Houston Texans", "Indianapolis Colts", "Jacksonville Jaguars", "Tennessee Titans"],
    "AFC West": ["Denver Broncos", "Kansas City Chiefs", "Las Vegas Raiders", "Los Angeles Chargers"],
    "NFC East": ["Dallas Cowboys", "New York Giants", "Philadelphia Eagles", "Washington Commanders"],
    "NFC North": ["Chicago Bears", "Detroit Lions", "Green Bay Packers", "Minnesota Vikings"],
    "NFC South": ["Atlanta Falcons", "Carolina Panthers", "New Orleans Saints", "Tampa Bay Buccaneers"],
    "NFC West": ["Arizona Cardinals", "Los Angeles Rams", "San Francisco 49ers", "Seattle Seahawks"],
}
NBA_CONF = {
    "East": ["Atlanta Hawks", "Boston Celtics", "Brooklyn Nets", "Charlotte Hornets", "Chicago Bulls", "Cleveland Cavaliers",
             "Detroit Pistons", "Indiana Pacers", "Miami Heat", "Milwaukee Bucks", "New York Knicks", "Orlando Magic",
             "Philadelphia 76ers", "Toronto Raptors", "Washington Wizards"],
    "West": ["Dallas Mavericks", "Denver Nuggets", "Golden State Warriors", "Houston Rockets", "Los Angeles Clippers",
             "Los Angeles Lakers", "Memphis Grizzlies", "Minnesota Timberwolves", "New Orleans Pelicans",
             "Oklahoma City Thunder", "Phoenix Suns", "Portland Trail Blazers", "Sacramento Kings", "San Antonio Spurs",
             "Utah Jazz"],
}
NHL_DIV = {
    "Atlantic": ["Boston Bruins", "Buffalo Sabres", "Detroit Red Wings", "Florida Panthers", "Montreal Canadiens",
                 "Ottawa Senators", "Tampa Bay Lightning", "Toronto Maple Leafs"],
    "Metropolitan": ["Carolina Hurricanes", "Columbus Blue Jackets", "New Jersey Devils", "New York Islanders",
                     "New York Rangers", "Philadelphia Flyers", "Pittsburgh Penguins", "Washington Capitals"],
    "Central": ["Chicago Blackhawks", "Colorado Avalanche", "Dallas Stars", "Minnesota Wild", "Nashville Predators",
                "St. Louis Blues", "Utah Mammoth", "Winnipeg Jets"],
    "Pacific": ["Anaheim Ducks", "Calgary Flames", "Edmonton Oilers", "Los Angeles Kings", "San Jose Sharks",
                "Seattle Kraken", "Vancouver Canucks", "Vegas Golden Knights"],
}
NHL_CONF = {"East": ["Atlantic", "Metropolitan"], "West": ["Central", "Pacific"]}


def logistic(x):
    return 1.0 / (1.0 + np.exp(-x))


def series_win_prob(p, best_of=7):
    """P(win a best-of-N series) for per-game win prob p (scalar or array)."""
    need = best_of // 2 + 1
    p = np.asarray(p, dtype=float)
    tot = np.zeros_like(p)
    for k in range(need):                      # opponent wins k games
        tot += math.comb(need - 1 + k, k) * p ** need * (1 - p) ** k
    return tot


class Season:
    def __init__(self, lg, teams, games, alias=None):
        self.lg, self.teams = lg, teams
        self.idx = {t: i for i, t in enumerate(teams)}
        alias = alias or {}
        self.base = np.zeros((len(teams), 2))              # wins, games played (NHL: points, gp)
        self.rem = []                                      # (home, away) index pairs for unplayed games
        for d, away, home, sa, sh, status in games:
            away, home = alias.get(away, away), alias.get(home, home)
            if away not in self.idx or home not in self.idx:
                continue
            a, h = self.idx[away], self.idx[home]
            if status == "STATUS_FINAL" and sa is not None and sh is not None:
                sa, sh = float(sa), float(sh)
                w = h if sh > sa else a
                self.base[w, 0] += 2 if lg == "NHL" else 1
                self.base[[a, h], 1] += 1
            else:
                self.rem.append((h, a))
        self.rem = np.array(self.rem, dtype=int).reshape(-1, 2)

    # ── regular season ───────────────────────────────────────────────────────────
    def simulate_regular(self, r, n, rng):
        """-> score (n, T) final wins (NFL/NBA) or points (NHL), plus games per team."""
        T = len(self.teams)
        score = np.tile(self.base[:, 0], (n, 1))
        gp = self.base[:, 1] + np.bincount(self.rem.ravel(), minlength=T)
        if len(self.rem):
            h, a = self.rem[:, 0], self.rem[:, 1]
            p = logistic(r[h] - r[a] + HFA[self.lg])                       # (G,)
            u = rng.random((n, len(p)))
            hw = u < p[None, :]
            win_pts = 2.0 if self.lg == "NHL" else 1.0
            for g in range(len(p)):
                score[:, h[g]] += hw[:, g] * win_pts
                score[:, a[g]] += (~hw[:, g]) * win_pts
            if self.lg == "NHL":                                              # ~23% of losses are OT/SO: loser gets 1
                ot = rng.random((n, len(p))) < 0.23
                for g in range(len(p)):
                    score[:, a[g]] += hw[:, g] * ot[:, g]
                    score[:, h[g]] += (~hw[:, g]) * ot[:, g]
        return score, gp

    # ── playoffs ──────────────────────────────────────────────────────────────────
    def game_p(self, r, i, j):
        return float(logistic(r[i] - r[j]))

    def series_p(self, r, i, j):
        return float(series_win_prob(logistic(r[i] - r[j] + SERIES_HFA)))

    def _nfl_playoffs(self, r, s, rng, out):
        reach = {}                                                    # team -> deepest round index (0=playoffs..4=champ)
        champs = []
        for conf in ("AFC", "NFC"):
            divs = [v for k, v in NFL_DIV.items() if k.startswith(conf)]
            winners = [max((self.idx[t] for t in d), key=lambda i: s[i]) for d in divs]
            win_set = set(winners)
            rest = sorted((self.idx[t] for d in divs for t in d if self.idx[t] not in win_set), key=lambda i: -s[i])[:3]
            seeds = sorted(winners, key=lambda i: -s[i]) + rest
            for i in seeds:
                out[i, 0] += 1                                        # made playoffs
            out[seeds[0], 1] += 1                                     # bye -> reached divisional round
            wc = [(seeds[1], seeds[6]), (seeds[2], seeds[5]), (seeds[3], seeds[4])]
            surv = []
            for hi, lo in wc:
                w = hi if rng.random() < self.game_p(r, hi, lo) else lo
                surv.append(w)
            for w in surv:
                out[w, 1] += 1
            field = [seeds[0]] + surv
            field.sort(key=lambda i: seeds.index(i))
            pairs = [(field[0], field[3]), (field[1], field[2])]
            nxt = []
            for hi, lo in pairs:
                w = hi if rng.random() < self.game_p(r, hi, lo) else lo
                nxt.append(w)
                out[w, 2] += 1                                        # reached conference final
            a, b = sorted(nxt, key=lambda i: seeds.index(i))
            w = a if rng.random() < self.game_p(r, a, b) else b
            out[w, 3] += 1                                            # reached the Super Bowl
            champs.append(w)
        a, b = champs
        w = a if rng.random() < self.game_p(r, a, b) else b
        out[w, 4] += 1

    def _nba_playoffs(self, r, s, rng, out):
        finalists = []
        for conf, names in NBA_CONF.items():
            order = sorted((self.idx[t] for t in names), key=lambda i: -s[i])
            seeds = order[:6]
            s7, s8, s9, s10 = order[6:10]
            w78 = s7 if rng.random() < self.game_p(r, s7, s8) else s8
            l78 = s8 if w78 == s7 else s7
            w910 = s9 if rng.random() < self.game_p(r, s9, s10) else s10
            w8 = l78 if rng.random() < self.game_p(r, l78, w910) else w910
            seeds += [w78, w8]
            for i in seeds:
                out[i, 0] += 1
            def play(hi, lo):
                return hi if rng.random() < self.series_p(r, hi, lo) else lo
            r1 = [play(seeds[0], seeds[7]), play(seeds[3], seeds[4]), play(seeds[1], seeds[6]), play(seeds[2], seeds[5])]
            for i in r1:
                out[i, 1] += 1
            r2 = [play(r1[0], r1[1]), play(r1[2], r1[3])]
            for i in r2:
                out[i, 2] += 1
            f = play(r2[0], r2[1])
            out[f, 3] += 1
            finalists.append(f)
        a, b = finalists
        w = a if rng.random() < self.series_p(r, a, b) else b
        out[w, 4] += 1

    def _nhl_playoffs(self, r, s, rng, out):
        finalists = []
        for conf, divs in NHL_CONF.items():
            dtop, rest, dwin = {}, [], []
            for d in divs:
                order = sorted((self.idx[t] for t in NHL_DIV[d]), key=lambda i: -s[i])
                dtop[d] = order[:3]
                rest += order[3:]
                dwin.append(order[0])
            wcs = sorted(rest, key=lambda i: -s[i])[:2]
            hi_d = max(divs, key=lambda d: s[dtop[d][0]])
            lo_d = [d for d in divs if d != hi_d][0]
            for i in [x for d in divs for x in dtop[d]] + wcs:
                out[i, 0] += 1
            def play(hi, lo):
                return hi if rng.random() < self.series_p(r, hi, lo) else lo
            # best division winner vs WC2 (lower), other division winner vs WC1; 2v3 inside each division
            br = {hi_d: [(dtop[hi_d][0], wcs[1]), (dtop[hi_d][1], dtop[hi_d][2])],
                  lo_d: [(dtop[lo_d][0], wcs[0]), (dtop[lo_d][1], dtop[lo_d][2])]}
            d_win = []
            for d in divs:
                w = [play(a, b) for a, b in br[d]]
                for i in w:
                    out[i, 1] += 1
                f = play(w[0], w[1])
                out[f, 2] += 1
                d_win.append(f)
            c = play(d_win[0], d_win[1])
            out[c, 3] += 1
            finalists.append(c)
        a, b = finalists
        w = a if rng.random() < self.series_p(r, a, b) else b
        out[w, 4] += 1

    def run(self, r, n=3000, seed=11):
        """-> dict(ladder (T,5) P(playoffs, r2, conf final, final, champion), score (n,T), gp)"""
        rng = np.random.default_rng(seed)
        score, gp = self.simulate_regular(r, n, rng)
        # seed on rate (schedules differ by a game or two in the ESPN pull) with a sub-win random tiebreak
        denom = gp * (2.0 if self.lg == "NHL" else 1.0)
        seedstat = score / denom + rng.random(score.shape) * (0.9 / denom)
        out = np.zeros((len(self.teams), 5))
        play = {"NFL": self._nfl_playoffs, "NBA": self._nba_playoffs, "NHL": self._nhl_playoffs}[self.lg]
        for k in range(n):
            play(r, seedstat[k], rng, out)
        return dict(ladder=out / n, score=score, gp=gp, wins=score.mean(axis=0))

    def fit(self, r0, targets, iters=40, n=1500, seed=5, verbose=False):
        """targets: {team: dict(champ=, final=, playoffs=, wins=)} (any subset). Damped log-ratio updates on common
        random numbers (same seed every pass), so the loop is deterministic and the noise does not chase itself."""
        r = r0.copy()
        w = {"champ": 0.35, "final": 0.30, "playoffs": 0.35}
        sens = {"champ": 4.0, "final": 3.0, "playoffs": 1.5}        # d ln(prob) / d rating, roughly
        eps = {"champ": 2e-3, "final": 4e-3, "playoffs": 2e-2}
        col = {"champ": 4, "final": 3, "playoffs": 0}
        for it in range(iters):
            full = self.run(r, n=n, seed=seed)
            res, mean_w = full["ladder"], full["wins"]
            step = 1.0 if it < 10 else 0.6 if it < 25 else 0.35
            err = []
            for t, tg in targets.items():
                i = self.idx[t]
                num = den = 0.0
                for k in ("champ", "final", "playoffs"):
                    if tg.get(k) is None:
                        continue
                    num += w[k] * (math.log(tg[k] + eps[k]) - math.log(res[i, col[k]] + eps[k])) / sens[k]
                    den += w[k]
                    if k == "champ":
                        err.append(abs(res[i, 4] - tg[k]))
                if tg.get("wins") is not None:
                    scale = 8.0 if self.lg == "NFL" else 20.0 if self.lg == "NBA" else 40.0
                    num += 0.3 * (tg["wins"] - mean_w[i]) / scale
                    den += 0.3
                if den:
                    r[i] += step * float(np.clip(num / den, -0.3, 0.3))
            r -= r.mean()
            if verbose:
                print(f"  iter {it:2d} mean|champ err| {np.mean(err):.4f}")
        return r


def load_games(lg, date):
    return json.load(open(os.path.join(HERE, "raw", f"{lg.lower()}_games_{date}.json")))
