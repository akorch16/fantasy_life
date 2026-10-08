"""Musician baseline for 2027: chart carry-over + new-hit lottery, on the league's raw scale.

League score (CLAUDE.md Rulings) = 2 x weeks at #1 + top-10 song-weeks, from weekly Hot 100 issues of the league year.
2027 issues start Jan 2 2027, so almost everything is unknown. Two parts:

1. CARRY-OVER (only songs charting NOW): each song currently in the top 30 of the latest issue is run forward as a
   Markov chain over rank buckets {1, 2-5, 6-10, 11-30, off}, with transition rates estimated from every week-to-week
   move of every song in the 2026 issues (raw/hot100_2026_*.json). Run to the first 2027 issue, then 52 issues of
   scoring. Songs no longer charting (Bad Bunny's) contribute nothing.
2. NEW HITS: a compound Poisson. Number of new top-10 songs ~ Poisson(LAMBDA_BASE + LAMBDA_PER_HIT x their count of
   top-10 songs that debuted in 2026); each new song's value is drawn from the empirical distribution of 2026
   debuts' (top-10 weeks + 2 x #1 weeks), scaled by IN_YEAR for runs cut off by year-end.

Output per artist: mean, sd, 101 quantiles (rank_points_mc samples these directly, so the heavy right tail is kept).
"""
import glob
import json
import os
import re
import unicodedata

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STATES = ["1", "2-5", "6-10", "11-30", "off"]
STEPS_TO_2027 = 12          # latest 2026 issue (Oct 10) -> Jan 2 2027 issue
WEEKS_2027 = 52
LAMBDA_BASE, LAMBDA_PER_HIT, LAMBDA_CAP = 0.15, 0.5, 2.0
IN_YEAR = 0.9
SIMS = 20_000


def norm(s):
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().strip()


def split_artists(text):
    parts = re.split(r"\s*[,&]\s*|\s+(?:featuring|feat\.?|with|x|and)\s+", text, flags=re.IGNORECASE)
    return [p.strip().strip('"').strip() for p in parts if p and len(p.strip()) >= 2]


def bucket(rank):
    if rank is None:
        return 4
    return 0 if rank == 1 else 1 if rank <= 5 else 2 if rank <= 10 else 3


def load_weeks():
    path = sorted(glob.glob(os.path.join(HERE, "raw", "hot100_2026_*.json")))[-1]
    return json.load(open(path)), path


def song_tables(weeks):
    """{(title, credit): [rank or None per week]}"""
    songs = {}
    for i, (_, rows) in enumerate(weeks):
        for rank, title, credit in rows:
            songs.setdefault((title, credit), [None] * len(weeks))[i] = rank
    return songs


def transition_matrix(songs):
    c = np.ones((5, 5)) * 0.05         # light smoothing
    for ranks in songs.values():
        for a, b in zip(ranks, ranks[1:]):
            if a is None:
                continue
            c[bucket(a), bucket(b)] += 1
    c[4] = [0, 0, 0, 0, 1]             # off is absorbing: a returning song is a "new" hit, modelled separately
    return c / c.sum(axis=1, keepdims=True)


def raw_score_per_state(s):
    return {0: 3, 1: 1, 2: 1, 3: 0, 4: 0}[s]        # top-10 week (+1) and #1 week (+2 extra)


def simulate_carry(P, start_state, rng, n=SIMS):
    state = np.full(n, start_state)
    cum = np.cumsum(P, axis=1)
    total = np.zeros(n)
    for step in range(STEPS_TO_2027 + WEEKS_2027):
        u = rng.random(n)
        state = (u[:, None] > cum[state]).sum(axis=1).clip(0, 4)
        if step >= STEPS_TO_2027:
            total += np.vectorize(raw_score_per_state)(state) if False else np.take([3, 1, 1, 0, 0], state)
    return total


def debut_values(songs, weeks):
    """Per-song (top-10 weeks + 2 x #1 weeks) for songs that entered the chart in 2026 (not week-1 carry-overs)
    and reached the top 10."""
    vals = []
    for ranks in songs.values():
        if ranks[0] is not None:
            continue
        v = sum(1 for r in ranks if r is not None and r <= 10) + 2 * sum(1 for r in ranks if r == 1)
        if any(r is not None and r <= 10 for r in ranks):
            vals.append(v)
    return np.array(vals, dtype=float)


def artist_index(songs, weeks):
    """norm(artist) -> dict(raw2026, songs_now [(title, rank)], debut_hits)"""
    idx = {}
    for (title, credit), ranks in songs.items():
        t10 = sum(1 for r in ranks if r is not None and r <= 10)
        n1 = sum(1 for r in ranks if r == 1)
        now = ranks[-1]
        debuted_2026 = ranks[0] is None
        for a in split_artists(credit):
            e = idx.setdefault(norm(a), dict(name=a, raw=0, now=[], hits=0))
            e["raw"] += t10 + 2 * n1
            if now is not None:
                e["now"].append((title, now))
            if debuted_2026 and t10 > 0:
                e["hits"] += 1
    return idx


def project(name, idx, P, vals, rng, aliases=None):
    key = norm((aliases or {}).get(name, name))
    e = idx.get(key, dict(name=name, raw=0, now=[], hits=0))
    carry = np.zeros(SIMS)
    for title, rank in e["now"]:
        carry += simulate_carry(P, bucket(rank), rng)
    lam = min(LAMBDA_BASE + LAMBDA_PER_HIT * e["hits"], LAMBDA_CAP)
    k = rng.poisson(lam, SIMS)
    new = np.zeros(SIMS)
    for i in range(int(k.max()) if k.size else 0):
        draw = rng.choice(vals, SIMS) * IN_YEAR
        new += np.where(k > i, draw, 0)
    tot = carry + new
    q = np.quantile(tot, np.linspace(0, 1, 101))
    return dict(mean=float(tot.mean()), sd=float(tot.std()), q=[round(float(x), 2) for x in q],
                raw2026=e["raw"], now=e["now"], hits=e["hits"], lam=lam, carry_mean=float(carry.mean()),
                new_mean=float(new.mean()), p_zero=float((tot < 0.5).mean()))


def main():
    weeks, path = load_weeks()
    songs = song_tables(weeks)
    P = transition_matrix(songs)
    vals = debut_values(songs, weeks)
    idx = artist_index(songs, weeks)
    rng = np.random.default_rng(2027)
    mpath = os.path.join(HERE, "data", "Musician.json")
    d = json.load(open(mpath))
    aliases = {"Beyoncé": "Beyonce"}
    print(f"weeks {len(weeks)} ({weeks[0][0]}..{weeks[-1][0]}), songs {len(songs)}, debut hits {len(vals)} (mean {vals.mean():.1f}, p90 {np.quantile(vals, .9):.0f})")
    print("transition matrix rows 1,2-5,6-10,11-30:\n", np.round(P[:4], 2))
    for e in d["entries"]:
        r = project(e["name"], idx, P, vals, rng, aliases)
        e["mu"], e["sd"], e["q"] = round(r["mean"], 1), round(r["sd"], 1), r["q"]
        now = "; ".join(f"{t} (#{k})" for t, k in r["now"][:3]) or "none charting"
        e["detail"] = (f"2026 raw {r['raw2026']}; charting now: {now}; carry-over {r['carry_mean']:.1f} + new hits {r['new_mean']:.1f} "
                       f"(lambda {r['lam']:.2f}, P(~0) {r['p_zero']:.0%})")
        print(f"{e['name']:18} 2026 raw {r['raw2026']:3d} now {len(r['now'])} carry {r['carry_mean']:5.1f} new {r['new_mean']:5.1f} -> mu {r['mean']:5.1f} sd {r['sd']:5.1f}")
    d["note"] = ("Baseline = 2 x #1 weeks + top-10 song-weeks in 2027 issues. music_model.py: Markov carry-over of songs charting in the latest 2026 issue "
                 "+ compound-Poisson new hits (empirical 2026 debut values). 'q' = 101 quantiles used by the rank simulation. Grammy EV: grammy_model.py.")
    json.dump(d, open(mpath, "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
