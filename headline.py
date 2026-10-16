#!/usr/bin/env python3
"""
headline.py — Standalone FL News headline generator.
Uses Tavily free tier for live sports news + Anthropic Haiku for generation.
Cost: ~$0.009/run. Reads/writes docs/scores.json in-place.
"""
import json, os, sys
from typing import Optional
from pathlib import Path

DOCS_DIR = Path(__file__).parent / 'docs'
SCORES_PATH = DOCS_DIR / 'scores.json'

# Draft pick reference for the prompt, built from the canonical source.
# NFL/NCAAF/NCAAB excluded: frozen 2025 seasons, no live news to report.
from draft_picks_2026 import DRAFT_PICKS_2026

_HEADLINE_CATEGORIES = [
    'NBA', 'NHL', 'MLB', 'Tennis', 'Golf', 'NASCAR', 'MLS',
    'Stock', 'Actor', 'Actress', 'Musician', 'Country',
]

def _build_draft_summary() -> str:
    lines = []
    for cat in _HEADLINE_CATEGORIES:
        picks = DRAFT_PICKS_2026[cat]
        if cat == 'Stock':
            entries = [f"{p}={v['ticker']}({v['direction']})" for p, v in picks.items()]
        else:
            entries = [f"{p}={v.replace(' ', '').replace('.', '')}" for p, v in picks.items()]
        label = 'Country(FIFAWorldCup)' if cat == 'Country' else cat
        lines.append(f"{label}: " + ', '.join(entries))
    return '\n'.join(lines)

DRAFT_SUMMARY = _build_draft_summary()


# ── Event calendar ────────────────────────────────────────────────────────────
# (name, start, end, query). A query runs only while today is inside
# [start, end + RESULTS_GRACE_DAYS] — so event queries retire themselves and
# nobody has to hand-edit the list when a tournament ends. The same table
# drives the prompt: in-window events are announced as active, past events are
# explicitly listed as concluded/off-limits.
RESULTS_GRACE_DAYS = 2   # a final is still news for a couple of days

EVENT_WINDOWS = [
    ("French Open tennis",    "2026-05-24", "2026-06-07", "French Open Roland Garros 2026 tennis results today"),
    ("US Open golf",          "2026-06-18", "2026-06-21", "US Open golf championship 2026 final leaderboard"),
    ("World Cup group stage", "2026-06-11", "2026-06-27", "FIFA World Cup 2026 group stage results today"),
    ("World Cup knockout round","2026-06-28","2026-07-19", "FIFA World Cup 2026 knockout round match results today"),
    ("Wimbledon",             "2026-06-29", "2026-07-12", "Wimbledon 2026 tennis match results today"),
    ("The Open golf",         "2026-07-16", "2026-07-19", "The Open Championship 2026 golf leaderboard results"),
    ("US Open tennis",        "2026-08-31", "2026-09-13", "US Open 2026 tennis match results today"),
    ("NASCAR playoffs",       "2026-09-06", "2026-11-08", "NASCAR Cup Series playoffs 2026 race results"),
    ("MLB playoffs",          "2026-09-29", "2026-11-01", "MLB playoffs 2026 results"),
    ("MLS Cup playoffs",      "2026-10-21", "2026-12-06", "MLS Cup playoffs 2026 results"),
]

# Season-long categories — always searched (their pages update continuously).
ALWAYS_ON_QUERIES = [
    'MLB baseball results standings 2026 this week',
    'MLS NASCAR results 2026 this week',
    '{today} Billboard Hot 100 chart number one new entry this week',
    'NVDA TSLA COIN PLTR AVGO SMCI LULU INTC NEE stock movers this week 2026',
    '{today} domestic US box office opening weekend results North America',
]


def _parse_d(s):
    from datetime import date
    return date(*map(int, s.split('-')))


def _calendar_state(today):
    """(active, concluded, upcoming) event-window lists for the given date."""
    from datetime import timedelta
    active, concluded, upcoming = [], [], []
    for name, start, end, query in EVENT_WINDOWS:
        s, e = _parse_d(start), _parse_d(end)
        if s <= today <= e + timedelta(days=RESULTS_GRACE_DAYS):
            active.append((name, s, e, query))
        elif today > e:
            concluded.append((name, s, e))
        else:
            upcoming.append((name, s, e))
    return active, concluded, upcoming


def build_queries(today) -> list:
    """Date-aware query list: always-on categories + currently active events."""
    today_str = today.strftime('%B %d %Y')
    queries = [q.format(today=today_str) for q in ALWAYS_ON_QUERIES]
    active, _, _ = _calendar_state(today)
    queries.extend(q for _, _, _, q in active)
    return queries


def build_calendar_note(today) -> str:
    """Prompt guidance derived from the calendar — replaces hand-edited
    'the active events are X' lines that rot the moment an event ends."""
    active, concluded, _ = _calendar_state(today)
    lines = []
    if active:
        lines.append("Events IN PROGRESS right now (their fresh results are the priority): "
                     + "; ".join(f"{n} (through {e.strftime('%b %d')})" for n, s, e, _ in active))
    if concluded:
        lines.append("Events already CONCLUDED — do NOT report anything from these, their news is stale: "
                     + "; ".join(f"{n} (ended {e.strftime('%b %d')})" for n, s, e in concluded))
    lines.append("The NBA Finals and NHL Stanley Cup Finals concluded in mid-June 2026 — never report on them.")
    return "\n".join(f"- {l}" for l in lines)


MAX_SNIPPET_AGE_DAYS = 3


def search_news(debug: bool = False) -> str:
    """Fetch recent news via Tavily — separate query per active event so no
    category starves another. Queries come from the date-aware calendar.

    topic='news' is REQUIRED for Tavily to honor the `days` recency filter —
    without it the general index ranks evergreen pages (Wikipedia, 'Past
    Results' leaderboards) that made headlines cover weeks-old events.
    """
    from datetime import date, datetime, timedelta, timezone
    api_key = os.environ.get('TAVILY_API_KEY', '')
    if not api_key:
        return ''
    today = date.today()
    queries = build_queries(today)
    cutoff = today - timedelta(days=MAX_SNIPPET_AGE_DAYS)
    try:
        import requests
        seen, all_snippets, dropped = set(), [], 0
        for query in queries:
            resp = requests.post(
                'https://api.tavily.com/search',
                json={
                    'api_key': api_key,
                    'query': query,
                    'topic': 'news',
                    'days': MAX_SNIPPET_AGE_DAYS,
                    'search_depth': 'basic',
                    'max_results': 3,
                    'include_answer': False,
                },
                timeout=20,
            )
            resp.raise_for_status()
            results = resp.json().get('results', [])
            if debug:
                print(f'\n  [QUERY] {query}')
            for r in results:
                title = r.get('title', '')
                content = r.get('content', '')
                if not title or title in seen:
                    continue
                seen.add(title)
                # Hard-drop anything published before the cutoff; stamp the
                # date into the snippet so Claude can judge freshness too.
                pub = (r.get('published_date') or '').strip()
                pub_label = 'date unknown'
                if pub:
                    try:
                        pub_day = datetime.fromisoformat(
                            pub.replace('Z', '+00:00')).astimezone(timezone.utc).date()
                    except ValueError:
                        try:
                            pub_day = datetime.strptime(pub[:16], '%a, %d %b %Y').date()
                        except ValueError:
                            pub_day = None
                    if pub_day:
                        if pub_day < cutoff:
                            dropped += 1
                            if debug:
                                print(f'    ✗ dropped (published {pub_day}): {title}')
                            continue
                        pub_label = f'published {pub_day.isoformat()}'
                snippet = f"- [{pub_label}] {title}: {content[:300]}"
                all_snippets.append(snippet)
                if debug:
                    print(f'    → [{pub_label}] {title}')
                    print(f'       {content[:200]}')
        if dropped:
            print(f'  ℹ dropped {dropped} snippet(s) older than {MAX_SNIPPET_AGE_DAYS} days')
        return '\n'.join(all_snippets)
    except Exception as e:
        print(f'  ⚠ Tavily search failed: {e}')
        return ''


def mlb_official_snippets(today=None) -> str:
    """Snippet-style lines for MLB postseason series, from MLB's own StatsAPI.

    News search can't be trusted for series state: bracket/tracker pages are
    re-dated daily but list every round since the Wild Card, and the newest
    recap may not be indexed yet. StatsAPI is exact. Only series with a game
    played within MAX_SNIPPET_AGE_DAYS (or still in progress) are reported.
    Returns '' on any failure so headline generation degrades to news-only.
    """
    try:
        import requests
        from datetime import date, timedelta
        today = today or date.today()
        resp = requests.get(
            'https://statsapi.mlb.com/api/v1/schedule',
            params={'sportId': 1, 'gameType': 'D,L,W',
                    'startDate': (today - timedelta(days=14)).isoformat(),
                    'endDate': (today + timedelta(days=1)).isoformat(),
                    'hydrate': 'team'},
            timeout=20)
        resp.raise_for_status()
        series = {}
        for day in resp.json().get('dates', []):
            for g in day.get('games', []):
                a, h = g['teams']['away'], g['teams']['home']
                names = tuple(sorted([a['team']['name'], h['team']['name']]))
                s = series.setdefault((g.get('seriesDescription', ''), names),
                                      {'wins': dict.fromkeys(names, 0), 'last': None,
                                       'upcoming': False, 'total': g.get('gamesInSeries')})
                if g['status']['detailedState'] == 'Final' and a.get('score') is not None:
                    winner = a if a['score'] > h['score'] else h
                    s['wins'][winner['team']['name']] += 1
                    s['last'] = (day['date'], g.get('seriesGameNumber'), a, h)
                elif g['status']['detailedState'] != 'Final':
                    s['upcoming'] = True
        cutoff = today - timedelta(days=MAX_SNIPPET_AGE_DAYS)
        lines = []
        for (desc, names), s in sorted(series.items(), key=lambda kv: kv[1]['last'][0] if kv[1]['last'] else ''):
            if not s['last']:
                continue
            last_day, game_no, a, h = s['last']
            if date.fromisoformat(last_day) < cutoff:
                continue
            (t1, w1), (t2, w2) = sorted(s['wins'].items(), key=lambda kv: -kv[1])
            need = ((s['total'] or 7) // 2) + 1
            score = f"Game {game_no}: {a['team']['name']} {a['score']}, {h['team']['name']} {h['score']}"
            if w1 >= need:
                lines.append(f"- [official MLB data, {last_day}] {desc} FINAL: {t1} beat {t2} {w1}-{w2} "
                             f"and advance ({score}, {last_day}).")
            elif w1 == w2:
                lines.append(f"- [official MLB data, {last_day}] {desc} in progress: {t1} and {t2} tied {w1}-{w2} "
                             f"({score}, {last_day}).")
            else:
                lines.append(f"- [official MLB data, {last_day}] {desc} in progress: {t1} lead {t2} {w1}-{w2} "
                             f"({score}, {last_day}).")
        return "\n".join(lines)
    except Exception as e:
        print(f'  ⚠ MLB StatsAPI facts unavailable: {e}')
        return ''


_OWNERS = ('Tim', 'Wu', 'Jens', 'Todd', 'Mitchell', 'Shep', 'Theo', 'Feder',
           'Fryar', 'Korch', 'Molmen', 'Jamzee', 'Buckley')


def _owner_pick_words() -> dict:
    """{owner: set of lowercase words (>=3 chars) from all of their picks}."""
    import re
    words = {o: set() for o in _OWNERS}
    for cat, picks in DRAFT_PICKS_2026.items():
        for owner, pick in picks.items():
            if owner not in words:
                continue
            text = pick.get('ticker', '') if isinstance(pick, dict) else str(pick)
            words[owner].update(w for w in re.findall(r"[a-z0-9.]+", text.lower()) if len(w) >= 3)
    return words


def check_headline(headline: str) -> list:
    """Problems that mean the headline mis-attributes a pick to an owner."""
    import re
    problems = []
    words = _owner_pick_words()
    for m in re.finditer(r"\b(" + "|".join(_OWNERS) + r")'s\b", headline):
        problems.append(f"possessive '{m.group(0)}' — write 'Pick (<em>Owner</em>)' and only for picks that owner holds")
    for m in re.finditer(r"([A-Za-z0-9.&' -]{2,40}?)\s*\(<em>(\w+)</em>\)", headline):
        phrase, owner = m.group(1), m.group(2)
        if owner not in words:
            problems.append(f"'{owner}' is not an FL player")
            continue
        tokens = [w for w in re.findall(r"[a-z0-9.]+", phrase.lower()) if len(w) >= 3][-3:]
        if not any(t in words[owner] for t in tokens):
            problems.append(f"'{phrase.strip()}' is not one of {owner}'s picks")
    return problems


def generate_headline(scores_data: dict, news_snippets: str) -> Optional[str]:
    """Generate a fresh FL News ticker headline via Claude Sonnet."""
    if not news_snippets:
        print('  – No snippets returned; skipping to avoid hallucination')
        return None
    try:
        import anthropic
        from datetime import date
        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

        today_d = date.today()
        today = today_d.strftime('%B %d, %Y')
        calendar_note = build_calendar_note(today_d)
        news_block = f'\nNews snippets from the last {MAX_SNIPPET_AGE_DAYS} days (today is {today}):\n{news_snippets}\n'

        prompt = f"""You write punchy multi-sentence "FL News" ticker headlines for Fantasy Life 2026 — a 13-person fantasy league where each player drafted real sports teams, athletes, musicians, actors, and stocks.

Draft picks (FL player → their pick) — cover ALL categories, not just sports:
{DRAFT_SUMMARY}
{news_block}
CRITICAL rules:
- SCHEDULE vs RESULT: A snippet row showing two team records (e.g. "1-0-0" and "0-1-0") alongside a clock time ("12:00 PM", "3:00 PM ET", etc.) is a SCHEDULED game that has NOT been played yet. Do NOT report it as a completed result. A completed match has a plain scoreline with no kickoff time, or the snippet explicitly says "final" / "full-time" / "FT" / "FT:".
- TABLE WITHOUT DATA: If a snippet contains only table column headers (e.g. "| RK | DRIVER | POINTS | WINS |") but no data row naming the specific driver/player, do NOT report any statistic for that driver. Skip the story entirely.
- TRUNCATED TEXT: Snippets that end with "..." are cut off mid-sentence. Do NOT infer, complete, or extend what follows the "...". Only use text that is explicitly present before the cutoff point.
- CITATION CHECK: Before writing each sentence, confirm the exact fact (score, number, outcome, opponent name) appears verbatim in one of the snippets above. If you cannot point to where it appears word-for-word, omit it.
- PREVIEW PAGES ARE NOT RESULTS: snippets with "predictions", "preview", "odds", "how to watch", "schedule", or phrasing like "X faces Y" / "X and Y meet" / "looking to" describe an UPCOMING match. Never turn one into a result — a win/advance/elimination claim requires the snippet to explicitly state it happened ("beats", "defeated", "advances", "eliminated", a final scoreline). If no snippet states the outcome of a match, do not mention that match at all.
- ONLY report facts explicitly stated in the snippets above. Do NOT add any result, score, or outcome not written in a snippet.
- OFFICIAL MLB DATA: lines tagged "[official MLB data, ...]" come straight from MLB and are authoritative for MLB postseason series state. If a news snippet disagrees with them (e.g. an older series score), the official line wins. Never report an MLB series result that is older than the newest official line for that series.
- BRACKET / TRACKER / STANDINGS PAGES list results from EVERY earlier round, so their publication date says nothing about when a result happened. Never take a game result from such a page (e.g. "Rays 4, Yankees 3 (Tampa Bay wins 3-0)" or a Wild Card score) unless an official MLB data line or a dated article confirms it happened within the last {MAX_SNIPPET_AGE_DAYS} days. A series that has already ended and is not on an official line is OLD — skip it.
- OWNERSHIP: only the picks listed above have an FL owner. A team, player or ticker that is not in the list has NO owner — never attach an FL player to it, and never write possessives like "Fryar's Rays". Write only "Pick (<em>Owner</em>)" using the exact pick/owner pairs listed above, and mention opponents without an owner as plain names.
- If a snippet mentions a pick but doesn't clearly state the result or move, skip it.
- For ongoing series (NBA Finals, NHL Finals, etc.), always report the MOST RECENT game — if snippets mention multiple games, use the highest game number.
- Never cross categories: an NBA team cannot win a Stanley Cup; a stock ticker is not a song chart.
- The EVENT itself must have occurred within the last {MAX_SNIPPET_AGE_DAYS} days (today is {today}). A recent article referencing an older event (e.g. "biggest opening of the year" for a film that opened weeks ago) does NOT qualify — skip it.
- Each snippet starts with its publication date in brackets. Prefer the most recently published snippets. A snippet marked [date unknown] may be an evergreen page — treat any result on it as suspect unless the snippet text itself dates the event within the last {MAX_SNIPPET_AGE_DAYS} days.
- For Actor/Actress/Musician: only report if the film opened or the song charted within the last {MAX_SNIPPET_AGE_DAYS} days. Do NOT report on releases from weeks or months ago even if a recent article mentions them.
- 3–5 sentences, max 60 words total
- Never mention FL standings, point totals, or league positions
- Event status (derived from the league calendar — trust this over any snippet):
{calendar_note}
- Cover a MIX of categories — aim for at least 2 different categories (e.g. one sports + one music/stock/movie/WorldCup)
- Format: "Pick (<em>FLPlayer</em>) result." — pick name first, FL owner in <em> tags in parentheses
- Examples: "Knicks (<em>Buckley</em>) sweep Cavaliers (<em>Jens</em>) into the NBA Finals." / "NVDA (<em>Todd</em>) surges 9% on earnings." / "USA (<em>Wu</em>) blank Morocco 2-0 in World Cup opener." / "Taylor Swift (<em>Molmen</em>) hits #1 with new single."
- Use <em> tags ONLY around FL player names — never around pick names
- Be specific: include series scores or % moves only if the snippet gives them
- Actor/Actress: ONLY write a sentence about a film if a snippet explicitly names the film title AND at least one FL pick actor/actress in the same sentence or tight clause. Once a film is confirmed by a snippet, you MAY use your knowledge of the film's cast to also credit other FL picks who are in that film — but only if you are highly confident they appear in it. Do not invent casting. If unsure, stick to only the actors named in the snippet.
- Output format — TWO sections, exactly like this, and NOTHING else. Do not
  write any preamble, reasoning, or "let me check the snippets" narration —
  your response must start immediately with the literal text "FACTS:".
  Keep each FACTS line to one short sentence — at most 6 facts total.

FACTS:
1. quote: "<exact text copied verbatim from a snippet>" → <the fact it supports>
2. quote: "..." → ...

HEADLINE:
<the headline sentences>

Every headline sentence MUST be backed by a numbered FACTS entry whose quote is copied character-for-character from a snippet above. If you cannot produce the verbatim quote for a fact, it does not go in the headline. The HEADLINE section must contain only the headline text."""

        import re
        feedback = ''
        for attempt in (1, 2):
            msg = client.messages.create(
                model='claude-sonnet-4-6',
                max_tokens=1200,
                # anthropic-python 1.x dropped temperature as a typed create() param
                # (requirements.txt pins anthropic>=0.25 with no upper bound, so CI
                # picked up the new major version) — extra_body still passes it
                # through to the underlying Messages API, which is unchanged.
                extra_body={'temperature': 0},
                messages=[{'role': 'user', 'content': prompt + feedback}],
            )
            raw = msg.content[0].text.strip()
            # Truncation safety: if the model ran out of tokens before finishing,
            # never publish whatever partial/reasoning text it had written so far
            # (this shipped a raw chain-of-thought fragment to prod on 2026-07-17
            # when 'HEADLINE:' hadn't been reached yet and the old code fell back
            # to treating the entire raw response as the headline).
            if msg.stop_reason == 'max_tokens':
                print(f'  ✗ generate_headline: response truncated at max_tokens — skipping. '
                      f'Raw tail: {raw[-300:]!r}')
                return None
            if 'HEADLINE:' not in raw:
                print(f'  ✗ generate_headline: no HEADLINE: section in response — skipping. '
                      f'Raw: {raw[:300]!r}')
                return None
            facts, headline = raw.split('HEADLINE:', 1)
            print('  Grounding facts:\n' + '\n'.join(
                f'    {l}' for l in facts.replace('FACTS:', '').strip().splitlines() if l.strip()))
            headline = headline.strip()
            if not headline:
                print('  ✗ generate_headline: empty headline after HEADLINE: — skipping')
                return None
            # Normalize markdown emphasis the model occasionally emits (*Wu*) back
            # to the <em> tags the ticker expects.
            headline = re.sub(r'\*([A-Za-z]+)\*', r'<em>\1</em>', headline)
            problems = check_headline(headline)
            if not problems:
                return headline
            print(f'  ⚠ attempt {attempt}: owner/pick check failed: ' + '; '.join(problems))
            feedback = ('\n\nYour previous headline was rejected for mis-attributing picks:\n- '
                        + '\n- '.join(problems)
                        + '\nWrite the FACTS and HEADLINE sections again, fixing every problem. '
                          'Mention unowned teams as plain names.')
        print('  ✗ generate_headline: owner/pick check failed twice — skipping')
        return None
    except Exception as e:
        print(f'  ✗ generate_headline: {e}')
        return None


COST_PER_RUN_USD = 0.04   # Sonnet ~1k tokens in + ~200 out ≈ $0.04
MIN_HOURS_BETWEEN_RUNS = 20  # once per day; 20h (not 24h) to handle GitHub Actions scheduling drift


def _hours_since_last_headline(data: dict) -> float:
    """Return hours since the last headline was generated, or infinity if unknown."""
    ts = data.get('headline_generated_at')
    if not ts:
        return float('inf')
    try:
        from datetime import datetime, timezone
        last = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return (datetime.now(timezone.utc) - last).total_seconds() / 3600
    except Exception:
        return float('inf')


def main():
    debug   = '--debug'    in sys.argv
    dry_run = '--dry-run'  in sys.argv
    force   = '--force'    in sys.argv  # skip the 24h dedup guard

    if not SCORES_PATH.exists():
        print(f'✗ {SCORES_PATH} not found — run scoring.py first')
        sys.exit(1)

    with open(SCORES_PATH) as f:
        data = json.load(f)

    # ── Dedup guard: never hit the API more than once per MIN_HOURS_BETWEEN_RUNS ──
    hours_ago = _hours_since_last_headline(data)
    if hours_ago < MIN_HOURS_BETWEEN_RUNS and not force and not dry_run:
        print(f'⏭ Headline already generated {hours_ago:.1f}h ago — skipping API call (limit: {MIN_HOURS_BETWEEN_RUNS}h)')
        print(f'  Estimated cost avoided: ${COST_PER_RUN_USD:.3f}')
        print(f'  Use --force to override.')
        sys.exit(0)

    print('Searching for today\'s sports news...')
    news = search_news(debug=debug)
    mlb = mlb_official_snippets()
    if mlb:
        print('\n  ✓ Official MLB postseason data:\n' + '\n'.join(f'    {l[:160]}' for l in mlb.splitlines()))
        news = mlb + ('\n' + news if news else '')
    if news:
        print(f'\n  ✓ Got {len(news.splitlines())} snippets from Tavily')
        if not debug:
            # brief summary — show just titles so CI logs are useful
            for line in news.splitlines():
                print(f'    {line[:120]}')
    else:
        print('  – No Tavily key set or search skipped; generating without live news')

    if dry_run:
        print('\n[--dry-run] Generating headline (will NOT write to scores.json)...')
    else:
        print('\nGenerating FL News headline via Claude Sonnet...')

    headline = generate_headline(data, news)
    if not headline:
        print('– Headline generation failed; existing headline unchanged')
        sys.exit(0)

    print(f'\n  Full headline:\n  {headline}')

    if dry_run:
        print(f'\n[--dry-run] Would write headline above. scores.json unchanged.')
        sys.exit(0)

    from datetime import datetime, timezone
    data['headline'] = headline
    data['headline_generated_at'] = datetime.now(timezone.utc).isoformat()
    with open(SCORES_PATH, 'w') as f:
        json.dump(data, f)

    print(f'\n✓ Headline updated (est. cost: ${COST_PER_RUN_USD:.3f})')


if __name__ == '__main__':
    main()
