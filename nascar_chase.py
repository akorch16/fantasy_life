"""NASCAR Chase model for projections.py: simulate the remaining Chase races from the live points table.

The 2026 Chase has no eliminations: the champion is whoever has the most points after the final race
(Homestead, Nov 8), and the league bonus pays final standings 1st-5th (13 / 9 / 6.5 / 4 / 2.5). Sampling the
top 5 from Kalshi title odds alone ignored the actual gaps (a driver 5 back and one 40 back look alike once you
only know title prices), so this model races it out:

* Standings + remaining races come from NASCAR's own feeds (cf.nascar.com, reachable from Actions), with
  data/nascar_chase.json as a snapshot fallback (only used while no race has run since it was saved).
* Each remaining race: finishing order and two stage orders are drawn Plackett-Luce style (skill + Gumbel noise)
  over a 38-car field. Points: win 40, 2nd 35, then -1 per place (min 1); stages pay 10..1 to the top 10.
  Superspeedways (Talladega/Daytona) are mostly luck, so skill is damped there.
* Contender skills are fitted so the simulated title odds match Kalshi's champion prices (common random numbers,
  damped log-ratio updates); everyone else gets a skill from their season top-5 rate.

Refresh the snapshot locally is not possible (cf.nascar.com is blocked outside Actions); the daily run fetches live.
"""
import datetime
import json
import math
import os
import random

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT = os.path.join(HERE, "data", "nascar_chase.json")
POINTS_URL = "https://cf.nascar.com/cacher/{year}/1/racinginsights-points-feed.json"
RACES_URL = "https://cf.nascar.com/cacher/{year}/race_list_basic.json"
FINISH_PTS = (13.0, 9.0, 6.5, 4.0, 2.5)
FIELD = 38
SUPERSPEEDWAYS = ("talladega", "daytona", "atlanta")
SS_DAMP = 0.3            # share of skill that still matters at a superspeedway
CHASE_SIZE = 16


def race_points(pos):
    """Finishing points by 1-based position."""
    return 40 if pos == 1 else max(1, 36 - pos)


def stage_points(pos):
    return max(0, 11 - pos)


def fetch_live(year=2026, timeout=30):
    """{"standings": [{driver, points, top_5, starts, wins}], "remaining": [{name, track, date}], "as_of"} or None."""
    try:
        H = {"User-Agent": "Mozilla/5.0"}
        pts = requests.get(POINTS_URL.format(year=year), headers=H, timeout=timeout).json()
        races = requests.get(RACES_URL.format(year=year), headers=H, timeout=timeout).json().get("series_1") or []
    except Exception as e:
        print(f"  ℹ NASCAR feed unavailable ({e})")
        return None
    standings = [{"driver": d["driver_name"], "points": d["points"], "top_5": d.get("top_5", 0),
                  "starts": d.get("starts", 0), "wins": d.get("wins", 0)} for d in pts if d.get("driver_name")]
    remaining = [{"name": r.get("race_name", "").strip(), "track": r.get("track_name", ""),
                  "date": (r.get("race_date") or r.get("date_scheduled") or "")[:10]}
                 for r in races if r.get("playoff_round") and not r.get("winner_driver_id")]
    return {"as_of": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "standings": standings, "remaining": remaining}


def load_snapshot():
    try:
        with open(SNAPSHOT) as f:
            return json.load(f)
    except Exception:
        return None


def snapshot_is_current(snap, today=None):
    """True while no race in the snapshot's remaining list has already been run (dated before today)."""
    today = today or datetime.datetime.now(datetime.timezone.utc).date()
    return all(datetime.date.fromisoformat(r["date"]) >= today for r in snap.get("remaining", []))


class ChaseModel:
    def __init__(self, data, targets=None, n_fit=3000, n_pool=20000, seed=26):
        st = sorted(data["standings"], key=lambda d: -d["points"])
        self.chase = st[:CHASE_SIZE]
        self.drivers = [d["driver"] for d in self.chase]
        self.base = [float(d["points"]) for d in self.chase]
        self.remaining = data["remaining"]
        self.damp = [SS_DAMP if any(s in r["track"].lower() for s in SUPERSPEEDWAYS) else 1.0 for r in self.remaining]
        # skill prior from season top-5 rate (log scale, roughly a 1.4x-per-unit strength ratio)
        self.skill = [math.log((d.get("top_5", 0) + 1.0) / (max(d.get("starts", 1), 1) + 2.0)) * 1.3 for d in self.chase]
        self.other_skill = math.log(1.5 / 35.0) * 1.3          # the 22 non-Chase cars
        self.calibration = None
        rng = random.Random(seed)
        noise = self._draw_noise(rng, n_fit)
        if targets and self.remaining:
            self._fit(targets, noise)
        self.pool = self._simulate(self._draw_noise(rng, n_pool)) if self.remaining else [self._final_order(self.base)]

    # ── simulation ──────────────────────────────────────────────────────────
    def _draw_noise(self, rng, n):
        g = lambda: -math.log(-math.log(rng.random() or 1e-12))
        return [[[[g() for _ in range(FIELD)] for _ in range(3)] for _ in self.remaining] for _ in range(n)]

    def _simulate(self, noise, skill=None):
        skill = skill or self.skill
        out = []
        n_c = len(self.drivers)
        for sim in noise:
            pts = list(self.base)
            for r, sessions in enumerate(sim):
                d = self.damp[r]
                for s, z in enumerate(sessions):            # s = 0 finish, 1-2 stages
                    score = [d * (skill[i] if i < n_c else self.other_skill) + z[i] for i in range(FIELD)]
                    order = sorted(range(FIELD), key=lambda i: -score[i])
                    for pos, i in enumerate(order, 1):
                        if i < n_c:
                            pts[i] += race_points(pos) if s == 0 else stage_points(pos)
            out.append(self._final_order(pts))
        return out

    def _final_order(self, pts):
        return [self.drivers[i] for i in sorted(range(len(pts)), key=lambda i: (-pts[i], random.random()))[:5]]

    def _fit(self, targets, noise, iters=14):
        names = [d for d in self.drivers if targets.get(d, 0) > 0]
        if not names:
            return
        tot = sum(targets[d] for d in names)
        tgt = {d: targets[d] / tot for d in names}
        skill = list(self.skill)
        for _ in range(iters):
            wins = {d: 0 for d in self.drivers}
            for top5 in self._simulate(noise, skill):
                wins[top5[0]] += 1
            n = len(noise)
            for d in names:
                i = self.drivers.index(d)
                sim = (wins[d] + 0.5) / (n + 1)
                skill[i] += max(-0.6, min(0.6, 0.6 * math.log(tgt[d] / sim)))
        self.skill = skill
        wins = {d: 0 for d in self.drivers}
        for top5 in self._simulate(noise, skill):
            wins[top5[0]] += 1
        self.calibration = {d: (round(tgt[d], 3), round(wins[d] / len(noise), 3)) for d in names}

    # ── interface used by projections.simulate() ────────────────────────────
    def sample_owner_bonuses(self, picks):
        """{owner: bonus} for one sampled Chase finish; picks = {owner: driver name}."""
        top5 = random.choice(self.pool)
        by_driver = {d: FINISH_PTS[k] for k, d in enumerate(top5)}
        return {owner: by_driver[drv] for owner, drv in picks.items() if drv in by_driver}

    def finish_probs(self, driver):
        """P(1st..5th) for a driver in the pool (for logging / checks)."""
        n = len(self.pool)
        return [round(sum(1 for t in self.pool if t[k] == driver) / n, 3) for k in range(5)]


def build_model(targets=None, today=None, **kw):
    """ChaseModel from the live feed (snapshot fallback while still current), or None."""
    data = fetch_live()
    if data and data["standings"]:
        try:
            with open(SNAPSHOT, "w") as f:
                json.dump(data, f, indent=1)
        except Exception:
            pass
    else:
        data = load_snapshot()
        if not data or not snapshot_is_current(data, today):
            return None
    return ChaseModel(data, targets, **kw)
