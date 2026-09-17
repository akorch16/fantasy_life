-- Sportsbook Buckley Bucks — lock down direct anon/authenticated writes to
-- sb_players and sb_bets. Run in Supabase SQL Editor.
--
-- Neither table has ever had RLS enabled — access has been governed purely
-- by whatever default table-level grants exist, which is how the browser's
-- public anon key has been able to write directly to both (sportsbook.html
-- upserts sb_players on identity switch, and sb_bets on every bet placement,
-- completely bypassing the place_bet RPC's balance check and row lock).
--
-- This does NOT lock reads: the leaderboard, balance display, and Realtime
-- subscriptions in sportsbook.html all read sb_players/sb_bets directly with
-- the anon key and must keep working. Only INSERT/UPDATE/DELETE are closed
-- for anon/authenticated — no policy for those means no access, same pattern
-- as sb_ledger.
--
-- Unaffected by this change:
--   - db.py / GitHub Actions (service_role bypasses RLS entirely)
--   - place_bet RPC (SECURITY DEFINER — runs as its owner, a superuser,
--     which also bypasses RLS)

alter table sb_players enable row level security;
alter table sb_bets    enable row level security;

create policy sb_players_public_read on sb_players
  for select to anon, authenticated
  using (true);

create policy sb_bets_public_read on sb_bets
  for select to anon, authenticated
  using (true);

-- Deliberately no insert/update/delete policies for anon/authenticated on
-- either table.
