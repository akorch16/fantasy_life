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

        prompt = f"""You write punchy multi-sentence "FL News" ticker headlines for Fantasy Life 2026 — a 13-person fantasy league.

Draft picks (FL player → their team/pick):
{DRAFT_SUMMARY}

Current standings:
{standings}
{news_block}
Rules:
- 3–5 sentences, max 60 words total
- Each sentence = one sport/event; reference real news if provided
- Tie real-world events to FL players who own those teams/picks
- Use <em> tags ONLY around FL player names (Tim, Wu, Jens, Todd, etc.) — NOT around team or athlete names
- Be specific: scores, series leads, W/L records where known
- Output ONLY the headline text, no quotes, no labels

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


def main():
    if not SCORES_PATH.exists():
        print(f'✗ {SCORES_PATH} not found — run scoring.py first')
        sys.exit(1)

    with open(SCORES_PATH) as f:
        data = json.load(f)

    print('Searching for today\'s sports news...')
    news = search_news()
    if news:
        print(f'  ✓ Got {len(news.splitlines())} snippets from Tavily')
    else:
        print('  – No Tavily key set or search skipped; generating without live news')

    print('Generating FL News headline via Claude Haiku...')
    headline = generate_headline(data, news)
    if not headline:
        print('✗ Headline generation failed — keeping existing headline')
        sys.exit(1)

    data['headline'] = headline
    with open(SCORES_PATH, 'w') as f:
        json.dump(data, f)

    print(f'✓ Headline updated: {headline[:120]}')


if __name__ == '__main__':
    main()
