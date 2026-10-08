"""Grammy bonus EV with the 13-pt category cap applied to the OUTCOME, not the mean.

League scoring (CLAUDE.md Rulings): Record/Album/Song of the Year win +7, any other win +3, nomination +1 (a win replaces
its nomination point). Bonus is capped at 13 per category (Amend. 7.14).

Per artist (data/grammy_specs.json):
  big_win / big_nom : P(win) / P(nominated) for Album, Record, Song of the Year (Kalshi where available)
  bna               : (P(nom), P(win)) Best New Artist
  other_noms        : expected number of OTHER nominations (genre/craft categories); each wins with the historical rate
Win rate for other nominations is calibrated on data/grammy_history.json (top-10 nominees, 2021-2026 ceremonies).
"""
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SIMS = 100_000


def hist_rates():
    rows = json.load(open(os.path.join(HERE, "data", "grammy_history.json")))["rows"]
    n = sum(r["noms"] for r in rows)
    w = sum(r["wins"] for r in rows)
    b = sum(r["big3_wins"] for r in rows)
    return (w - b) / (n - b)            # win rate per non-big-3 nomination, ~0.23


def simulate(spec, rate, seed=7):
    rng = np.random.default_rng(seed)
    x = np.zeros(SIMS)
    for w, n in zip(spec["big_win"], spec["big_nom"]):
        u = rng.random(SIMS)
        x += np.where(u < w, 7, np.where(u < n, 1, 0))
    pn, pw = spec.get("bna", (0, 0))
    u = rng.random(SIMS)
    x += np.where(u < pw, 3, np.where(u < pn, 1, 0))
    k = rng.poisson(spec.get("other_noms", 0), SIMS)
    won = rng.binomial(k, rate)
    x += 3 * won + (k - won)
    return x


def evaluate(spec, rate=None):
    rate = hist_rates() if rate is None else rate
    x = simulate(spec, rate)
    return dict(raw=float(x.mean()), ev=float(np.minimum(x, 13).mean()), p_cap=float((x >= 13).mean()))


def main():
    specs = json.load(open(os.path.join(HERE, "data", "grammy_specs.json")))["artists"]
    path = os.path.join(HERE, "data", "Musician.json")
    d = json.load(open(path))
    rate = hist_rates()
    for e in d["entries"]:
        s = specs.get(e["name"])
        if not s:
            continue
        r = evaluate(s, rate)
        e["grammy_ev"], e["grammy_raw"], e["grammy_p_cap"] = round(r["ev"], 2), round(r["raw"], 2), round(r["p_cap"], 2)
        e["odds"] = f"Grammy EV {r['ev']:.1f} (raw {r['raw']:.1f}, P(cap) {r['p_cap']:.0%})"
        print(f"{e['name']:16} raw {r['raw']:5.2f}  capped EV {r['ev']:5.2f}  P(>=13) {r['p_cap']:.2f}")
    json.dump(d, open(path, "w"), indent=1, ensure_ascii=False)
    print(f"other-nomination win rate (history) = {rate:.3f}")


if __name__ == "__main__":
    main()
