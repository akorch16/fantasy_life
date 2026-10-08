#!/usr/bin/env python3
"""
Re-apply exchange prices to the team-sport data files.

    python3 draft_guide/kalshi_overlay.py draft_guide/raw/kalshi_2026-10-08.json

For NFL / NBA / NHL / NCAAF: sets p_champ from the title market and p_final from the conference-champion
market (Kalshi mids, confidence A), then rescales every team that has no exchange price so the field still
sums to ~1. Run after pulling new prices (see .claude/commands/fl-draft-prep.md), then rebuild the workbook.
Matching is one-to-one: exact name first, else the shortest team name containing the key.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")


def apply(cat, title, final, as_of):
    path = os.path.join(DATA, f"{cat}.json")
    doc = json.load(open(path))
    es = doc["entries"]

    def find(key, taken):
        kl = key.lower()
        exact = [e for e in es if e["name"].lower() == kl and id(e) not in taken]
        if exact:
            return exact[0]
        cand = sorted([e for e in es if kl in e["name"].lower() and id(e) not in taken], key=lambda e: len(e["name"]))
        return cand[0] if cand else None

    taken, named, missing = set(), {}, []
    for k, p in title["prices"].items():
        e = find(k, taken)
        if e:
            taken.add(id(e)); named[id(e)] = p
        else:
            missing.append(k)
    rest = max(1.0 - title.get("field_mass", 0.0) - sum(named.values()), 0.02)
    others = [e for e in es if id(e) not in named]
    s_other = sum(e.get("p_champ") or 0 for e in others) or 1.0
    for e in es:
        if id(e) in named:
            e["p_champ"] = named[id(e)]
            e["odds"] = f"Kalshi {named[id(e)]*100:.1f}%"
            e["source"] = f"{title['series']} exchange mid-price, pulled {as_of}"
            e["confidence"] = "A"
            e["as_of"] = as_of
        else:
            e["p_champ"] = round((e.get("p_champ") or 0) / s_other * rest, 4)
            if e.get("confidence") == "B":
                e["confidence"] = "C"
    if final:
        ft = set()
        for k, p in final["prices"].items():
            e = find(k, ft)
            if e:
                ft.add(id(e)); e["p_final"] = p
                if f"p(final)" not in (e.get("source") or ""):
                    e["source"] = (e.get("source") or "") + f"; p(final)={final['series']} Kalshi mid"
            else:
                missing.append("final:" + k)
    doc["as_of"] = as_of
    json.dump(doc, open(path, "w"), indent=1, ensure_ascii=False)
    print(f"{cat}: {len(named)} priced teams, rest mass {rest:.3f}, unmatched {missing}")


def main(argv):
    raw = json.load(open(argv[0]))
    for cat, title in raw["title"].items():
        apply(cat, title, raw.get("final", {}).get(cat), raw["as_of"])


if __name__ == "__main__":
    main(sys.argv[1:])
