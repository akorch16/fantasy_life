#!/usr/bin/env python3
"""
headline.py — Standalone FL News headline generator.
Uses Tavily free tier for live sports news + Anthropic Haiku for generation.
Cost: ~$0.009/run. Reads/writes docs/scores.json in-place.
"""
import json, os, sys
from pathlib import Path

DOCS_DIR = Path(__file__).parent / 'docs'
SCORES_PATH = DOCS_DIR / 'scores.json'

# Compact draft pick reference for the prompt
DRAFT_SUMMARY = """\
NBA: Tim=Nuggets, Wu=Spurs, Jens=Cavaliers, Todd=Timberwolves, Mitchell=Warriors,
     Shep=Celtics, Theo=Lakers, Feder=Thunder, Fryar=Clippers, Korch=Rockets,
     Molmen=Bucks, Jamzee=Magic, Buckley=Knicks
NHL: Tim=GoldenKnights, Wu=Devils, Jens=MapleLeafs, Todd=Panthers, Mitchell=Stars,
     Shep=Bruins, Theo=RedWings, Feder=Capitals, Fryar=Lightning, Korch=Avalanche,
     Molmen=Rangers, Jamzee=Hurricanes, Buckley=Oilers
MLB: Tim=Cubs, Wu=Dodgers, Jens=Yankees, Todd=Braves, Mitchell=Phillies, Shep=Astros,
     Theo=Padres, Feder=Mets, Fryar=Guardians, Korch=BlueJays, Molmen=Rangers,
     Jamzee=Mariners, Buckley=Brewers
Tennis: Tim=Keys, Wu=Gauff, Jens=Paolini, Todd=Alcaraz, Mitchell=Fritz, Shep=Djokovic,
        Theo=Zverev, Feder=Swiatek, Fryar=Sabalenka, Korch=Pegula, Molmen=Medvedev,
        Jamzee=Anisimova, Buckley=Sinner
Golf: Tim=Schauffele, Wu=Scheffler, Jens=Henley, Todd=Cantlay, Mitchell=Spaun,
      Shep=Rahm, Theo=JThomas, Feder=DeChambeau, Fryar=Hovland, Korch=Fleetwood,
      Molmen=McIlroy, Jamzee=Aberg, Buckley=Morikawa
Stock: Tim=COIN(L), Wu=LULU(L), Jens=SOFI(L), Todd=NVDA(L), Mitchell=CVNA(S),
       Shep=TSLA(S), Theo=CMG(L), Feder=PLTR(L), Fryar=AVGO(L), Korch=SMCI(L),
       Molmen=TTWO(L), Jamzee=INTC(L), Buckley=NEE(L)
Actress: Tim=Grande, Wu=Zendaya, Jens=Seyfried, Todd=TeyanaTaylor, Mitchell=Theron,
         Shep=Thompson, Theo=Sweeney, Feder=Erivo, Fryar=Pugh, Korch=Hathaway,
         Molmen=JessieBuckley, Jamzee=Stone, Buckley=TaylorJoy
Musician: Tim=Lamar, Wu=FKATwigs, Jens=Carpenter, Todd=Rodrigo, Mitchell=BadBunny,
          Shep=Drake, Theo=BTS, Feder=LadyGaga, Fryar=Bieber, Korch=SZA,
          Molmen=TaylorSwift, Jamzee=TheWeeknd, Buckley=Beyonce
NASCAR: Tim=Wallace, Wu=Bell, Jens=Briscoe, Todd=Elliott, Mitchell=VanGisbergen,
        Shep=Suarez, Theo=Hamlin, Feder=Reddick, Fryar=Blaney, Korch=Byron,
        Molmen=Larson, Jamzee=Logano, Buckley=Chastain
MLS: Tim=Charlotte, Wu=Minnesota, Jens=SanDiego, Todd=NYRedBulls, Mitchell=Philly,
     Shep=Orlando, Theo=InterMiami, Feder=Vancouver, Fryar=Columbus, Korch=Cincinnati,
     Molmen=LAGalaxy, Jamzee=Seattle, Buckley=LAFC"""


def search_news() -> str:
    """Fetch recent sports headlines via Tavily — 3 targeted searches, last 3 days only."""
    api_key = os.environ.get('TAVILY_API_KEY', '')
    if not api_key:
        return ''
    # Focused queries for active competitions only
    queries = [
        'NBA playoffs 2026 series results scores',
        'NHL playoffs 2026 series results scores',
        'Roland Garros French Open tennis 2026 results',
    ]
    try:
        import requests
        seen, all_snippets = set(), []
        for query in queries:
            resp = requests.post(
                'https://api.tavily.com/search',
                json={
                    'api_key': api_key,
                    'query': query,
                    'search_depth': 'basic',
                    'max_results': 3,
                    'include_answer': False,
                    'days': 3,
                },
                timeout=20,
            )
            resp.raise_for_status()
            for r in resp.json().get('results', []):
                title = r.get('title', '')
                if title and title not in seen:
                    seen.add(title)
                    all_snippets.append(f"- {title}: {r.get('content', '')[:300]}")
        return '\n'.join(all_snippets)
    except Exception as e:
        print(f'  ⚠ Tavily search failed: {e}')
        return ''


def generate_headline(scores_data: dict, news_snippets: str) -> str | None:
    """Generate a fresh FL News ticker headline via Claude Sonnet."""
    if not news_snippets:
        print('  – No snippets returned; skipping to avoid hallucination')
        return None
    try:
        import anthropic
        from datetime import date
        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

        today = date.today().strftime('%B %d, %Y')
        news_block = f'\nNews snippets from the last 3 days (today is {today}):\n{news_snippets}\n'

        prompt = f"""You write punchy multi-sentence "FL News" sports ticker headlines for Fantasy Life 2026 — a 13-person fantasy league where each player drafted real sports teams/athletes.

Draft picks (FL player → their team/pick):
{DRAFT_SUMMARY}
{news_block}
CRITICAL rules:
- ONLY report facts explicitly stated in the snippets above. Do NOT add any result, score, or outcome not written in a snippet.
- If a snippet mentions a team but doesn't clearly state the result, skip it.
- Never cross sports: an NBA team cannot win a Stanley Cup; an NHL team cannot win an NBA title.
- Only include events from the last 3 days (today is {today}).
- 3–5 sentences, max 60 words total
- This is a SPORTS NEWS ticker — never mention FL standings, point totals, or league positions
- Format: "Team (<em>FLPlayer</em>) result." — team/athlete name first, FL owner in <em> tags in parentheses
- Example: "Knicks (<em>Buckley</em>) sweep Cavaliers (<em>Jens</em>) into the NBA Finals."
- Use <em> tags ONLY around FL player names — never around team names or athlete names
- Be specific: include series scores (e.g. 3-1) only if the snippet gives them
- Output ONLY the headline text, no quotes, no labels, no preamble

Headline:"""

        msg = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=200,
            messages=[{'role': 'user', 'content': prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        print(f'  ✗ generate_headline: {e}')
        return None


COST_PER_RUN_USD = 0.04   # Sonnet ~1k tokens in + ~200 out ≈ $0.04
MIN_HOURS_BETWEEN_RUNS = 30  # scoring.py runs at 08:00; headline.yml runs at 07:00 next day (~23h gap)


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
    if not SCORES_PATH.exists():
        print(f'✗ {SCORES_PATH} not found — run scoring.py first')
        sys.exit(1)

    with open(SCORES_PATH) as f:
        data = json.load(f)

    # ── Dedup guard: never hit the API more than once per MIN_HOURS_BETWEEN_RUNS ──
    hours_ago = _hours_since_last_headline(data)
    if hours_ago < MIN_HOURS_BETWEEN_RUNS:
        print(f'⏭ Headline already generated {hours_ago:.1f}h ago — skipping API call (limit: {MIN_HOURS_BETWEEN_RUNS}h)')
        print(f'  Estimated cost avoided: ${COST_PER_RUN_USD:.3f}')
        sys.exit(0)

    print('Searching for today\'s sports news...')
    news = search_news()
    if news:
        print(f'  ✓ Got {len(news.splitlines())} snippets from Tavily')
    else:
        print('  – No Tavily key set or search skipped; generating without live news')

    print('Generating FL News headline via Claude Sonnet...')
    headline = generate_headline(data, news)
    if not headline:
        print('– Headline generation failed; existing headline unchanged')
        sys.exit(0)  # non-fatal — leaderboard still works without a new headline

    from datetime import datetime, timezone
    data['headline'] = headline
    data['headline_generated_at'] = datetime.now(timezone.utc).isoformat()
    with open(SCORES_PATH, 'w') as f:
        json.dump(data, f)

    print(f'✓ Headline updated (est. cost: ${COST_PER_RUN_USD:.3f}): {headline[:100]}')


if __name__ == '__main__':
    main()
