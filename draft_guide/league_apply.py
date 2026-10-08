"""Fit league_sim ratings to market prices and write the simulated ladder + win% distribution into data/<LG>.json.

    python3 draft_guide/league_apply.py NFL NBA NHL

Targets per team (any subset): champion (data/<LG>.json p_champ, Kalshi-based), final (conference champion price),
make-playoffs (Kalshi KX<LG>PLAYOFF mid) read from raw/kalshi_structure_<date>.json. Teams with no price are rated from
their record / existing strength and fall out of the same simulation, so every row gets a coherent ladder.
Writes p_champ/p_final/p_semi/p_quarter/p_r1 (real bracket probabilities), mu/sd of the final regular-season rate and
101 quantiles q of it.
"""
import glob
import json
import os
import sys

import numpy as np

import league_sim as ls

HERE = os.path.dirname(os.path.abspath(__file__))
DATE = "2026-10-08"


def structure_prices():
    """{series: {tail: price}} from the most recent raw/kalshi_structure_*.json."""
    out = {}
    paths = sorted(glob.glob(os.path.join(HERE, "raw", "kalshi_structure_*.json")))
    if not paths:
        return out
    for t, n, rows in json.load(open(paths[-1])):
        d = out.setdefault(t, {})
        for row in rows:
            tk, sub = row[0], row[1]
            bid, ask, last = (row[2], row[3], row[4]) if len(row) > 4 else (None, None, row[2])
            try:
                px = (float(bid) + float(ask)) / 2 if bid not in (None, "", "0.0000") and ask not in (None, "", "0.0000") else float(last or 0)
            except (TypeError, ValueError):
                continue
            d[sub] = px
    return out


def rate_stat(lg, score, gp):
    """regular-season ranking stat per sim: win% (NFL/NBA) or points% (NHL)."""
    return score / (gp * (2.0 if lg == "NHL" else 1.0))


def apply(lg, teams, games, alias, targets_fn, mu_scale=3.0, n_fit=2000, n_final=8000):
    path = os.path.join(HERE, "data", f"{lg}.json")
    d = json.load(open(path))
    ents = {e["name"]: e for e in d["entries"]}
    S = ls.Season(lg, teams, games, alias)
    tg = targets_fn(ents)
    r0 = np.array([((ents.get(t, {}).get("mu") or 0.5) - 0.5) * mu_scale for t in teams])
    r = S.fit(r0, tg, iters=16, n=n_fit)
    res = S.run(r, n=n_final, seed=99)
    lad, stat = res["ladder"], rate_stat(lg, res["score"], res["gp"])
    for t in teams:
        e = ents.get(t)
        if not e:
            continue
        i = S.idx[t]
        e["p_r1"], e["p_quarter"], e["p_semi"], e["p_final"], e["p_champ"] = [round(float(x), 4) for x in lad[i]]
        col = stat[:, i]
        e["mu"], e["sd"] = round(float(col.mean()), 4), round(float(col.std()), 4)
        e["q"] = [round(float(x), 4) for x in np.quantile(col, np.linspace(0, 1, 101))]
        e["notes"] = (e.get("notes") or "").split(" [sim")[0] + f" [sim: playoffs {lad[i,0]:.0%}, rd2 {lad[i,1]:.0%}, conf final {lad[i,2]:.0%}]"
        e["source"] = (e.get("source") or "").split(" | league_sim")[0] + " | league_sim.py: full-schedule + real playoff bracket Monte Carlo, ratings fitted to Kalshi"
    d["note"] = f"{lg} ladder + baseline from league_sim.py (remaining schedule simulated, real playoff structure); ratings fitted to Kalshi champion/conference/playoff prices where posted."
    json.dump(d, open(path, "w"), indent=1, ensure_ascii=False)
    return S, r, lad


def targets_nfl(ents):
    px = structure_prices()
    tg = {}
    for t, e in ents.items():
        tg[t] = dict(champ=e.get("p_champ"), final=e.get("p_final"))
    return tg


if __name__ == "__main__":
    which = sys.argv[1:] or ["NFL"]
    if "NFL" in which:
        games = json.load(open(os.path.join(HERE, "raw", f"nfl_games_{DATE}.json")))
        teams = sum(ls.NFL_DIV.values(), [])
        S, r, lad = apply("NFL", teams, games, {}, targets_nfl)
        print("NFL done; Σ ladder", lad.sum(axis=0).round(2))
