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

## Step 2 — Settle sportsbook props (ONE file)

`data/sb_settled.json` is the single source of truth for settlement. For each
affected prop id, append:

```json
{"id": "<prop-id>", "outcome": "yes"|"no"|"push"}
```

That's it. Everything downstream is automatic:
- The **hourly odds workflow** (`odds.yml`) and the daily run both call
  `db.settle_sb_bet()` for every ledger entry (idempotent — only rows with
  `settled_outcome IS NULL` are touched) and rebuild balances. Winners are paid
  within the hour.
- `projections.py compute_prop_odds()` reads the ledger and pins the prop at
  100/0/50 with `settled: true` + `outcome` in `docs/projections.json`.
- `docs/sportsbook.html` derives closed/PUSH state from that JSON — no HTML
  edits required (the `settled:`/`odds:` flags in `BETS` are legacy fallback only).

Optional polish: update the bet's `desc` in `docs/sportsbook.html` with a
"SETTLED — ..." sentence for flavor. Never required for payout.

Note: many props settle **automatically** — `_AUTO_SETTLE_RULES` in
projections.py watches for resolved Kalshi markets, and overdue unsettled props
are flagged in a GitHub issue titled "Sportsbook: bets awaiting manual settlement".
Check that issue first; some of your work may already be done.

Also: remove the prop's tuple from `_PROP_DEFS` in projections.py if present
(dead weight once settled), and delete any `_AUTO_SETTLE_RULES` /
`_PROP_SCHEDULE` entries for it.

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
