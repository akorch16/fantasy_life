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
        if tg.get(t, {}).get("champ") is not None:
            e["confidence"] = "A"                      # priced on Kalshi (title, conference and playoff markets)
        e["p_r1"], e["p_quarter"], e["p_semi"], e["p_final"], e["p_champ"] = [round(float(x), 4) for x in lad[i]]
        col = stat[:, i]
        e["mu"], e["sd"] = round(float(col.mean()), 4), round(float(col.std()), 4)
        e["q"] = [round(float(x), 4) for x in np.quantile(col, np.linspace(0, 1, 101))]
        e["notes"] = (e.get("notes") or "").split(" [sim")[0] + f" [sim: playoffs {lad[i,0]:.0%}, rd2 {lad[i,1]:.0%}, conf final {lad[i,2]:.0%}]"
        e["source"] = (e.get("source") or "").split(" | league_sim")[0] + " | league_sim.py: full-schedule + real playoff bracket Monte Carlo, ratings fitted to Kalshi"
    d["note"] = f"{lg} ladder + baseline from league_sim.py (remaining schedule simulated, real playoff structure); ratings fitted to Kalshi champion/conference/playoff prices where posted."
    json.dump(d, open(path, "w"), indent=1, ensure_ascii=False)
    return S, r, lad


def _mid(row):
    try:
        b, a, l = float(row[2] or 0), float(row[3] or 0), float(row[4] or 0)
    except (TypeError, ValueError):
        return 0.0
    return (b + a) / 2 if b > 0 and a > 0 else l


def _team(short, teams):
    """Kalshi short name ('New York J', 'Los Angeles C', 'Tampa Bay') -> full team name."""
    sp = {"new york j": "New York Jets", "new york g": "New York Giants", "los angeles c": None, "los angeles r": "Los Angeles Rams",
          "los angeles l": "Los Angeles Lakers", "new york": "New York Knicks"}
    k = short.lower().strip()
    if k == "los angeles c":
        return "Los Angeles Clippers" if "Los Angeles Clippers" in teams else "Los Angeles Chargers"
    if k in sp and sp[k] in teams:
        return sp[k]
    for t in teams:
        if t.lower() == k or t.lower().startswith(k + " "):
            return t
    return None


def kalshi_targets(teams, series, scale_to):
    """{team: price} from a structure series, renormalised so the field sums to scale_to (strips vig / stale rows)."""
    paths = sorted(glob.glob(os.path.join(HERE, "raw", "kalshi_structure_*.json")))
    data = {t: rows for t, n, rows in json.load(open(paths[-1]))}
    px = {}
    for row in data.get(series, []):
        t = _team(row[1], teams)
        if t:
            px[t] = _mid(row)
    tot = sum(px.values())
    return {t: v * scale_to / tot for t, v in px.items()} if tot else {}


SERIES = {
    "NFL": dict(champ="KXSB", final=("KXNFLAFCCHAMP", "KXNFLNFCCHAMP"), playoffs="KXNFLPLAYOFF", n_playoffs=14),
    "NBA": dict(champ="KXNBA", final=("KXNBAEAST", "KXNBAWEST"), playoffs="KXNBAPLAYOFF", n_playoffs=16),
    "NHL": dict(champ="KXNHL", final=("KXNHLEAST", "KXNHLWEST"), playoffs="KXNHLPLAYOFF", n_playoffs=16),
}


def make_targets(lg, teams):
    cfg = SERIES[lg]
    champ = kalshi_targets(teams, cfg["champ"], 1.0)
    final = {}
    for s in cfg["final"]:
        final.update(kalshi_targets(teams, s, 1.0))
    # each conference's champion prices sum to 1 -> two finalists in total; keep them as-is (sum 2)
    play = kalshi_targets(teams, cfg["playoffs"], float(cfg["n_playoffs"]))
    return {t: dict(champ=champ.get(t), final=final.get(t), playoffs=play.get(t)) for t in teams}


LEAGUES = {
    "NFL": (lambda: sum(ls.NFL_DIV.values(), [])),
    "NBA": (lambda: sum(ls.NBA_CONF.values(), [])),
    "NHL": (lambda: [t for d in ls.NHL_DIV.values() for t in d]),
}

if __name__ == "__main__":
    which = sys.argv[1:] or ["NFL", "NBA", "NHL"]
    for lg in which:
        games = json.load(open(os.path.join(HERE, "raw", f"{lg.lower()}_games_{DATE}.json")))
        teams = LEAGUES[lg]()
        tg = make_targets(lg, teams)
        alias = {"LA Clippers": "Los Angeles Clippers"}
        S, r, lad = apply(lg, teams, games, alias, lambda ents, tg=tg: tg)
        print(lg, "done; sum ladder", lad.sum(axis=0).round(2))
        for t in sorted(teams, key=lambda t: -(tg[t]["champ"] or 0))[:8]:
            i = S.idx[t]
            print(f"   {t:24} champ sim {lad[i,4]:.3f} tgt {tg[t]['champ'] or 0:.3f} | final sim {lad[i,3]:.3f} tgt {tg[t]['final'] or 0:.3f} | po sim {lad[i,0]:.2f} tgt {tg[t]['playoffs'] or 0:.2f}")
