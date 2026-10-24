#!/usr/bin/env python3
"""Refresh data/NCAAF.json from the current AP poll + Kalshi CFP-qualification and title prices.

    python3 draft_guide/ncaaf_update.py draft_guide/raw/cfb_<date>.json

The league scores NCAAF on the FINAL AP poll (after the playoff), so the baseline strength `mu` blends
  * where a team sits in the AP poll now (rank_mu = 0.86 at #1, -0.016 per place; unranked by votes), and
  * how likely the market thinks it is to make the 12-team CFP (playoff_mu = 0.40 + 0.48 x P(CFP)),
70/30 (the baseline IS the AP poll; market prices mostly reflect playoff wins, which the bonus ladder
already carries). Bonus ladder: p_champ = Kalshi title mid, p_r1 = Kalshi make-the-CFP mid (the 2.5-pt floor); the later
rounds are inferred from p_champ by build_workbook.infer_ladder. Teams in the poll or priced to make the CFP but
missing from the pool are added (confidence B).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ALIAS = {"Miami": "Miami (FL)"}


def rank_mu(rank=None, votes=0):
    if rank:
        return 0.86 - 0.016 * (rank - 1)
    return 0.42 + min(votes, 150) / 150 * 0.04          # receiving votes: 0.42-0.46


def main(path):
    raw = json.load(open(path))
    as_of = raw["as_of"]
    ap = {ALIAS.get(r["team"], r["team"]): r for r in raw["ap"]}
    votes = {ALIAS.get(r["team"], r["team"]): r["points"] for r in raw.get("ap_others", [])}
    cfp, title = raw["cfp"], raw["title"]
    dpath = os.path.join(HERE, "data", "NCAAF.json")
    d = json.load(open(dpath))
    ents = {e["name"]: e for e in d["entries"]}
    for name in set(ap) | {k for k, v in cfp.items() if v >= 0.05}:
        if name not in ents:
            ents[name] = {"name": name, "confidence": "B", "notes": "added from AP poll / Kalshi CFP market"}
            d["entries"].append(ents[name])
    for name, e in ents.items():
        a = ap.get(name)
        pc = cfp.get(name)
        rm = rank_mu(a["rank"] if a else None, votes.get(name, 0))
        pm = 0.40 + 0.48 * pc if pc is not None else rm
        e["mu"] = round(0.7 * rm + 0.3 * pm, 4)
        e["sd"] = 0.15 if a and a["rank"] <= 12 else 0.16
        if name in title:
            e["p_champ"] = title[name]
            e["odds"] = f"Kalshi title {title[name]:.1%} / CFP {pc:.0%}" if pc is not None else f"Kalshi title {title[name]:.1%}"
        elif pc is not None:
            e["p_champ"] = round(min(e.get("p_champ") or 0.005, 0.01), 4)
            e["odds"] = f"Kalshi CFP {pc:.0%}"
        if pc is not None:
            e["p_r1"] = round(pc, 4)
            e["confidence"] = "A"
        rec = f"AP #{a['rank']}, {a['record']}" + (f" (was #{a['prev']})" if a.get("prev") else "") if a else ("receiving votes" if name in votes else "unranked")
        e["detail"] = rec + (f" | CFP {pc:.0%}" if pc is not None else "")
        e["source"] = f"ESPN AP Top 25 (Week 8) + Kalshi KXNCAAFPLAYOFF-26/KXNCAAF-27 mids, pulled {as_of}"
        e["as_of"] = as_of
    d["as_of"] = as_of
    d["note"] = ("Final-AP-poll category. mu = 70/30 blend of current AP rank and Kalshi P(make CFP) (ncaaf_update.py); "
                 "p_champ = Kalshi title mid; p_r1 = Kalshi make-the-CFP mid; later rounds inferred from p_champ.")
    json.dump(d, open(dpath, "w"), indent=1, ensure_ascii=False)
    for e in sorted(d["entries"], key=lambda e: -(e.get("mu") or 0))[:16]:
        print(f"{e['name']:16} mu {e['mu']:.3f}  p_champ {e.get('p_champ') or 0:.3f}  p_r1 {e.get('p_r1') or 0:.2f}  {e['detail']}")


if __name__ == "__main__":
    main(sys.argv[1])
