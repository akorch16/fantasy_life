#!/usr/bin/env python3
"""Grade the 2025 draft (2026 league year) against the live standings and show how the league drafts each category.

    python3 draft_guide/draft_history.py [--player Korch]

Reads data/draft_log_2026.json (pick-by-pick log: round 0 = keeper round, 1-14 snake) and docs/scores.json
(current rank / baseline / bonus points per player per category). Prints
  1. category timing: first pick, median round, how many went in rounds 1-3 / 4-7 / 8+
  2. payoff by round bucket (baseline = rank points, bonus, total)
  3. per category: does picking earlier score more rank points? (Spearman of round vs rank points)
"""
import json
import os
import statistics as st
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CAT = {'nfl': 'NFL', 'nba': 'NBA', 'mlb': 'MLB', 'nhl': 'NHL', 'ncaaf': 'NCAAF', 'ncaab': 'NCAAB', 'tennis': 'Tennis',
       'golf': 'Golf', 'nascar': 'NASCAR', 'mls': 'MLS', 'actor': 'Actor', 'actress': 'Actress', 'musician': 'Musician',
       'country': 'Country', 'stock': 'Stock'}
INV = {v: k for k, v in CAT.items()}


def load():
    log = json.load(open(os.path.join(HERE, "data", "draft_log_2026.json")))["picks"]
    scores = json.load(open(os.path.join(HERE, "..", "docs", "scores.json")))
    sc = {(p["name"], c): v for p in scores["players"] for c, v in p["categories"].items()}
    for e in log:
        v = sc[(e["player"], INV[e["category"]])]
        e.update(rank=v["rank"], base=v["baseline_pts"], bonus=v["bonus_pts"], total=v["total_pts"])
    return log, scores


def spearman(x, y):
    rx, ry = np.argsort(np.argsort(x)), np.argsort(np.argsort(y))
    return float(np.corrcoef(rx, ry)[0, 1])


def main(argv):
    log, scores = load()
    print(f"scores as of {scores['last_updated']}")
    print("\nCATEGORY TIMING (draft rounds 1-14)")
    print(f"{'cat':9}{'1st pick#':>10}{'med rd':>8}{'rd1-3':>7}{'rd4-7':>7}{'rd8+':>6}{'keepers':>9}{'avg total':>11}")
    for c in CAT.values():
        L = [e for e in log if e["category"] == c]
        d = [e for e in L if e["round"] > 0]
        rds = sorted(e["round"] for e in d)
        print(f"{c:9}{min(e['overall'] for e in d):>10}{st.median(rds):>8}{sum(r <= 3 for r in rds):>7}"
              f"{sum(4 <= r <= 7 for r in rds):>7}{sum(r >= 8 for r in rds):>6}{sum(e['keeper'] for e in L):>9}{st.mean(e['total'] for e in L):>11.1f}")
    print("\nPAYOFF BY ROUND (non-keeper picks)")
    for lo, hi in [(0, 0), (1, 2), (3, 4), (5, 7), (8, 10), (11, 14)]:
        L = [e for e in log if lo <= e["round"] <= hi and not e["keeper"]]
        print(f" rounds {lo:>2}-{hi:<2} n={len(L):3}  base {st.mean(e['base'] for e in L):4.1f}  bonus {st.mean(e['bonus'] for e in L):4.1f}  total {st.mean(e['total'] for e in L):4.1f}")
    K = [e for e in log if e["keeper"]]
    print(f" keepers      n={len(K):3}  base {st.mean(e['base'] for e in K):4.1f}  bonus {st.mean(e['bonus'] for e in K):4.1f}  total {st.mean(e['total'] for e in K):4.1f}")
    print("\nDOES PICKING EARLIER PAY? (Spearman of round vs rank pts; negative = earlier better)")
    for c in CAT.values():
        L = [e for e in log if e["category"] == c and not e["keeper"]]
        print(f" {c:9} rho {spearman([e['round'] for e in L], [e['base'] for e in L]):+.2f}")
    if "--player" in argv:
        pl = argv[argv.index("--player") + 1]
        print(f"\n{pl.upper()} PICKS")
        for e in sorted((e for e in log if e["player"] == pl), key=lambda e: e["round"]):
            print(f" R{e['round']:2} {e['category']:9} {e['roster_name']:26} rank {e['rank']:4.1f} total {e['total']:5.1f}{'  (keeper)' if e['keeper'] else ''}")


if __name__ == "__main__":
    main(sys.argv[1:])
