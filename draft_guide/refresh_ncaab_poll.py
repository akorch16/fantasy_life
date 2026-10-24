"""Refresh draft_guide/data/NCAAB.json from the current AP Top 25 (ESPN).

NCAAB is scored on AP poll position, so once the preseason poll is out it is a better strength signal than the August
title prices (and the only signal for teams with no price). For each pool team in the poll:

    mu_new = 0.5 * mu_old + 0.5 * (0.97 - 0.0125 * (rank - 1))      # #1 -> 0.97 ... #25 -> 0.67

Teams not in the poll keep their old mu. Re-run weekly; the second run reads `mu_prior` (the pre-poll value) so the blend never
compounds. Needs ESPN reachable (run locally).

    python3 draft_guide/refresh_ncaab_poll.py
"""
import datetime
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
PATH = os.path.join(HERE, "data", "NCAAB.json")


def norm(s):
    s = unicodedata.normalize("NFKD", str(s).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def main():
    from scrapers import fetch_json
    d = fetch_json("https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/rankings", timeout=20)
    poll = next(p for p in d["rankings"] if p["name"] == "AP Top 25")
    ranks = {}
    for r in poll["ranks"]:
        t = r["team"]
        for key in {norm(t.get("location", "")), norm(t.get("displayName", "")), norm(t.get("shortDisplayName", ""))}:
            ranks[key] = r["current"]
    alias = {"uconn": "uconn", "st johns": "st john s"}
    doc = json.load(open(PATH))
    changed = []
    for e in doc["entries"]:
        rk = ranks.get(norm(e["name"])) or ranks.get(alias.get(norm(e["name"]), ""))
        if rk is None:
            continue
        old = e.setdefault("mu_prior", e["mu"])
        e["mu"] = round(0.5 * old + 0.5 * (0.97 - 0.0125 * (rk - 1)), 3)
        e["detail"] = f"AP Top 25 #{rk} ({datetime.date.today()})"
        changed.append((e["name"], rk, old, e["mu"]))
    doc["as_of"] = str(datetime.date.today())
    doc["note"] = ("mu = 50% Aug 4 title-price/estimate strength + 50% current AP Top 25 position (refresh_ncaab_poll.py; "
                   f"{poll.get('headline') or 'AP Top 25'}). Teams outside the poll keep the pre-poll mu (mu_prior).")
    json.dump(doc, open(PATH, "w"), indent=1, ensure_ascii=False)
    open(PATH, "a").write("\n")
    print(f"updated {len(changed)} teams from the AP poll")
    for n, rk, old, new in sorted(changed, key=lambda x: x[1]):
        print(f"  #{rk:>2} {n:16} mu {old:.3f} -> {new:.3f}")


if __name__ == "__main__":
    main()
