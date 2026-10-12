-- Sportsbook Buckley Bucks — place_bet hardening + idempotency key.
-- Run in Supabase SQL Editor. Safe to apply BEFORE or AFTER the matching
-- sportsbook.html deploy (the page falls back to the old signature on PGRST202,
-- and old pages keep working because p_request_id defaults to null).
--
-- Fixes (found by reading docs/sb-ledger-phase3.sql):
--   1. p_wager was never validated. A negative wager passes `v_available < p_wager`
--      and writes a bet_placed ledger row with delta = -p_wager, a POSITIVE number,
--      minting balance. Now rejected, and enforced again by a table CHECK.
--   2. p_side was unrestricted. Now 'yes' | 'no' only (function + CHECK).
--   3. p_potential_return was unbounded. Now must be >= wager and <= 100x wager
--      (the page quotes odds between 1% and 99%).
--   4. Retries were not deduplicated: unique(player, bet_id, placed_at) includes
--      placed_at, which defaults to now(), so a retry never collides. Added a
--      client-generated request id with unique(player, request_id).
--   5. SECURITY DEFINER function now pins search_path.
--
-- STILL CLIENT-TRUSTED (needs server-side odds and close times to fix):
--   - potential_return is only range-checked, not recomputed from the live price.
--   - closes_at is enforced in the browser, not here.
--   - p_player is unauthenticated (accepted for a 13-friend league).
--   - an unknown p_player is auto-created (db.py --test-place-bet-phase3 relies on it).
--
-- ── 0. AUDIT FIRST — all three should return zero rows ──────────────────────────
--   select * from sb_bets   where wager <= 0 or side not in ('yes','no') or potential_return < wager;
--   select * from sb_ledger where event_type = 'bet_placed' and delta >= 0;
--   select player, count(*) from sb_bets group by player, bet_id, side, wager
--     having count(*) > 1;   -- possible past double-submits (informational)
-- If the first two return rows, fix them with balance_adjusted ledger events
-- (sb_ledger is append-only) before step 1, or the VALIDATE in step 1 will fail.

-- ── 1. Constraints (NOT VALID, then VALIDATE, so existing rows can't block it) ──
alter table sb_bets add column if not exists request_id uuid;

alter table sb_bets drop constraint if exists sb_bets_wager_positive;
alter table sb_bets add  constraint sb_bets_wager_positive
  check (wager > 0) not valid;
alter table sb_bets validate constraint sb_bets_wager_positive;

alter table sb_bets drop constraint if exists sb_bets_side_valid;
alter table sb_bets add  constraint sb_bets_side_valid
  check (side in ('yes', 'no')) not valid;
alter table sb_bets validate constraint sb_bets_side_valid;

-- Partial unique index: legacy rows (request_id null) are unaffected.
create unique index if not exists sb_bets_player_request_uidx
  on sb_bets (player, request_id) where request_id is not null;

-- ── 2. Replace place_bet ────────────────────────────────────────────────────────
-- Drop the old 6-arg signature, otherwise it stays callable alongside the new one.
drop function if exists place_bet(text, text, text, integer, integer, text);

create or replace function place_bet(
  p_player           text,
  p_bet_id           text,
  p_side             text,
  p_wager            integer,
  p_potential_return integer,
  p_sport            text,
  p_request_id       uuid default null
) returns json
language plpgsql security definer
set search_path = public
as $$
declare
  v_available  integer;
  v_new_bet_id bigint;
  v_prior      record;
begin
  -- Input validation first: cheap, and nothing below may run on bad input.
  if p_wager is null or p_wager <= 0 or p_wager > 1000000 then
    return json_build_object('ok', false, 'error', 'Invalid wager');
  end if;
  if p_side is null or p_side not in ('yes', 'no') then
    return json_build_object('ok', false, 'error', 'Invalid side');
  end if;
  if p_potential_return is null
     or p_potential_return < p_wager
     or p_potential_return > p_wager::bigint * 100 then
    return json_build_object('ok', false, 'error', 'Invalid payout');
  end if;
  if p_bet_id is null or length(p_bet_id) = 0 or length(p_bet_id) > 100 then
    return json_build_object('ok', false, 'error', 'Invalid bet');
  end if;

  -- Per-player mutex: a second concurrent call for the same player blocks here
  -- until the first commits, so the idempotency check and the balance check
  -- below cannot race. (Balance itself is derived from sb_ledger, not this row.)
  perform 1 from sb_players where name = p_player for update;
  if not found then
    insert into sb_players (name, balance, updated_at) values (p_player, 1000, now());
    perform 1 from sb_players where name = p_player for update;
  end if;

  select 1000 + coalesce(sum(delta), 0) into v_available
  from sb_ledger
  where player = p_player;

  -- Idempotent retry: same request id means the client is re-sending an attempt
  -- whose response it never saw. Return the original outcome, insert nothing.
  if p_request_id is not null then
    select id, bet_id, side, wager into v_prior
    from sb_bets
    where player = p_player and request_id = p_request_id;
    if found then
      if v_prior.bet_id <> p_bet_id or v_prior.side <> p_side or v_prior.wager <> p_wager then
        return json_build_object('ok', false,
          'error', 'Request id was already used for a different bet',
          'available', v_available);
      end if;
      return json_build_object('ok', true, 'duplicate', true, 'available', v_available);
    end if;
  end if;

  if v_available < p_wager then
    return json_build_object('ok', false, 'error', 'Insufficient balance',
                             'available', v_available);
  end if;

  insert into sb_bets (player, bet_id, side, wager, potential_return, sport, request_id)
  values (p_player, p_bet_id, p_side, p_wager, p_potential_return, p_sport, p_request_id)
  on conflict (player, bet_id, placed_at) do nothing
  returning id into v_new_bet_id;

  if v_new_bet_id is null then
    return json_build_object('ok', false, 'error', 'Duplicate bet — try again',
                             'available', v_available);
  end if;

  insert into sb_ledger (player, event_type, bet_row_id, delta)
  values (p_player, 'bet_placed', v_new_bet_id, -p_wager);

  return json_build_object('ok', true, 'available', v_available - p_wager);
end;
$$;

grant execute on function place_bet(text, text, text, integer, integer, text, uuid)
  to anon, authenticated;
