"""2027 league standings -> docs/scores_2027.json (same shape and scoring as docs/scores.json).

Scoring is the 2026 format: per category, rank the 13 owners' picks (RANK.AVG ties), 13 pts for 1st ... 1 pt for 13th,
plus bonus points from data/bonuses_2027.json. Country also carries the 2027 Women's World Cup bonus (uncapped).

Only categories whose 2027 scoring season is already underway are ranked now:
    NFL  (2026 season, win %)            NBA  (2026-27, win %)         NHL (2026-27, points %)
    NCAAF (AFCA Coaches Poll)            NCAAB (AP Top 25)
MLB, MLS, NASCAR, Golf, Tennis, Actor, Actress, Musician, Country and Stock are calendar-2027 events: no points until they
start (their rows show the pick and 0). Bonus entries for any category are still honoured.

Live data is fetched from the same public endpoints the draft guide used (ESPN standings/polls, NHL API); raw rows are cached
in data/standings_2027.json so a failed fetch re-scores from the last good values and is flagged stale.
"""
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from draft_picks_2027 import DRAFT_PICKS_2027, PLAYERS_2027, TENNIS_GENDER_2027  # noqa: E402

CATS = ["NFL", "NBA", "MLB", "NHL", "NCAAF", "NCAAB", "Tennis", "Golf", "NASCAR", "MLS",
        "Actor", "Actress", "Musician", "Country", "Stock"]
LIVE = ["NFL", "NBA", "NHL", "NCAAF", "NCAAB"]
SEASON = 2027
MISSING_POLL_RANK = 26                       # unranked in a Top-25 poll
OUT = os.path.join(HERE, "docs", "scores_2027.json")
CACHE = os.path.join(HERE, "data", "standings_2027.json")
BONUSES = os.path.join(HERE, "data", "bonuses_2027.json")
UTC = timezone.utc

NOTE = ("2027 season. Live standings: NFL, NBA, NHL, college football (Coaches Poll) and college basketball (AP poll). "
        "MLB, MLS, NASCAR, Golf, Tennis, Actor, Actress, Musician, Country (incl. the Women's World Cup bonus) and Stock "
        "start scoring when their 2027 seasons begin.")


def norm(s):
    s = unicodedata.normalize("NFKD", str(s).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9()&. ]", " ", s)).strip()


def rank_avg(values, reverse=True):
    """RANK.AVG: tied values share the average of the ranks they span (same as scoring.rank_avg)."""
    items = sorted(values.items(), key=lambda kv: kv[1], reverse=reverse)
    ranks, i = {}, 0
    while i < len(items):
        j = i
        while j < len(items) - 1 and items[j][1] == items[j + 1][1]:
            j += 1
        for k in range(i, j + 1):
            ranks[items[k][0]] = (i + 1 + j + 1) / 2.0
        i = j + 1
    return ranks


def rank_to_points(rank, n=13):
    return max(0, n - rank + 1)


# ── fetchers (each returns rows or raises) ───────────────────────────────────────
def _espn_standings(sport, league):
    from scrapers import fetch_json
    urls = [f"https://site.api.espn.com/apis/v2/sports/{sport}/{league}/standings",
            f"https://site.web.api.espn.com/apis/v2/sports/{sport}/{league}/standings"]
    last = None
    for url in urls:
        try:
            d = fetch_json(url, timeout=20)
            rows = []
            for ch in d.get("children", []):
                for e in ch.get("standings", {}).get("entries", []):
                    st = {s["name"]: s.get("value") for s in e.get("stats", [])}
                    w, l, t = (st.get("wins") or 0), (st.get("losses") or 0), (st.get("ties") or 0)
                    gp = w + l + t
                    rows.append({"team": e["team"]["displayName"], "wins": w, "losses": l, "ties": t,
                                 "win_pct": round((w + 0.5 * t) / gp, 4) if gp else 0.0})
            if len(rows) >= 28:
                return rows, url
        except Exception as ex:           # try the next endpoint
            last = ex
    raise RuntimeError(f"ESPN {sport}/{league} standings unavailable ({last})")


def fetch_nfl():
    return _espn_standings("football", "nfl")


def fetch_nba():
    return _espn_standings("basketball", "nba")


def fetch_nhl():
    from scrapers import fetch_json
    url = "https://api-web.nhle.com/v1/standings/now"
    d = fetch_json(url, timeout=20)
    rows = []
    for r in d["standings"]:
        gp = r.get("gamesPlayed") or 0
        pts = r.get("points") or 0
        rows.append({"team": r["teamName"]["default"], "gp": gp, "points": pts,
                     "points_pct": round(pts / (2 * gp), 4) if gp else 0.0})
    if len(rows) < 30:
        raise RuntimeError("NHL standings incomplete")
    return rows, url


def _espn_poll(sport, league, poll_name):
    from scrapers import fetch_json
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/rankings"
    d = fetch_json(url, timeout=20)
    poll = next((p for p in d.get("rankings", []) if p.get("name") == poll_name), None)
    if not poll:
        raise RuntimeError(f"{poll_name} not found at {url}")
    rows = []
    for r in poll["ranks"]:
        t = r["team"]
        rows.append({"rank": r["current"], "team": t.get("displayName") or f"{t.get('location')} {t.get('name')}",
                     "location": t.get("location"), "short": t.get("shortDisplayName"), "abbr": t.get("abbreviation")})
    return rows, url


def fetch_ncaaf():
    return _espn_poll("football", "college-football", "AFCA Coaches Poll")


def fetch_ncaab():
    return _espn_poll("basketball", "mens-college-basketball", "AP Top 25")


FETCH = {"NFL": fetch_nfl, "NBA": fetch_nba, "NHL": fetch_nhl, "NCAAF": fetch_ncaaf, "NCAAB": fetch_ncaab}
METRIC = {"NFL": ("win_pct", True), "NBA": ("win_pct", True), "NHL": ("points_pct", True),
          "NCAAF": ("rank", False), "NCAAB": ("rank", False)}

# pick text -> normalized names a source may call it (exact match only: "Texas" must never match "Texas Tech")
POLL_ALIAS = {"miami (fl)": {"miami", "miami hurricanes"}, "uconn": {"uconn", "connecticut", "uconn huskies"},
              "ole miss": {"ole miss", "mississippi", "ole miss rebels"}, "byu": {"byu", "byu cougars"}}
ALIAS = {"utah mammoth": {"utah mammoth", "utah hockey club"}, "montreal canadiens": {"montreal canadiens"}}


def candidates(pick):
    n = norm(pick)
    return {n} | POLL_ALIAS.get(n, set()) | ALIAS.get(n, set())


def find_row(cat, pick, rows):
    want = candidates(pick)
    for r in rows:
        names = {norm(r.get("team", "")), norm(r.get("location") or ""), norm(r.get("short") or ""), norm(r.get("abbr") or "")}
        if want & names:
            return r
    return None


# ── bonuses ──────────────────────────────────────────────────────────────────────
def load_bonuses():
    try:
        return json.load(open(BONUSES))
    except Exception:
        return {}


def now_utc():
    return datetime.now(UTC)


def main():
    cache = {}
    try:
        cache = json.load(open(CACHE))
    except Exception:
        pass
    now = now_utc()
    fresh, source_of = {}, {}
    for cat in LIVE:
        try:
            rows, src = FETCH[cat]()
            cache[cat] = {"fetched_at": now.isoformat(), "source": src, "rows": rows}
            source_of[cat] = "live"
            print(f"  ✓ {cat}: {len(rows)} rows from {src}")
        except Exception as e:
            print(f"  ✗ {cat}: {e} — using cached values" if cat in cache else f"  ✗ {cat}: {e} — no cache")
            source_of[cat] = "cache" if cat in cache else "missing"
        fresh[cat] = cache.get(cat)

    bonuses = load_bonuses()
    wwc = bonuses.get("Country_WWC", {}) or {}
    cat_scores = {}                      # cat -> {owner: entry}
    for cat in CATS:
        picks = DRAFT_PICKS_2027[cat]
        entries = {o: {"pick": picks[o], "raw_value": None, "raw_display": None, "rank": None, "baseline_pts": 0, "bonus_pts": 0}
                   for o in PLAYERS_2027}
        if cat in LIVE and fresh.get(cat):
            rows = fresh[cat]["rows"]
            key, reverse = METRIC[cat]
            vals = {}
            for o in PLAYERS_2027:
                row = find_row(cat, picks[o], rows)
                if row is None:
                    vals[o] = MISSING_POLL_RANK if key == "rank" else None
                    if key != "rank":
                        print(f"  ⚠ {cat}: no row matched for {o}'s pick {picks[o]!r}")
                else:
                    vals[o] = row[key]
            scoreable = {o: v for o, v in vals.items() if v is not None}
            ranks = rank_avg(scoreable, reverse=reverse)
            for o in PLAYERS_2027:
                if o in ranks:
                    entries[o]["raw_value"] = None if (key == "rank" and vals[o] == MISSING_POLL_RANK) else vals[o]
                    entries[o]["rank"] = ranks[o]
                    entries[o]["baseline_pts"] = rank_to_points(ranks[o])
                if cat in ("NFL", "NBA"):
                    row = find_row(cat, picks[o], rows)
                    if row:
                        t = f"-{row['ties']}" if row.get("ties") else ""
                        entries[o]["raw_display"] = f"{int(row['wins'])}-{int(row['losses'])}{t}"
        for o in PLAYERS_2027:
            b = (bonuses.get(cat, {}) or {}).get(o, 0) or 0
            if cat == "Country":
                b += wwc.get(o, 0) or 0
                entries[o]["world_cup_bonus_pts"] = round(wwc.get(o, 0) or 0, 2)
            entries[o]["bonus_pts"] = b
        cat_scores[cat] = entries

    players = []
    for o in PLAYERS_2027:
        cats, total = {}, 0.0
        for cat in CATS:
            e = cat_scores[cat][o]
            ct = (e["baseline_pts"] or 0) + (e["bonus_pts"] or 0)
            total += ct
            cats[cat.lower()] = {"pick": e["pick"], "raw_value": e["raw_value"], "raw_display": e["raw_display"], "rank": e["rank"],
                                 "baseline_pts": round(e["baseline_pts"], 2), "bonus_pts": round(e["bonus_pts"], 2),
                                 "total_pts": round(ct, 2),
                                 **({"world_cup_bonus_pts": e["world_cup_bonus_pts"], "olympics_bonus_pts": 0} if cat == "Country" else {}),
                                 "not_started": cat not in LIVE}
        players.append({"name": o, "total": round(total, 2), "categories": cats, "is_premium": False})
    players.sort(key=lambda p: -p["total"])
    for i, p in enumerate(players, 1):
        p["place"] = i

    # 7-day history + deltas, same approach as scoring.py
    prev = {}
    try:
        prev = json.load(open(OUT))
    except Exception:
        pass
    hist = prev.get("score_history", [])
    today = now.strftime("%Y-%m-%d")
    snap = {"date": today, "totals": {p["name"]: p["total"] for p in players}, "places": {p["name"]: p["place"] for p in players}}
    hist = [h for h in hist if h.get("date") != today] + [snap]
    cutoff = (now - timedelta(days=10)).strftime("%Y-%m-%d")
    hist = sorted((h for h in hist if h["date"] >= cutoff), key=lambda h: h["date"])
    target = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    base = min(hist, key=lambda h: abs((datetime.strptime(h["date"], "%Y-%m-%d") - datetime.strptime(target, "%Y-%m-%d")).days))
    for p in players:
        n = p["name"]
        if n in base["totals"] and base["date"] != today:
            p["week_delta"] = round(p["total"] - base["totals"][n], 2)
            p["place_change"] = base["places"].get(n, p["place"]) - p["place"]
        else:
            p["week_delta"], p["place_change"] = None, None

    freshness = {}
    for cat in LIVE:
        c = fresh.get(cat)
        age = (now - datetime.fromisoformat(c["fetched_at"])).days if c else None
        freshness[cat.lower()] = {"updated_at": c["fetched_at"] if c else None, "age_days": age,
                                  "stale": source_of[cat] != "live" and (age is None or age > 3), "source": source_of[cat]}

    doc = {"players": players, "last_updated": now.strftime("%Y-%m-%d %H:%M UTC"), "season": SEASON,
           "golf_data_stale": False, "data_freshness": freshness, "headline": NOTE, "headline_generated_at": None,
           "score_history": hist, "live_categories": [c.lower() for c in LIVE]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(doc, f)
    with open(CACHE, "w") as f:
        json.dump(cache, f)
    print(f"\nwrote {OUT}  ({len(players)} players)")
    for p in players:
        live = " ".join(f"{c.upper()[:4]}={p['categories'][c.lower()]['baseline_pts']:g}" for c in LIVE)
        print(f"  {p['place']:>2}. {p['name']:8} {p['total']:6.1f}   {live}")


if __name__ == "__main__":
    main()
