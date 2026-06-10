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
NASCAR: Tim=Wallace, Wu=Bell, Jens=Briscoe, Todd=Elliott, Mitchell=VanGisbergen,
        Shep=Suarez, Theo=Hamlin, Feder=Reddick, Fryar=Blaney, Korch=Byron,
        Molmen=Larson, Jamzee=Logano, Buckley=Chastain
MLS: Tim=Charlotte, Wu=Minnesota, Jens=SanDiego, Todd=NYRedBulls, Mitchell=Philly,
     Shep=Orlando, Theo=InterMiami, Feder=Vancouver, Fryar=Columbus, Korch=Cincinnati,
     Molmen=LAGalaxy, Jamzee=Seattle, Buckley=LAFC
Stock: Tim=COIN(L), Wu=LULU(L), Jens=SOFI(L), Todd=NVDA(L), Mitchell=CVNA(S),
       Shep=TSLA(S), Theo=CMG(L), Feder=PLTR(L), Fryar=AVGO(L), Korch=SMCI(L),
       Molmen=TTWO(L), Jamzee=INTC(L), Buckley=NEE(L)
Actor: Tim=SeanPenn, Wu=WagnerMoura, Jens=Clooney, Todd=DiCaprio, Mitchell=PedroPascal,
       Shep=JeremyAllenWhite, Theo=DwayneJohnson, Feder=TomHolland, Fryar=Hemsworth,
       Korch=JonBernthal, Molmen=MattDamon, Jamzee=Chalamet, Buckley=Pattinson
Actress: Tim=ArianaGrande, Wu=Zendaya, Jens=Seyfried, Todd=TeyanaTaylor, Mitchell=Theron,
         Shep=TessaThompson, Theo=SydneySweeney, Feder=CynthiaErivo, Fryar=FlorencePugh,
         Korch=AnneHathaway, Molmen=JessieBuckley, Jamzee=EmmaStone, Buckley=AnyaTaylorJoy
Musician: Tim=KendrickLamar, Wu=FKATwigs, Jens=SabrinaCarpenter, Todd=OliviaRodrigo,
          Mitchell=BadBunny, Shep=Drake, Theo=BTS, Feder=LadyGaga, Fryar=JustinBieber,
          Korch=SZA, Molmen=TaylorSwift, Jamzee=TheWeeknd, Buckley=Beyonce
Country(FIFAWorldCup): Tim=Netherlands, Wu=USA, Jens=Germany, Todd=Guinea, Mitchell=SouthSudan,
                       Shep=France, Theo=Switzerland, Feder=Brazil, Fryar=Norway, Korch=Guyana,
                       Molmen=Argentina, Jamzee=Spain, Buckley=Canada"""


def search_news(debug: bool = False) -> str:
    """Fetch recent news via Tavily — separate query per active event so no category starves another."""
    api_key = os.environ.get('TAVILY_API_KEY', '')
    if not api_key:
        return ''
    queries = [
        # ── Active playoff series get their own slot ──────────────────────
        'NBA Finals 2026 most recent game score result last night',
        'NHL Stanley Cup Finals 2026 most recent game score result last night',
        # ── Other sports ──────────────────────────────────────────────────
        'Roland Garros French Open tennis 2026 results',
        'US Open golf 2026 results leaderboard',
        'MLB MLS NASCAR standings results 2026',
        # ── FIFA World Cup ────────────────────────────────────────────────
        'FIFA World Cup 2026 results group stage standings',
        # ── Music (recent chart moves only) ──────────────────────────────
        'Billboard Hot 100 number one song this week 2026',
        # ── Stocks ───────────────────────────────────────────────────────
        'NVDA TSLA COIN PLTR AVGO SMCI LULU INTC NEE stock market 2026',
        # ── Movies: recent box office, NOT celebrity gossip ───────────────
        'box office results opening weekend June 2026',
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
            results = resp.json().get('results', [])
            if debug:
                print(f'\n  [QUERY] {query}')
            for r in results:
                title = r.get('title', '')
                content = r.get('content', '')
                if title and title not in seen:
                    seen.add(title)
                    snippet = f"- {title}: {content[:300]}"
                    all_snippets.append(snippet)
                    if debug:
                        print(f'    → {title}')
                        print(f'       {content[:200]}')
        return '\n'.join(all_snippets)
    except Exception as e:
        print(f'  ⚠ Tavily search failed: {e}')
        return ''


def generate_headline(scores_data: dict, news_snippets: str) -> Optional[str]:
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

        prompt = f"""You write punchy multi-sentence "FL News" ticker headlines for Fantasy Life 2026 — a 13-person fantasy league where each player drafted real sports teams, athletes, musicians, actors, and stocks.

Draft picks (FL player → their pick) — cover ALL categories, not just sports:
{DRAFT_SUMMARY}
{news_block}
CRITICAL rules:
- ONLY report facts explicitly stated in the snippets above. Do NOT add any result, score, or outcome not written in a snippet.
- If a snippet mentions a pick but doesn't clearly state the result or move, skip it.
- For ongoing series (NBA Finals, NHL Finals, etc.), always report the MOST RECENT game — if snippets mention multiple games, use the highest game number.
- Never cross categories: an NBA team cannot win a Stanley Cup; a stock ticker is not a song chart.
- Only include events from the last 3 days (today is {today}).
- 3–5 sentences, max 60 words total
- Never mention FL standings, point totals, or league positions
- If snippets contain results for BOTH NBA Finals and NHL Stanley Cup Finals, include a sentence for each — never drop an active Finals series
- Cover a MIX of categories — aim for at least 2 different categories (e.g. one sports + one music/stock/movie/WorldCup)
- Format: "Pick (<em>FLPlayer</em>) result." — pick name first, FL owner in <em> tags in parentheses
- Examples: "Knicks (<em>Buckley</em>) sweep Cavaliers (<em>Jens</em>) into the NBA Finals." / "NVDA (<em>Todd</em>) surges 9% on earnings." / "USA (<em>Wu</em>) blank Morocco 2-0 in World Cup opener." / "Taylor Swift (<em>Molmen</em>) hits #1 with new single."
- Use <em> tags ONLY around FL player names — never around pick names
- Be specific: include series scores or % moves only if the snippet gives them
- Actor/Actress: ONLY connect a film to an FL player's pick if the snippet explicitly names that actor/actress by name in the film. A film title alone is never enough — do NOT use outside knowledge about casting.
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
