# FL Settle

Run the full "an event just finished" checklist: bonus points, sportsbook prop
settlement, fallback-odds pruning, headline refresh, deploy.

## When to use

Run `/fl-settle <event>` when a real-world event resolves (a playoff series, a
tennis/golf major, an award show). Example: `/fl-settle Hurricanes win Stanley Cup`.

---

## Step 0 — Identify what the event touches

From the event description, list:
1. **Bonus points** owed (championship 13 / runner-up 9 / semi 6.5 / major 4-6 — see `/fl-bonus` table and docs/rules.html)
2. **Sportsbook props** affected — search both definition sites:
   ```bash
   grep -n "id:" docs/sportsbook.html | grep -i "<sport-or-player>"
   grep -n "<sport>-" projections.py
   ```
3. **FALLBACK odds** in projections.py for the settled bracket/market

---

## Step 1 — Bonus points

Append entries to `data/bonuses.json` following the `/fl-bonus` skill (never
delete existing entries). Bonuses in this file override Supabase.

---

## Step 2 — Settle sportsbook props (four coordinated edits)

For each affected prop id (e.g. `nhl-fin-tim-v-jamzee`):

1. **`docs/sportsbook.html`** — in the `BETS` array: set the winning side's odds
   to 100, losing side to 0, add `settled: true`. The browser-side `settleBets()`
   pays out localStorage bets from this.
2. **`projections.py`** — move the prop's tuple out of `_PROP_DEFS` into
   `_PROP_DEFS_SETTLED` as `("<id>", 100)` with a comment naming the outcome.
   (If YES lost, pin it at `0`.)
3. **`data/sb_settled.json`** — append `{"id": "<prop-id>", "outcome": "yes"|"no"}`.
   The daily scoring run calls `db.settle_sb_bet()` for every entry here; it is
   idempotent (only touches rows with `settled_outcome IS NULL`), so leave old
   entries in place.
4. Verify the three ids match exactly — a typo means the bet never settles in Supabase.

---

## Step 3 — Prune FALLBACK odds

In `projections.py` `FALLBACK`:
- Pin the decided market: winner → `1.0`, drop losers (see the settled conf-finals entries for the pattern).
- Update any downstream-round odds the result changes (e.g. champion odds after a finals berth).
- **Bump `FALLBACK_AS_OF`** to today.

Run `python3 projections.py` locally and eyeball the prop odds table, then
`git checkout -- docs/projections.json` (Actions owns that file).

---

## Step 4 — Refresh the headline

```bash
python3 headline.py --force --dry-run   # preview
python3 headline.py --force             # write, if the preview looks right
```
Skip if no API keys available locally — the next scheduled run picks it up.

---

## Step 5 — Deploy

Run `/fl-merge`. After the merge, confirm the next daily Actions run settles the
Supabase bets (look for `settle_sb_bet` lines in the run log).
