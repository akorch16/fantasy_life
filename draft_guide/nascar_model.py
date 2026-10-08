"""Recency-weighted NASCAR top-5 model. Input: data/nascar_history.json (final Cup standings 1st-5th by year)."""
import json
import os

DECAY = 0.65                      # weight multiplier per year back (2026 = 1.0)
LADDER = {1: 13, 2: 9, 3: 6.5, 4: 4, 5: 2.5}
FIELD = 36                        # full-time Cup entries
K_PRIOR = 1.2                     # pseudo-years of field prior mixed into every driver
HERE = os.path.dirname(os.path.abspath(__file__))


def model(names, old=None, history=None, last_year=2026):
    """names: all drivers on the board. old: {name: (p_top5, p_champ)} 2026-form estimates used only to
    break ties among drivers absent from the history table. Returns {name: dict(p_top5, p_champ, score, line)}."""
    h = history or json.load(open(os.path.join(HERE, "data", "nascar_history.json")))["years"]
    old = old or {}
    years = sorted(int(y) for y in h)
    w = {y: DECAY ** (last_year - y) for y in years}
    wsum = sum(w.values())
    listed = {n for y in h.values() for n in y}
    rest = max(FIELD - len(listed), 1)
    miss_w = sum(w[y] * (5 - len(h[str(y)])) for y in years) / wsum    # weighted top-5 slots/year held by unlisted drivers
    prior5 = miss_w / rest                                             # ~ per-year top-5 chance of an unlisted driver
    prior_c = 0.004
    ne = len(years)
    out = {}
    for n in names:
        if n in listed:
            t = sum(w[y] for y in years if n in h[str(y)]) / wsum
            c = sum(w[y] for y in years if h[str(y)].get(n) == 1) / wsum
            p5 = (ne * t + K_PRIOR * 5 / FIELD) / (ne + K_PRIOR)
            pc = 0.5 * ((ne * c + K_PRIOR / FIELD) / (ne + K_PRIOR)) + 0.5 * p5 / 5
        else:                      # absent from the table != zero: it only lists 7 drivers
            o5, oc = old.get(n, (prior5, prior_c))
            p5 = 0.5 * prior5 + 0.5 * min(o5, 0.3) * 0.3
            pc = 0.5 * prior_c + 0.5 * min(oc, 0.06) * 0.3
        s = sum(w[y] * LADDER.get(h[str(y)].get(n), 0) for y in years) / wsum
        line = " • ".join(f"{y} ({'1st 2nd 3rd 4th 5th'.split()[h[str(y)][n]-1]})" for y in years if n in h[str(y)])
        out[n] = dict(p_top5=p5, p_champ=pc, score=s, line=line)
    # renormalise: board + phantom unlisted cars (FIELD - len(names)) must total 5 top-5s and 1 title
    extra = max(FIELD - len(out), 0)
    for key, total, ph in (("p_top5", 5.0, prior5), ("p_champ", 1.0, prior_c)):
        board = sum(v[key] for v in out.values())
        scale = max(total - ph * extra, 0.1) / board
        for v in out.values():
            v[key] = min(v[key] * scale, 0.97)
    return out
