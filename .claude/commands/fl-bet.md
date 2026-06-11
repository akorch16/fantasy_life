# FL Bet

Add a new sportsbook bet. A bet lives in **two places with a matching id** —
this skill keeps them consistent.

## When to use

Run `/fl-bet <description>` to add a bet, e.g.
`/fl-bet Cubs finish ahead of Dodgers, closes July 1`.

(Retire this skill once player-created challenge bets ship.)

---

## Step 1 — Choose the id

Convention: `<event>-<playerA>-v-<playerB>`, lowercase. Event prefixes in use:
`nba-`, `nhl-`, `mlb-`, `mls-`, `nascar-`, `rg-` (Roland Garros, `-m-`/`-w-` for
men/women), `uso-` (US Open golf), `pts-` (season total points). Player names
are FL owners, not picks. Check it's unused:

```bash
grep -rn "<id>" docs/sportsbook.html projections.py
```

## Step 2 — Add to `BETS` in docs/sportsbook.html

```js
{
  id: 'mlb-jens-v-tim',
  sport: 'MLB · Standings',          // "Category · Context"
  title: 'Yankees (<em>Jens</em>) ahead of Cubs (<em>Tim</em>) on July 1',
  desc: 'One sentence of context: current standing, what YES means, the stakes.',
  odds: 54,                          // YES%, integer 1-99
  closes: 'Jul 1',
},
```

`<em>` tags go around FL player names only. `odds` is the YES probability —
the page derives NO as 100 − odds.

## Step 3 — Add to `_PROP_DEFS` in projections.py

```python
("mlb-jens-v-tim", 54, _mlb_h2h("Jens", "Tim"), "mlb-standings"),
```

Tuple: `(id, static_yes_pct, fn(odds)->int|None, source_category_label)`.
- The static % must match the `odds` in BETS (it's the fallback when the model can't compute).
- Pick the dynamic fn if one fits: `_mlb_h2h` / `_mls_h2h` (standings + normal
  approximation), `_pts_h2h` (Monte Carlo totals), or a `lambda o: _h2h(...)`
  over a Kalshi odds key. Use `None, None` only if no model backs it.

## Step 4 — Suggest odds honestly

If a dynamic fn exists, run `python3 projections.py` and read the computed YES%
from the log/output — use that (rounded) as the static odds too. Otherwise
estimate from current standings/Kalshi and say so in `desc`. Then
`git checkout -- docs/projections.json` before committing.

## Step 5 — Deploy

`/fl-merge`. The bet appears on the sportsbook page immediately; odds go live
on the next daily projections run.
