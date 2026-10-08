#!/usr/bin/env python3
"""Moneyball view of the 2025 draft: what each pick cost (round) vs what it is projected to finish worth.

projected final = current total (docs/scores.json) + projected remaining points for that category
(docs/projections.json category_expected: MLS / NASCAR / MLB bonuses not yet realised, Actor / Actress / Country / Stock
still moving). 'Price' = the round it went; 'surplus' = projected final minus what a pick in that round normally returns.
"""
import json
import os
import statistics as st
import sys

import numpy as np

import draft_history as h

HERE = os.path.dirname(os.path.abspath(__file__))


def build():
    log, scores = h.load()
    proj = json.load(open(os.path.join(HERE, "..", "docs", "projections.json")))
    exp = {p["name"]: p["category_expected"] for p in proj["players"]}
    for e in log:
        e["exp_more"] = exp[e["player"]].get(h.INV[e["category"]], 0.0)
        e["final"] = e["total"] + e["exp_more"]
        e["pick"] = e["overall"] if e["overall"] else 0
    # price curve: mean projected final by round (keeper round = 0); smooth with 3-round window
    rounds = sorted({e["round"] for e in log})
    curve = {r: st.mean(e["final"] for e in log if e["round"] == r) for r in rounds}
    sm = {r: st.mean(curve[x] for x in rounds if abs(x - r) <= 1) for r in rounds}
    for e in log:
        e["market"] = sm[e["round"]]
        e["surplus"] = e["final"] - e["market"]
    return log, curve, sm


def main(argv):
    log, curve, sm = build()
    print("MARKET CURVE (mean projected final by round, 3-round smooth)")
    print(" ".join(f"R{r}:{sm[r]:.1f}" for r in sorted(sm)))
    print("\nCATEGORY: avg round taken | avg projected final | avg surplus vs slot | best/worst | MLS/NASCAR/MLB still to come")
    rows = []
    for c in h.CAT.values():
        L = [e for e in log if e["category"] == c]
        d = [e for e in L if e["round"] > 0]
        rows.append((c, st.mean(e["round"] for e in d), st.mean(e["final"] for e in L), st.mean(e["surplus"] for e in L),
                     max(e["final"] for e in L), min(e["final"] for e in L), st.mean(e["exp_more"] for e in L)))
    for r in sorted(rows, key=lambda r: -r[3]):
        print(f" {r[0]:9} rd {r[1]:4.1f} | final {r[2]:5.1f} | surplus {r[3]:+5.1f} | best {r[4]:5.1f} worst {r[5]:5.1f} | still to add {r[6]:+.2f}")
    print("\nBIGGEST STEALS (late round, high projected final)")
    for e in sorted(log, key=lambda e: -e["surplus"])[:15]:
        print(f" R{e['round']:2} #{e['pick']:>3} {e['player']:9} {e['category']:9} {e['roster_name']:24} final {e['final']:5.1f} (slot avg {e['market']:.1f}) {e['surplus']:+.1f}")
    print("\nBIGGEST BUSTS (early round, low projected final)")
    for e in sorted(log, key=lambda e: e["surplus"])[:15]:
        print(f" R{e['round']:2} #{e['pick']:>3} {e['player']:9} {e['category']:9} {e['roster_name']:24} final {e['final']:5.1f} (slot avg {e['market']:.1f}) {e['surplus']:+.1f}")


if __name__ == "__main__":
    main(sys.argv[1:])
