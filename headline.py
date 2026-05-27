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
    """Fetch today's sports headlines via Tavily free tier."""
    api_key = os.environ.get('TAVILY_API_KEY', '')
    if not api_key:
        return ''
    try:
        import requests
        resp = requests.post(
            'https://api.tavily.com/search',
            json={
                'api_key': api_key,
                'query': 'NBA NHL MLB tennis golf playoffs results scores today 2026',
                'search_depth': 'basic',
                'max_results': 6,
                'include_answer': False,
            },
            timeout=20,
        )
        resp.raise_for_status()
        results = resp.json().get('results', [])
        snippets = '\n'.join(
            f"- {r.get('title', '')}: {r.get('content', '')[:250]}"
            for r in results
            if r.get('title')
        )
        return snippets
    except Exception as e:
        print(f'  ⚠ Tavily search failed: {e}')
        return ''


def generate_headline(scores_data: dict, news_snippets: str) -> str | None:
    """Generate a fresh FL News ticker headline via Claude Haiku."""
    try:
        import anthropic
        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

        players = scores_data.get('players', [])
        standings = '\n'.join(
            f"  {p['place']}. {p['name']}: {p['total']} pts"
            for p in players
        )

        news_block = (
            f'\nRecent sports news (use these for real event references):\n{news_snippets}\n'
            if news_snippets else
            '\n(No live news available — invent plausible events based on the season.)\n'
        )

        prompt = f"""You write punchy multi-sentence "FL News" sports ticker headlines for Fantasy Life 2026 — a 13-person fantasy league where each player drafted real sports teams/athletes.

Draft picks (FL player → their team/pick):
{DRAFT_SUMMARY}
{news_block}
Rules:
- 3–5 sentences, max 60 words total
- This is a SPORTS NEWS ticker, not a scoreboard — never mention FL standings, point totals, or league positions
- Each sentence covers one sport/event; use real news if provided, otherwise invent plausible recent results
- Format: "Team (<em>FLPlayer</em>) result." — team/athlete name first, FL owner in <em> tags in parentheses
- Example: "Knicks (<em>Buckley</em>) sweep Cavaliers (<em>Jens</em>) into the NBA Finals."
- Use <em> tags ONLY around FL player names — never around team names or athlete names
- Be specific: include series scores (3-1), standings records, or stats where known
- Output ONLY the headline text, no quotes, no labels, no preamble

Headline:"""

        msg = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=200,
            messages=[{'role': 'user', 'content': prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        print(f'  ✗ generate_headline: {e}')
        return None


COST_PER_RUN_USD = 0.009   # Haiku ~200 tokens in + ~200 out ≈ $0.009
MIN_HOURS_BETWEEN_RUNS = 20  # never call the API more than once per ~day


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

    print('Generating FL News headline via Claude Haiku...')
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
