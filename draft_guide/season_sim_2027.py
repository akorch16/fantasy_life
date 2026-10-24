"""2027 season projections from the finished draft board (same output shape as docs/projections.json).

For every simulated season, each of the 13 owners' 15 picks gets
  * a baseline outcome ~ the guide's per-candidate distribution (mu/sd, or the 'q' quantile curve for musicians),
    ranked within the category among the 13 owners' picks -> 13 pts for best ... 1 pt for worst, and
  * a bonus outcome sampled from the guide's own ladders (playoff depth, slams/majors, NASCAR top 5, Oscars, Grammys,
    Women's World Cup), capped at 13 per category (Country uncapped, league ruling Oct 2026).
Picks are matched to candidates in draft_guide/data/*.json (the same numbers as the draft workbook). A pick outside a
category's candidate pool is scored as that pool's weakest candidate (reported at the end).

    python3 draft_guide/season_sim_2027.py [board.xlsx] [--sims N] [--site]

Rosters come from draft_picks_2027.py (or an alternate board.xlsx for what-ifs). Pure Python (no numpy).
Writes draft_guide/projections_2027.json and prints the standings table; --site also writes docs/projections_2027.json
(the shape docs/projections.html reads with ?season=2027, which overlays live standings for the 'Now' column).
"""
import argparse
import datetime
import difflib
import json
import math
import os
import random
import re
import sys
import types
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import openpyxl  # noqa: E402  (must load before the numpy stub below)


def _load_builder():
    """build_workbook imports numpy at the top, but only its rank-points Monte Carlo needs it; stub it if absent."""
    try:
        import numpy  # noqa: F401
    except ImportError:
        sys.modules["numpy"] = types.ModuleType("numpy")
    import build_workbook
    return build_workbook


B = _load_builder()
CATS = B.CATS
BOARD_CAT = {"Music": "Musician"}

# ── name matching ─────────────────────────────────────────────────────────────────
ALIAS = {
    "okc": "oklahoma city thunder", "cavs": "cleveland cavaliers", "76ers": "philadelphia 76ers", "da bears": "chicago bears",
    "white sucks": "chicago white sox", "red sox!?": "boston red sox", "vegas!!!?": "vegas golden knights", "nj devils": "new jersey devils",
    "mammoth": "utah mammoth", "panthers": "florida panthers", "wild": "minnesota wild", "bruins": "ucla", "djovkovic (wow)": "novak djokovic",
    "carlos": "carlos alcaraz", "sabs": "aryna sabalenka", "rory": "rory mcilroy", "sam mr. burns": "sam burns", "cam young": "cameron young",
    "byron": "william byron", "lafc": "los angeles fc", "sam mr. burns effect": "sam burns", "larson": "kyle larson", "taylor": "taylor swift", "arianna grand": "ariana grande", "sdfc": "san diego fc",
    "nashville fc": "nashville sc", "dallas fc": "fc dallas", "philly union": "philadelphia union", "st louis city": "st. louis city sc",
    "usa": "united states", "england": "united kingdom", "iraq women's soccer": "iraq", "mirra andreev": "mirra andreeva",
    "pegula": "jessica pegula", "svitolina": "elina svitolina", "rybakina": "elena rybakina", "zverev": "alexander zverev",
    "sinner": "jannik sinner", "swiatek": "iga swiatek", "medvedev": "daniil medvedev", "matsuyama": "hideki matsuyama",
    "aberg": "ludvig aberg", "schauffele": "xander schauffele", "ryan gosling": "ryan gosling", "robert pattinson": "robert pattinson",
}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.strip())


def match_pick(cat, text, pool):
    """Returns (entry or None, how). Order: exact/alias -> contains -> last word -> closest spelling."""
    t = ALIAS.get(norm(text), norm(text))
    names = {norm(e["name"]): e for e in pool}
    if t in names:
        return names[t], "exact"
    best = [e for n, e in names.items() if t in n and len(t) >= 3]   # pick text inside the pool name only ("Florida State" must not collapse to "Florida")
    if best:
        return max(best, key=lambda e: (e.get("mu") or 0)), "contains"
    last = [e for n, e in names.items() if n.split()[-1] == t.split()[-1] and len(t.split()[-1]) >= 4]
    if len(last) == 1:
        return last[0], "last word"
    close = difflib.get_close_matches(t, list(names), n=1, cutoff=0.78)
    if close:
        return names[close[0]], "spelling"
    return None, "not in pool"


# ── sampling ──────────────────────────────────────────────────────────────────────
def draw_score(e, rng):
    q = e.get("q")
    if q:
        u = rng.random() * (len(q) - 1)
        i = int(u)
        return q[i] + (q[min(i + 1, len(q) - 1)] - q[i]) * (u - i)
    return rng.gauss(e.get("mu") or 0.0, max(e.get("sd") or 1e-6, 1e-6))


LAD = [13.0, 9.0, 6.5, 4.0, 2.5]


def team_bonus(e, rng, ladder):
    probs, _ = B.infer_ladder(e)
    if probs.get("p_champ") is None:
        return 0.0
    u = rng.random()
    for k, pts in zip(B.PROB_KEYS, ladder):
        if u < probs[k]:
            return pts
    return 0.0


def poisson(lam, rng):
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def grammy_bonus(e, rng, specs, rate):
    s = specs.get(e["name"])
    if not s:
        return e.get("grammy_ev") or 0.0
    x = 0.0
    for w, n in zip(s["big_win"], s["big_nom"]):
        u = rng.random()
        x += 7 if u < w else (1 if u < n else 0)
    pn, pw = s.get("bna", (0, 0))
    u = rng.random()
    x += 3 if u < pw else (1 if u < pn else 0)
    k = poisson(s.get("other_noms", 0), rng)
    won = sum(1 for _ in range(k) if rng.random() < rate)
    return x + 3 * won + (k - won)


def oscar_bonus(e, cat, awards, rng):
    key = "Actor" if cat == "Actor" else "Actress"
    x = 0.0
    for a in awards:
        if a.get("name") != e["name"] or key not in (a.get("category") or ""):
            continue
        pn, pw = a.get("p_nom") or 0, a.get("p_win") or 0
        win, nom = (13, 4) if "Supporting" not in a.get("category", "") else (9, 2.5)
        u = rng.random()
        x += win if u < pw else (nom if u < pn else 0)
    return x


def sample_bonus(cat, e, rng, ctx):
    if cat in B.TEAM:
        lad = ctx["ladders"][cat]
        return team_bonus(e, rng, lad)
    if cat == "Tennis":
        return (4.0 if rng.random() < (e.get("p_slam_win") or 0) else 0) + (2.5 if rng.random() < (e.get("p_slam_ru") or 0) else 0)
    if cat == "Golf":
        return (6.0 if rng.random() < (e.get("p_major_win") or 0) else 0) + (2.5 if rng.random() < (e.get("p_major_ru") or 0) else 0)
    if cat == "NASCAR":
        pc, p5 = e.get("p_champ") or 0, e.get("p_top5") or 0
        u = rng.random()
        return 13.0 if u < pc else (ctx["nascar_other"] if u < p5 else 0.0)
    if cat in ("Actor", "Actress"):
        return oscar_bonus(e, cat, ctx["awards"], rng)
    if cat == "Musician":
        return grammy_bonus(e, rng, ctx["grammy_specs"], ctx["grammy_rate"])
    if cat == "Country":
        probs = {k: e.get("wwc_" + k) for k in B.PROB_KEYS}
        if probs["p_champ"] is None:
            return 0.0
        u = rng.random()
        for k, pts in zip(B.PROB_KEYS, LAD):
            if u < probs[k]:
                return pts
        return 0.0
    return 0.0


def american(pct):
    """Mirror of toAmericanOdds() in docs/projections.html (pct in percent)."""
    f = pct / 100
    if f <= 0:
        return None
    raw = -(f / (1 - f)) * 100 if f >= 0.5 else ((1 - f) / f) * 100
    a = abs(raw)
    unit = 100 if a < 1000 else 1000 if a <= 15000 else 10000 if a < 100000 else 100000
    return int(round(raw / unit) * unit)


# ── board ─────────────────────────────────────────────────────────────────────────
def read_board(path):
    ws = openpyxl.load_workbook(path, data_only=True)["2027"]
    rows = list(ws.iter_rows(values_only=True))
    owners = [str(c).strip() for c in rows[0][1:14]]
    picks = {o: {} for o in owners}
    for r in rows[1:]:
        cat = BOARD_CAT.get((r[0] or "").strip(), (r[0] or "").strip())
        if cat not in CATS:
            continue
        for i, o in enumerate(owners):
            if r[1 + i] not in (None, ""):
                picks[o][cat] = str(r[1 + i]).strip()
    return owners, picks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board", nargs="?")
    ap.add_argument("--sims", type=int, default=30000)
    ap.add_argument("--seed", type=int, default=2027)
    ap.add_argument("--site", action="store_true", help="also write docs/projections_2027.json for the website")
    args = ap.parse_args()
    if args.board:
        board = args.board
        owners, picks = read_board(board)
    else:
        sys.path.insert(0, os.path.dirname(HERE))
        from draft_picks_2027 import DRAFT_PICKS_2027, PLAYERS_2027
        board = "draft_picks_2027.py"
        owners = list(PLAYERS_2027)
        picks = {o: {c: DRAFT_PICKS_2027[c][o] for c in CATS} for o in owners}
    print(f"rosters: {os.path.basename(board)}  | owners: {len(owners)}  | picks: {sum(len(v) for v in picks.values())}")

    assum = B.load_assumptions()
    pool = {c: B.entries_for(c) for c in CATS}
    ctx = {"ladders": assum["ladders"], "awards": assum["_awards"], "nascar_other": assum["nascar_other_avg"]}
    ctx["ladders"] = dict(ctx["ladders"])
    ctx["ladders"]["MLS"] = LAD            # league ruling: made playoffs 2.5, then 4 / 6.5 / 9 / 13 (guide file still has the old MLS ladder)
    ctx["grammy_specs"] = json.load(open(os.path.join(HERE, "data", "grammy_specs.json")))["artists"]
    ctx["grammy_rate"] = _hist_rate()

    chosen, report = {}, []
    for o in owners:
        for cat in CATS:
            text = picks[o].get(cat)
            if not text:
                continue
            if cat == "Stock":
                e = dict(pool[cat][0])                   # flat category: every pick has the same mu/sd and no bonus
                e["name"] = text
                chosen[(o, cat)] = e
                continue
            e, how = match_pick(cat, text, pool[cat])
            if e is None:
                weakest = min(pool[cat], key=lambda x: x.get("mu") or 0)
                e = dict(weakest)
                e["name"] = text
                e["_label"] = f"{text} (not in pool)"
                for k in B.PROB_KEYS + ["wwc_p_champ", "p_slam_win", "p_slam_ru", "p_major_win", "p_major_ru", "p_top5", "grammy_ev", "wwc_ev"]:
                    e[k] = None
            chosen[(o, cat)] = e
            report.append((o, cat, text, e.get("_label", e["name"]), how))

    rng = random.Random(args.seed)
    n = args.sims
    tot = {o: [] for o in owners}
    rk_sum = {o: {c: 0.0 for c in CATS} for o in owners}
    bo_sum = {o: {c: 0.0 for c in CATS} for o in owners}
    wins = dict.fromkeys(owners, 0)
    top4 = dict.fromkeys(owners, 0)
    top3 = dict.fromkeys(owners, 0)
    last = dict.fromkeys(owners, 0)
    for _ in range(n):
        t = dict.fromkeys(owners, 0.0)
        for cat in CATS:
            scored = sorted(((draw_score(chosen[(o, cat)], rng) + rng.random() * 1e-9, o) for o in owners if (o, cat) in chosen), reverse=True)
            m = len(scored)
            for rank, (_, o) in enumerate(scored):
                pts = 13 - rank if m == 13 else (13 - rank * 12 / max(m - 1, 1))
                b = sample_bonus(cat, chosen[(o, cat)], rng, ctx)
                b = b if cat == "Country" else min(b, B.BONUS_CAP)
                t[o] += pts + b
                rk_sum[o][cat] += pts
                bo_sum[o][cat] += b
        order = sorted(owners, key=lambda o: -t[o] - rng.random() * 1e-9)
        wins[order[0]] += 1
        for o in order[:4]:
            top4[o] += 1
        for o in order[:3]:
            top3[o] += 1
        last[order[-1]] += 1
        for o in owners:
            tot[o].append(t[o])

    out = []
    for o in owners:
        s = sorted(tot[o])
        cat_exp = {c: round((rk_sum[o][c] + bo_sum[o][c]) / n, 2) for c in CATS if (o, c) in chosen}
        out.append({
            "name": o, "current_total": 0.0,
            "projected_total": round(sum(s) / n, 1), "projected_p10": round(s[int(n * 0.10)], 1),
            "projected_p50": round(s[n // 2], 1), "projected_p90": round(s[int(n * 0.90)], 1),
            "win_pct": round(wins[o] / n * 100, 2), "top3_pct": round(top3[o] / n * 100, 2),
            "top4_pct": round(top4[o] / n * 100, 2), "last_pct": round(last[o] / n * 100, 2),
            "american_odds": american(wins[o] / n * 100),
            "category_expected": cat_exp,
            "bonus_expected": round(sum(bo_sum[o].values()) / n, 1),
            "picks": {c: chosen[(o, c)].get("_label", chosen[(o, c)]["name"]) for c in CATS if (o, c) in chosen},
        })
    out.sort(key=lambda r: (-r["win_pct"], -r["projected_total"]))
    doc = {"generated_for": "2027 league year", "board": os.path.basename(board), "n_simulations": n, "players": out}
    path = os.path.join(HERE, "projections_2027.json")
    json.dump(doc, open(path, "w"), indent=1, ensure_ascii=False)

    print(f"\n{'#':>2} {'owner':11}{'proj':>7}{'p10-p90':>14}{'win %':>8}{'odds':>9}{'top-4 %':>9}{'top-3 %':>9}{'last %':>8}{'bonus':>7}")
    for i, r in enumerate(out, 1):
        od = "—" if r["american_odds"] is None else f"{r['american_odds']:+,}"
        print(f"{i:>2} {r['name']:11}{r['projected_total']:>7.1f}{r['projected_p10']:>7.0f}-{r['projected_p90']:<6.0f}{r['win_pct']:>7.1f}%{od:>9}{r['top4_pct']:>8.1f}%{r['top3_pct']:>8.1f}%{r['last_pct']:>7.1f}%{r['bonus_expected']:>7.1f}")
    print(f"\nwrote {path}")
    if args.site:
        site = {
            "season": 2027, "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "n_simulations": n, "kalshi_markets_used": [], "category_expected_basis": "final",
            "footer_note": "Pre-season model from the Oct 25, 2026 draft rosters; inputs are the draft guide's odds (Kalshi, Oscar/Grammy/Women's World Cup prices as of Oct 22-24). Not yet updated for in-season results.",
            "players": [{
                "name": r["name"], "current_total": 0.0, "projected_additional": r["projected_total"],
                "projected_total": r["projected_total"], "projected_p10": r["projected_p10"], "projected_p90": r["projected_p90"],
                "win_pct": r["win_pct"], "top4_pct": r["top4_pct"], "top3_pct": r["top3_pct"], "last_pct": r["last_pct"],
                "category_expected": {c.lower(): v for c, v in r["category_expected"].items()},
                "picks": {c.lower(): v for c, v in r["picks"].items()},
            } for r in out],
        }
        spath = os.path.join(os.path.dirname(HERE), "docs", "projections_2027.json")
        json.dump(site, open(spath, "w"), separators=(",", ":"), ensure_ascii=False)
        print(f"wrote {spath}")
    weak = [(o, c, tx, nm, how) for (o, c, tx, nm, how) in report if how in ("not in pool", "spelling", "last word")]
    print("\nmatching notes (non-exact):")
    for o, c, tx, nm, how in weak:
        print(f"   {o:10} {c:9} '{tx}' -> {nm}  [{how}]")


def _hist_rate():
    rows = json.load(open(os.path.join(HERE, "data", "grammy_history.json")))["rows"]
    n = sum(r["noms"] for r in rows); w = sum(r["wins"] for r in rows); b = sum(r["big3_wins"] for r in rows)
    return (w - b) / (n - b)


if __name__ == "__main__":
    main()
