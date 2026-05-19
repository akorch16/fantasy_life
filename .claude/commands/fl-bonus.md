# FL Bonus Points

Add or update bonus points in `data/bonuses.json` for a Fantasy Life scoring event, then deploy to production.

## Invocation

Called with a plain-English description of the event, e.g.:
- `/fl-bonus Avalanche win Stanley Cup`
- `/fl-bonus Jon Rahm wins the Open Championship`
- `/fl-bonus UConn loses NBA Finals`
- `/fl-bonus Hurricanes advance to Stanley Cup Final`

If the input is ambiguous (unclear category, unclear milestone, or multiple picks could match), ask before writing.

---

## Draft Picks Reference

**NFL:** Tim=Seahawks, Wu=Ravens, Jens=Bills, Todd=49ers, Mitchell=Rams, Shep=Chiefs, Theo=Colts, Feder=Patriots, Fryar=Packers, Korch=Eagles, Molmen=Broncos, Jamzee=Lions, Buckley=Buccaneers

**NBA:** Tim=Nuggets, Wu=Spurs, Jens=Cavaliers, Todd=Timberwolves, Mitchell=Warriors, Shep=Celtics, Theo=Lakers, Feder=Thunder, Fryar=Clippers, Korch=Rockets, Molmen=Bucks, Jamzee=Magic, Buckley=Knicks

**MLB:** Tim=Cubs, Wu=Dodgers, Jens=Yankees, Todd=Braves, Mitchell=Phillies, Shep=Astros, Theo=Padres, Feder=Mets, Fryar=Guardians, Korch=Blue Jays, Molmen=Rangers, Jamzee=Mariners, Buckley=Brewers

**NHL:** Tim=Golden Knights, Wu=Devils, Jens=Maple Leafs, Todd=Panthers, Mitchell=Stars, Shep=Bruins, Theo=Red Wings, Feder=Capitals, Fryar=Lightning, Korch=Avalanche, Molmen=Rangers, Jamzee=Hurricanes, Buckley=Oilers

**NCAAF:** Tim=BYU, Wu=Miami, Jens=Georgia Tech, Todd=Ole Miss, Mitchell=Ohio State, Shep=Michigan, Theo=Georgia, Feder=Notre Dame, Fryar=Texas A&M, Korch=Indiana, Molmen=Texas Tech, Jamzee=Alabama, Buckley=Oregon

**NCAAB:** Tim=St. John's, Wu=Florida, Jens=Duke, Todd=UCLA, Mitchell=Alabama, Shep=Kansas, Theo=Houston, Feder=Kentucky, Fryar=UConn, Korch=Purdue, Molmen=North Carolina, Jamzee=Michigan, Buckley=Louisville

**Tennis:** Tim=Madison Keys, Wu=Coco Gauff, Jens=Jasmine Paolini, Todd=Carlos Alcaraz, Mitchell=Taylor Fritz, Shep=Novak Djokovic, Theo=Alexander Zverev, Feder=Iga Swiatek, Fryar=Aryna Sabalenka, Korch=Jessica Pegula, Molmen=Daniil Medvedev, Jamzee=Amanda Anisimova, Buckley=Jannik Sinner

**Golf:** Tim=Xander Schauffele, Wu=Scottie Scheffler, Jens=Russell Henley, Todd=Patrick Cantlay, Mitchell=J.J. Spaun, Shep=Jon Rahm, Theo=Justin Thomas, Feder=Bryson DeChambeau, Fryar=Viktor Hovland, Korch=Tommy Fleetwood, Molmen=Rory McIlroy, Jamzee=Ludvig Aberg, Buckley=Collin Morikawa

**NASCAR:** Tim=Bubba Wallace, Wu=Christopher Bell, Jens=Chase Briscoe, Todd=Chase Elliott, Mitchell=Shane van Gisbergen, Shep=Daniel Suarez, Theo=Denny Hamlin, Feder=Tyler Reddick, Fryar=Ryan Blaney, Korch=William Byron, Molmen=Kyle Larson, Jamzee=Joey Logano, Buckley=Ross Chastain

**MLS:** Tim=Charlotte FC, Wu=Minnesota United, Jens=San Diego FC, Todd=NY Red Bulls, Mitchell=Philadelphia Union, Shep=Orlando City, Theo=Inter Miami, Feder=Vancouver Whitecaps, Fryar=Columbus Crew, Korch=FC Cincinnati, Molmen=LA Galaxy, Jamzee=Seattle Sounders, Buckley=LAFC

**Actor:** Tim=Sean Penn, Wu=Wagner Moura, Jens=George Clooney, Todd=Leonardo DiCaprio, Mitchell=Pedro Pascal, Shep=Jeremy Allen White, Theo=Dwayne Johnson, Feder=Tom Holland, Fryar=Chris Hemsworth, Korch=Jon Bernthal, Molmen=Matt Damon, Jamzee=Timothée Chalamet, Buckley=Robert Pattinson

**Actress:** Tim=Ariana Grande, Wu=Zendaya, Jens=Amanda Seyfried, Todd=Teyana Taylor, Mitchell=Charlize Theron, Shep=Tessa Thompson, Theo=Sydney Sweeney, Feder=Cynthia Erivo, Fryar=Florence Pugh, Korch=Anne Hathaway, Molmen=Jessie Buckley, Jamzee=Emma Stone, Buckley=Anya Taylor-Joy

**Musician:** Tim=Kendrick Lamar, Wu=FKA Twigs, Jens=Sabrina Carpenter, Todd=Olivia Rodrigo, Mitchell=Bad Bunny, Shep=Drake, Theo=BTS, Feder=Lady Gaga, Fryar=Justin Bieber, Korch=SZA, Molmen=Taylor Swift, Jamzee=The Weeknd, Buckley=Beyoncé

**Stock:** Tim=COIN(L), Wu=LULU(L), Jens=SOFI(L), Todd=NVDA(L), Mitchell=CVNA(S), Shep=TSLA(S), Theo=CMG(L), Feder=PLTR(L), Fryar=AVGO(L), Korch=SMCI(L), Molmen=TTWO(L), Jamzee=INTC(L), Buckley=NEE(L)

**Country (GDP):** Tim=Netherlands, Wu=United States, Jens=Germany, Todd=Guinea, Mitchell=South Sudan, Shep=France, Theo=Switzerland, Feder=Brazil, Fryar=Norway, Korch=Guyana, Molmen=Argentina, Jamzee=Spain, Buckley=Canada

---

## Bonus Points Rules

### Sports Championships (NFL, NBA, NHL, MLB, NCAAF, NCAAB, MLS)

Milestone replacement model — each milestone **replaces** the previous total (not additive):

| Milestone | Bonus total | When awarded |
|---|---|---|
| `round16` | 2.5 | Won first round (of 16-team bracket) |
| `quarter` | 4.0 | Won second round / reached quarterfinals |
| `semi` | 6.5 | Won conference finals / reached Final Four |
| `runner_up` | 9.0 | Lost the championship game / finals |
| `champion` | 13.0 | Won the championship |

Example: A team currently at 4.0 (quarter) that wins their conference final → set to 6.5 (semi). Do not add 6.5 to 4.0.

### Golf

Additive per major event (Masters, US Open, The Open, PGA Championship):

| Event | Points |
|---|---|
| Major win | +6.0 |
| Major runner-up | +2.5 |

These stack across multiple majors in a season. New total = existing bonus + new event points.

### Tennis

Additive per Grand Slam (Australian Open, Roland Garros, Wimbledon, US Open):

| Event | Points |
|---|---|
| Men's major win | +4.0 |
| Men's major runner-up | +2.5 |
| Women's major win | +4.0 |
| Women's major runner-up | +2.5 |

### Actor / Actress (Oscars)

| Event | Points |
|---|---|
| Lead acting win | 13.0 total |
| Supporting acting win | 9.0 total |
| Lead acting nomination | 4.0 total |
| Supporting acting nomination | 2.5 total |

### Musician (Grammy)

Additive, capped at 13.0 total:

| Event | Points |
|---|---|
| Best Song / Album / Record | +7.0 |
| Other Grammy win | +3.0 |
| Any Grammy nomination | +1.0 |

### NASCAR

Season-end finishing position in Cup Series standings:

| Position | Bonus total |
|---|---|
| 1st | 13.0 |
| 2nd | 9.0 |
| 3rd | 6.5 |
| 4th | 4.0 |
| 5th | 2.5 |

### Country GDP

Top-5 GDP growth ranking at season end:

| Rank | Bonus total |
|---|---|
| 1st | 13.0 |
| 2nd | 9.0 |
| 3rd | 6.5 |
| 4th | 4.0 |
| 5th | 2.5 |

---

## Step 1 — Identify the update

From the input, determine:
- **Category** (NHL, Golf, Tennis, etc.)
- **Pick name** (team or person)
- **Owner** (league player from draft picks above)
- **Milestone** and the resulting **new total** from the rules above

For sports championships: read the current value for that player+category from `data/bonuses.json` to understand their current milestone, then set the new total.

For additive categories (Golf, Tennis, Grammy): read the current value and add the new event's points.

---

## Step 2 — Update bonuses.json

Read `data/bonuses.json`. Apply the change:
- If the category block already has an entry for this player, update it to the new total
- If the player has no entry yet in that category block, add one
- If the category block doesn't exist yet, create it

**Important**: values in this file are **final intended totals**, not per-event additions. The file overrides Supabase for any (category, player) pair present.

---

## Step 3 — Deploy to production

Create a hotfix branch, commit, push, PR, and squash merge:

```bash
DATE=$(date +%Y-%m-%d)
BRANCH="hotfix/bonus-$(echo '$DESCRIPTION' | tr ' ' '-' | tr '[:upper:]' '[:lower:]' | cut -c1-40)-${DATE}"
git fetch origin main
git checkout -b "${BRANCH}" origin/main
git add data/bonuses.json
git commit -m "bonus: <PLAYER> +<PTS> <category> (<pick> <event>)"
git push -u origin "${BRANCH}"
```

Then use `mcp__github__create_pull_request` (owner: `akorch16`, repo: `fantasy_life`, base: `main`) and immediately `mcp__github__merge_pull_request` with `squash` method.

Confirm the merged SHA and state the new bonus total clearly.
