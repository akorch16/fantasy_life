"""Settlement rule evaluators that don't come from Kalshi markets.

Each evaluator takes the rule tuple from projections._AUTO_SETTLE_RULES and
returns 'yes' | 'no' | 'push', or None when the bet can't be decided yet (the
bet then stays open and the overdue-settlement issue covers it).
"""
import datetime
import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
SCORES_PATH = os.path.join(_HERE, "docs", "scores.json")
_UTC = datetime.timezone.utc


def _parse_iso_z(ts):
    return datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_UTC)


# ── Leaderboard snapshot comparison ───────────────────────────────────────────

def score_cmp(rule, scores_doc=None):
    """("score_cmp", metric, owner_a, owner_b, window_start, window_end)

    Compares two owners on the leaderboard. metric is "total" (FL total points)
    or a category key such as "mls" (that category's raw_value). Decides only if
    docs/scores.json was generated inside [window_start, window_end), so the
    snapshot is the run the bet names rather than whatever "latest" is. For a
    category metric the category's data must also be non-stale. A > B -> yes,
    A < B -> no, equal -> push.
    """
    _, metric, owner_a, owner_b, start, end = rule
    doc = scores_doc
    if doc is None:
        try:
            with open(SCORES_PATH) as f:
                doc = json.load(f)
        except Exception:
            return None
    try:
        generated = datetime.datetime.strptime(
            doc["last_updated"], "%Y-%m-%d %H:%M UTC").replace(tzinfo=_UTC)
    except Exception:
        return None
    if not (_parse_iso_z(start) <= generated < _parse_iso_z(end)):
        return None

    if metric != "total" and doc.get("data_freshness", {}).get(metric, {}).get("stale", True):
        print(f"  ⏸ score_cmp {owner_a} v {owner_b}: {metric} data is stale — not auto-settling")
        return None

    def value(owner):
        for p in doc.get("players", []):
            if p.get("name") == owner:
                if metric == "total":
                    return p.get("total")
                return (p.get("categories", {}).get(metric) or {}).get("raw_value")
        return None

    a, b = value(owner_a), value(owner_b)
    if a is None or b is None:
        return None
    print(f"  📊 score_cmp {metric}: {owner_a}={a} vs {owner_b}={b} (leaderboard {doc['last_updated']})")
    if a == b:
        return "push"
    return "yes" if a > b else "no"


# ── Series winner via Tavily search + Claude extraction ───────────────────────

_CLAUDE_MODEL = "claude-sonnet-4-6"


def _tavily_search(query, api_key):
    import requests
    resp = requests.post(
        "https://api.tavily.com/search",
        json={"api_key": api_key, "query": query, "topic": "news", "days": 7,
              "search_depth": "basic", "max_results": 6, "include_answer": False},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def _claude_json(prompt):
    import anthropic
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    msg = client.messages.create(
        model=_CLAUDE_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return json.loads(text)


def _norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def tavily_series(rule, now=None, search=None, extract=None):
    """("tavily_series", label, yes_team, other_team, eligible_after)

    yes_team winning the series settles the bet YES, other_team NO. Only runs
    after eligible_after (the earliest the series could end). Claude reads Tavily
    news snippets and must return {"series_over", "winner", "evidence"}; the
    result is accepted only if the series is over, the winner is one of the two
    teams, and the evidence quote appears verbatim in the snippets and names the
    winner. Anything else leaves the bet open.
    """
    _, label, yes_team, other_team, eligible_after = rule
    now = now or datetime.datetime.now(_UTC)
    if now < _parse_iso_z(eligible_after):
        return None
    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if search is None and (not tavily_key or not os.environ.get("ANTHROPIC_API_KEY")):
        print(f"  ⏸ tavily_series {label}: TAVILY_API_KEY/ANTHROPIC_API_KEY not set — skipping")
        return None
    search = search or (lambda q: _tavily_search(q, tavily_key))
    extract = extract or _claude_json

    try:
        results = search(f"{yes_team} {other_team} {label} 2026 final result series winner advances")
    except Exception as e:
        print(f"  ⚠ tavily_series {label}: search failed ({e})")
        return None
    snippets = "\n".join(
        f"- [{r.get('published_date') or 'date unknown'}] {r.get('title', '')}: {r.get('content', '')[:500]}"
        for r in results if r.get("title"))
    if not snippets:
        return None

    prompt = (
        f"From ONLY the news snippets below, determine whether the 2026 {label} between "
        f"the {yes_team} and the {other_team} has finished, and who won it.\n"
        "Respond with JSON only: "
        '{"series_over": true|false, "winner": "<exactly one of: '
        f'{yes_team} | {other_team} | null>", "evidence": "<a verbatim quote of at most 200 '
        'characters from the snippets that states the series result>"}\n'
        "Say series_over=false if any snippet shows the series still in progress or the "
        "snippets don't clearly state the final result. Do not use outside knowledge.\n\n"
        f"Snippets:\n{snippets}"
    )
    try:
        out = extract(prompt)
    except Exception as e:
        print(f"  ⚠ tavily_series {label}: extraction failed ({e})")
        return None

    winner = out.get("winner")
    evidence = out.get("evidence") or ""
    if not out.get("series_over") or winner not in (yes_team, other_team):
        return None
    if not evidence or _norm(evidence) not in _norm(snippets):
        print(f"  ⚠ tavily_series {label}: evidence not found verbatim in snippets — rejecting")
        return None
    if winner.split()[-1].lower() not in evidence.lower():
        print(f"  ⚠ tavily_series {label}: evidence doesn't name {winner} — rejecting")
        return None
    # Second, independent read of ONLY the quote. A quote naming both teams
    # ("Dodgers beat Brewers") would pass the checks above even if the first
    # answer had the winner backwards, so the two reads must agree.
    try:
        check = extract(
            f'Quote: "{evidence}"\n'
            f"According to this quote alone, which team won the 2026 {label}: "
            f"{yes_team} or {other_team}? Respond with JSON only: "
            f'{{"winner": "<{yes_team} | {other_team} | null>"}}')
    except Exception as e:
        print(f"  ⚠ tavily_series {label}: verification read failed ({e})")
        return None
    if check.get("winner") != winner:
        print(f"  ⚠ tavily_series {label}: verification read disagrees "
              f"({check.get('winner')!r} vs {winner!r}) — rejecting")
        return None
    print(f"  🔎 tavily_series {label}: {winner} won — \"{evidence}\"")
    return "yes" if winner == yes_team else "no"
