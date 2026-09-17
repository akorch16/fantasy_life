-- Sportsbook Buckley Bucks — Phase 3: place_bet now derives from sb_ledger
-- Run in Supabase SQL Editor. Replaces the place_bet function only — no
-- table changes. Requires docs/sb-ledger-schema.sql to already be applied.
--
-- What changed from the original (docs/sb-schema.sql):
-- available balance used to be sb_players.balance minus "wagers placed after
-- the last nightly recalc" (a heuristic comparing placed_at to updated_at).
-- It's now simply 1000 + sum(sb_ledger.delta) for this player — the exact
-- same formula recalculate_sb_balance() uses, so there is only one formula
-- for "what is this player's balance" anywhere in the system.
--
-- The FOR UPDATE lock on sb_players stays, but changes role: it's no longer
-- locking the value being trusted, only using the row as a mutex so two
-- concurrent calls for the same player can't both read the ledger sum and
-- both pass the balance check before either one's insert becomes visible.
--
-- Note on RLS: sb_ledger has RLS enabled with no policies for anon/
-- authenticated (see sb-ledger-schema.sql). This function is SECURITY
-- DEFINER, so its INSERT into sb_ledger executes as the function's owner
-- (postgres, since that's who runs this in the SQL Editor) — a superuser,
-- which always bypasses RLS. That's what lets the browser's anon-key RPC
-- call still successfully write a ledger row through this validated path,
-- while a direct `supabase.from('sb_ledger').insert(...)` from the browser
-- console continues to be rejected by RLS. No policy change needed here.

create or replace function place_bet(
  p_player           text,
  p_bet_id           text,
  p_side             text,
  p_wager            integer,
  p_potential_return integer,
  p_sport            text
) returns json
language plpgsql security definer as $$
declare
  v_available  integer;
  v_new_bet_id bigint;
begin
  -- Lock player row purely as a mutex; its balance column is no longer read.
  perform 1 from sb_players where name = p_player for update;
  if not found then
    insert into sb_players (name, balance, updated_at) values (p_player, 1000, now());
  end if;

  select 1000 + coalesce(sum(delta), 0) into v_available
  from sb_ledger
  where player = p_player;

  if v_available < p_wager then
    return json_build_object(
      'ok',        false,
      'error',     'Insufficient balance',
      'available', v_available
    );
  end if;

  insert into sb_bets (player, bet_id, side, wager, potential_return, sport)
  values (p_player, p_bet_id, p_side, p_wager, p_potential_return, p_sport)
  on conflict (player, bet_id, placed_at) do nothing
  returning id into v_new_bet_id;

  if v_new_bet_id is null then
    -- Conflict on (player, bet_id, placed_at) — astronomically unlikely since
    -- placed_at defaults to now(), but if it ever happens, do not record a
    -- ledger event for a bet that was never actually inserted.
    return json_build_object(
      'ok',        false,
      'error',     'Duplicate bet — try again',
      'available', v_available
    );
  end if;

  insert into sb_ledger (player, event_type, bet_row_id, delta)
  values (p_player, 'bet_placed', v_new_bet_id, -p_wager);

  return json_build_object('ok', true, 'available', v_available - p_wager);
end;
$$;
