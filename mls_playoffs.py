"""MLS playoff-bonus model for the projections simulation.

Simulates the rest of the regular season from the full 30-team table and the
remaining fixtures (data/mls_schedule.json), seeds the top 9 of each conference,
and plays the bracket, including the 8-v-9 play-in. Each owner's team earns the
bonus for the round it was eliminated in:

    missed playoffs / lost the play-in  0
    lost Round One                      2.5
    lost conference semifinal           4.0
    lost conference final               6.5
    lost MLS Cup                        9.0
    champion                            13.0

Team strength is points-per-game shrunk toward the league mean. If Kalshi MLS Cup
prices are supplied, ratings are tilted (damped, clipped) so the model's title
odds for the owners' teams match the market.

Refresh the schedule snapshot (needs ESPN reachable, e.g. run locally):
    python3 mls_playoffs.py --refresh-schedule
"""
import datetime
import json
import math
import os
import random
import re
import unicodedata

_HERE = os.path.dirname(os.path.abspath(__file__))
SCHEDULE_PATH = os.path.join(_HERE, "data", "mls_schedule.json")
_UTC = datetime.timezone.utc

LEAGUE_PPG = 1.35      # shrinkage target
SHRINK = 0.6           # weight on the team's own points-per-game
HFA = 0.2              # home advantage, in rating (points-per-game) units
SCALE = 2.0            # rating difference -> win log-odds
DRAW = 0.26            # base draw probability in the regular season
GAMES = 34

BONUS = {"r1": 2.5, "semi": 4.0, "conf_final": 6.5, "final": 9.0, "champ": 13.0}

# slug -> regex on the accent-stripped lowercase team name
TEAM_PATTERNS = [
    ("atlanta", r"atlanta"), ("austin", r"austin"), ("charlotte", r"charlotte"),
    ("chicago", r"chicago"), ("cincinnati", r"cincinnati"), ("colorado", r"colorado"),
    ("columbus", r"columbus"), ("dc-united", r"d\.?c\.? united"), ("dallas", r"dallas"),
    ("houston", r"houston"), ("inter-miami", r"miami"), ("la-galaxy", r"galaxy"),
    ("lafc", r"lafc|los angeles fc"), ("minnesota", r"minnesota"), ("montreal", r"montr"),
    ("nashville", r"nashville"), ("new-england", r"new england"),
    ("nyc-fc", r"new york city|nycfc"), ("red-bulls", r"red bull"),
    ("orlando", r"orlando"), ("philadelphia", r"philadelphia"), ("portland", r"portland"),
    ("salt-lake", r"salt lake"), ("san-diego", r"san diego"), ("san-jose", r"san jose"),
    ("seattle", r"seattle"), ("sporting-kc", r"sporting|kansas city"),
    ("st-louis", r"st\.? louis"), ("toronto", r"toronto"), ("vancouver", r"vancouver"),
]
_COMPILED = [(slug, re.compile(rx)) for slug, rx in TEAM_PATTERNS]


def team_key(name):
    """Canonical slug for a team name from any source, or None."""
    if not name:
        return None
    s = "".join(c for c in unicodedata.normalize("NFKD", name.lower())
                if not unicodedata.combining(c))
    for slug, rx in _COMPILED:
        if rx.search(s):
            return slug
    return None


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x))


def _parse_ts(ts):
    return datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%MZ").replace(tzinfo=_UTC)


def load_schedule(path=SCHEDULE_PATH):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


class MLSPlayoffModel:
    def __init__(self, points, since, schedule, targets=None, seed=None):
        """points: {slug: pts} for all 30 teams; since: UTC time the table reflects."""
        self.conf = schedule["conference"]
        self.rng = random.Random(seed)
        first = _parse_ts(schedule["from"])
        since = max(since, first)
        remaining = {k: [] for k in self.conf}
        self.fixtures = []
        for fx in schedule["fixtures"]:
            if _parse_ts(fx["t"]) > since and fx["h"] in remaining and fx["a"] in remaining:
                self.fixtures.append((fx["h"], fx["a"]))
                remaining[fx["h"]].append(fx["a"])
                remaining[fx["a"]].append(fx["h"])
        self.pts = {k: float(points[k]) for k in self.conf}
        self.gp = {k: max(1, GAMES - len(remaining[k])) for k in self.conf}
        self.rating = {k: SHRINK * (self.pts[k] / self.gp[k]) + (1 - SHRINK) * LEAGUE_PPG
                       for k in self.conf}
        self.by_conf = {c: [k for k, v in self.conf.items() if v == c] for c in ("East", "West")}
        self.calibration = None
        if targets:
            self._calibrate(targets)
        self._cache_match_probs()

    # ── match model ──────────────────────────────────────────────────────────
    def _cache_match_probs(self):
        self._probs = [self._wdl(h, a) for h, a in self.fixtures]

    def _wdl(self, h, a):
        d = self.rating[h] - self.rating[a] + HFA
        draw = max(0.12, DRAW - 0.06 * min(abs(d), 1.0))
        win = _sigmoid(SCALE * d)
        return (1 - draw) * win, draw

    def _ko(self, a, b):
        """Single knockout game: winner."""
        p = _sigmoid(SCALE * (self.rating[a] - self.rating[b]))
        return a if self.rng.random() < p else b

    def _bo3(self, a, b):
        p = _sigmoid(SCALE * (self.rating[a] - self.rating[b]))
        return a if self.rng.random() < p * p * (3 - 2 * p) else b

    # ── one full season + playoffs ───────────────────────────────────────────
    def run_once(self):
        """Returns ({slug: bonus}, champion_slug)."""
        rng = self.rng
        pts = dict(self.pts)
        for (h, a), (ph, pd) in zip(self.fixtures, self._probs):
            u = rng.random()
            if u < ph:
                pts[h] += 3
            elif u < ph + pd:
                pts[h] += 1
                pts[a] += 1
            else:
                pts[a] += 3

        bonus, champs = {}, {}
        for conf, teams in self.by_conf.items():
            order = sorted(teams, key=lambda k: (pts[k], rng.random()), reverse=True)[:9]
            # play-in: 8th hosts 9th; the loser earns nothing
            p8 = _sigmoid(SCALE * (self.rating[order[7]] - self.rating[order[8]] + HFA))
            s8 = order[7] if rng.random() < p8 else order[8]
            seeds = order[:7] + [s8]
            for k in seeds:
                bonus[k] = BONUS["r1"]          # made the playoffs
            w18 = self._bo3(seeds[0], seeds[7])
            w45 = self._bo3(seeds[3], seeds[4])
            w27 = self._bo3(seeds[1], seeds[6])
            w36 = self._bo3(seeds[2], seeds[5])
            for k in (w18, w45, w27, w36):
                bonus[k] = BONUS["semi"]        # won Round One
            f1, f2 = self._ko(w18, w45), self._ko(w27, w36)
            for k in (f1, f2):
                bonus[k] = BONUS["conf_final"]  # won the conference semifinal
            champs[conf] = self._ko(f1, f2)
            bonus[champs[conf]] = BONUS["final"]
        champion = self._ko(champs["East"], champs["West"])
        bonus[champion] = BONUS["champ"]
        return bonus, champion

    # ── Kalshi calibration ───────────────────────────────────────────────────
    def _calibrate(self, targets, iters=3, sims=2500, damp=0.35, clip=0.4):
        """Tilt ratings so title odds for the priced teams match Kalshi. Prices under
        2% are ignored: Kalshi quotes long shots at a ~0.5% floor, which carries no
        information and would drag weak teams' playoff chances upward."""
        targets = {k: q for k, q in targets.items() if q >= 0.02}
        if not targets:
            return
        base = dict(self.rating)
        for _ in range(iters):
            self._cache_match_probs()
            wins = {k: 0 for k in targets}
            for _ in range(sims):
                _, champ = self.run_once()
                if champ in wins:
                    wins[champ] += 1
            for k, q in targets.items():
                p = (wins[k] + 0.5) / (sims + 1)
                step = damp * math.log((q + 0.003) / (p + 0.003))
                self.rating[k] = min(base[k] + clip, max(base[k] - clip, self.rating[k] + step))
        self.calibration = {k: round(self.rating[k] - base[k], 3) for k in targets}

    # ── convenience for projections.simulate ─────────────────────────────────
    def sample_owner_bonuses(self, owner_team_keys):
        """{owner: bonus} for one simulated season; owners who miss out are absent."""
        bonus, _ = self.run_once()
        return {o: bonus[k] for o, k in owner_team_keys.items() if k in bonus}


def build_model(points_by_name, since, targets_by_key=None, schedule=None, seed=None):
    """Returns an MLSPlayoffModel, or None if inputs aren't usable (caller falls back)."""
    schedule = schedule or load_schedule()
    if not schedule or not points_by_name:
        return None
    points = {}
    for name, pts in points_by_name.items():
        k = team_key(name)
        if k and pts is not None:
            points[k] = pts
    if len(points) < 28 or any(k not in points for k in schedule["conference"]):
        return None
    if since is None:
        return None
    return MLSPlayoffModel(points, since, schedule, targets_by_key, seed)


# ── schedule snapshot (run locally; ESPN is blocked from Actions) ────────────────
def refresh_schedule(days=24, start=None):
    from scrapers import fetch_json
    base = "https://site.api.espn.com/apis"
    st = fetch_json(f"{base}/v2/sports/soccer/usa.1/standings", timeout=20)
    conference = {}
    for child in st["children"]:
        conf = "East" if "east" in child["name"].lower() else "West"
        for e in child["standings"]["entries"]:
            k = team_key(e["team"]["displayName"])
            if k:
                conference[k] = conf
    assert len(conference) == 30, f"expected 30 teams, got {len(conference)}"
    start = start or datetime.datetime.now(_UTC).date()
    fixtures, seen = [], set()
    for i in range(days):
        d = start + datetime.timedelta(days=i)
        sb = fetch_json(f"{base}/site/v2/sports/soccer/usa.1/scoreboard?dates={d:%Y%m%d}", timeout=20)
        for ev in sb.get("events", []):
            if ev.get("season", {}).get("slug") != "regular-season" or ev["id"] in seen:
                continue
            seen.add(ev["id"])
            comp = ev["competitions"][0]["competitors"]
            home = next(c for c in comp if c["homeAway"] == "home")["team"]["displayName"]
            away = next(c for c in comp if c["homeAway"] == "away")["team"]["displayName"]
            hk, ak = team_key(home), team_key(away)
            if hk and ak:
                fixtures.append({"t": ev["date"], "h": hk, "a": ak})
    fixtures.sort(key=lambda f: f["t"])
    out = {
        "_note": "Remaining 2026 MLS regular-season fixtures, snapshotted from ESPN. "
                 "Regenerate with `python3 mls_playoffs.py --refresh-schedule`.",
        "from": f"{start.isoformat()}T00:00Z",
        "games_per_team": GAMES,
        "conference": dict(sorted(conference.items())),
        "fixtures": fixtures,
    }
    with open(SCHEDULE_PATH, "w") as f:
        json.dump(out, f, indent=1)
        f.write("\n")
    per = {}
    for fx in fixtures:
        for k in (fx["h"], fx["a"]):
            per[k] = per.get(k, 0) + 1
    print(f"wrote {len(fixtures)} fixtures from {start} to {SCHEDULE_PATH}")
    print("fixtures per team:", dict(sorted(per.items())))


if __name__ == "__main__":
    import sys
    if "--refresh-schedule" in sys.argv:
        sys.path.insert(0, _HERE)
        refresh_schedule()
