#!/usr/bin/env python3
"""Simulate the 2027 draft from Korch's slot (13 = last) and compare keeper options.

    python3 draft_guide/draft_sim.py            # writes data/my_draft_2027.json (read by the "My Draft" tab)

Field model (the other 12):
  * keeper round in draft order: each player keeps their best-owned 2027 asset (by board EV) with probability
    1.0 if EV >= 13, 0.5 if >= 11.5, else 0.15 (9 of 13 kept in 2025); otherwise they make a normal pick.
  * snake rounds: category chosen with weight = 2025-draft pace for that round (data/draft_log_2026.json, field picks
    only, +-1 round smoothing) x exp(0.25 x best market value left in the category); player = best market value + noise.
    Market value = board EV, except Musician/Actor/Actress where award EV counts double (the league over-drafts
    Grammy/Oscar names).
Korch policies:
  * dropoff: take the category whose best option is expected to fall the most before his next turn (rolled forward
    with the field model), with a small tie-break toward raw EV.
  * bpa: best EV available.
Outputs are model expectations (sum of board EV), not guarantees; differences of 1-2 pts are inside the noise.
"""
import collections
import json
import math
import os
import random
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_workbook as b  # noqa: E402

AWARD = {"Musician", "Actor", "Actress"}
ME = "Korch"
# 2027 order = reverse of 2026 standings (1st picks last). Only Korch's slot is confirmed; the rest follow scores.json.
DEFAULT_ORDER = ["Shep", "Jens", "Feder", "Todd", "Tim", "Theo", "Molmen", "Mitchell", "Jamzee", "Buckley", "Fryar", "Wu", "Korch"]


def board():
    table = b.compute_table(b.load_assumptions())
    owners, _ = b.match_owners(table)
    out = {}
    for c, rows in table.items():
        out[c] = [dict(name=r["e"]["name"], ev=r["total"], erank=r["erank"], bonus=min(r["bonus"], b.BONUS_CAP),
                       owner=owners[c].get(r["e"]["name"])) for r in rows]
    return out


def order_from_standings():
    try:
        sc = json.load(open(os.path.join(HERE, "..", "docs", "scores.json")))
        bon = json.load(open(os.path.join(HERE, "..", "data", "bonuses.json")))
        tot = {p["name"]: p["total"] for p in sc["players"]}
        # apply bonus overrides that scores.json has not picked up yet (team-sport milestone totals)
        for p in sc["players"]:
            for cat in ("NFL", "NBA", "MLB", "NHL", "NCAAF", "NCAAB", "MLS"):
                v = bon.get(cat, {}).get(p["name"])
                cur = p["categories"][cat.lower()]["bonus_pts"]
                if v is not None and v != cur:
                    tot[p["name"]] += v - cur
        return sorted(tot, key=lambda n: tot[n])           # last place picks first
    except Exception:
        return DEFAULT_ORDER


def pace_table():
    log = json.load(open(os.path.join(HERE, "data", "draft_log_2026.json")))["picks"]
    pace = collections.defaultdict(collections.Counter)
    for e in log:
        if e["player"] == ME or e["round"] == 0:
            continue
        for d in (-1, 0, 1):
            r = e["round"] + d
            if 1 <= r <= 14:
                pace[r][e["category"]] += 2 if d == 0 else 1
    return pace


class Draft:
    def __init__(self, B, order, pace, seed, rollouts=12):
        self.B, self.order, self.pace, self.R = B, order, pace, rollouts
        self.rng = random.Random(seed)
        self.cats = list(B)
        self.own = collections.defaultdict(list)
        for c, rows in B.items():
            for r in rows:
                if r["owner"]:
                    self.own[r["owner"]].append((r["ev"], c, r["name"]))

    def pref(self, rd, c):
        return self.pace[min(max(rd, 1), 14)][c] + 0.3

    @staticmethod
    def mval(c, r):
        return r["erank"] + 2.0 * r["bonus"] if c in AWARD else r["ev"]

    def run(self, keep, policy):
        pool = {c: [dict(r) for r in self.B[c]] for c in self.cats}
        filled = {p: set() for p in self.order}
        picks, kept = [], {}

        def take(p, c, name, rd):
            for i, r in enumerate(pool[c]):
                if r["name"] == name:
                    picks.append((rd, p, c, name, r["ev"]))
                    pool[c].pop(i)
                    break
            filled[p].add(c)

        def field(p, rd):
            opts = [c for c in self.cats if c not in filled[p] and pool[c]]
            w = [self.pref(rd, c) * math.exp(0.25 * max(self.mval(c, r) for r in pool[c][:6])) for c in opts]
            c = self.rng.choices(opts, weights=w)[0]
            best = max(pool[c], key=lambda r: self.mval(c, r) + self.rng.gauss(0, 1.0))
            take(p, c, best["name"], rd)

        def mine(rd, gap):
            opts = [c for c in self.cats if c not in filled[ME] and pool[c]]
            if policy == "bpa":
                c = max(opts, key=lambda c: pool[c][0]["ev"])
                take(ME, c, pool[c][0]["name"], rd)
                return
            est = collections.defaultdict(list)
            for _ in range(self.R if gap else 1):
                rr = random.Random(self.rng.random())
                pc = {c: [dict(r) for r in pool[c]] for c in self.cats}
                for _g in range(gap):
                    c = rr.choices(self.cats, weights=[self.pref(rd + 1, c) * (1 if pc[c] else 0) + 1e-9 for c in self.cats])[0]
                    pc[c].sort(key=lambda r: -(self.mval(c, r) + rr.gauss(0, 1.0)))
                    pc[c].pop(0)
                for c in opts:
                    est[c].append(max((r["ev"] for r in pc[c]), default=0.0))
            c = max(opts, key=lambda c: (pool[c][0]["ev"] - st.mean(est[c])) + 0.25 * pool[c][0]["ev"])
            take(ME, c, pool[c][0]["name"], rd)

        for p in self.order:                                   # keeper round
            if p == ME:
                if keep and any(r["name"] == keep[1] for r in pool[keep[0]]):
                    take(ME, keep[0], keep[1], 0)
                else:
                    mine(0, 0)                                 # back-to-back with R1 #13
                continue
            ev, c, name = max(self.own.get(p, [(0, None, None)]))
            pk = 1.0 if ev >= 13 else 0.5 if ev >= 11.5 else 0.15
            if c and self.rng.random() < pk and any(r["name"] == name for r in pool[c]):
                take(p, c, name, 0)
                kept[p] = (c, name)
            else:
                field(p, 1)
        for rd in range(1, 15):
            seq = self.order if rd % 2 == 1 else self.order[::-1]
            for p in seq:
                if len(filled[p]) >= 15:
                    continue
                if p == ME:
                    slot = self.order.index(ME)
                    first_of_pair = (rd % 2 == 1 and slot == len(self.order) - 1) or (rd % 2 == 0 and slot == 0)
                    mine(rd, 0 if first_of_pair else 2 * (len(self.order) - 1))
                else:
                    field(p, rd)
        return picks, kept


def main():
    B = board()
    order = order_from_standings()
    if order[-1] != ME:                                         # Alex confirmed he picks last
        order = [p for p in order if p != ME] + [ME]
    pace = pace_table()
    owned = sorted(((r["ev"], c, r["name"]) for c, rows in B.items() for r in rows if r["owner"] == ME), reverse=True)
    options = [("No keeper", None)] + [(f"Keep {n}", (c, n)) for ev, c, n in owned[:3]]
    N = 80
    out = {"as_of": b.date.today().isoformat(), "order": order, "n_sims": N, "options": [], "assumptions": __doc__.strip()}
    best = None
    for label, keep in options:
        res = {}
        for pol in ("dropoff", "bpa"):
            tots, rounds, players, keeps = [], collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter), collections.Counter()
            for s in range(N):
                picks, kept = Draft(B, order, pace, seed=1000 + s).run(keep, pol)
                mine = [x for x in picks if x[1] == ME]
                tots.append(sum(x[4] for x in mine))
                for rd, _, c, n, ev in mine:
                    rounds[rd][c] += 1
                    players[c][n] += 1
                for p, v in kept.items():
                    keeps[(p,) + v] += 1
            res[pol] = dict(mean=round(st.mean(tots), 1), sd=round(st.pstdev(tots), 1),
                            rounds={rd: [(c, round(k / N, 2)) for c, k in cnt.most_common(3)] for rd, cnt in sorted(rounds.items())},
                            players={c: [(n, round(k / N, 2)) for n, k in cnt.most_common(3)] for c, cnt in players.items()},
                            others_keep=[(k[0], k[2], round(v / N, 2)) for k, v in keeps.most_common()])
        out["options"].append(dict(label=label, keep=keep, **res))
        print(f"{label:28} dropoff {res['dropoff']['mean']:6.1f} (sd {res['dropoff']['sd']})   bpa {res['bpa']['mean']:6.1f}")
        if best is None or res["dropoff"]["mean"] > best[1]:
            best = (label, res["dropoff"]["mean"])
    out["recommendation"] = best[0]
    json.dump(out, open(os.path.join(HERE, "data", "my_draft_2027.json"), "w"), indent=1, ensure_ascii=False)
    print("recommended:", best[0], "| order:", order)


if __name__ == "__main__":
    main()
