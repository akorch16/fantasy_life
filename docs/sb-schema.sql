-- Sportsbook Buckley Bucks — Supabase schema
-- Run in Supabase SQL Editor.
-- Then go to Database → Replication and enable Realtime for both tables.

create table if not exists sb_players (
  name        text primary key,
  balance     integer not null default 1000,
  updated_at  timestamptz default now()
);

-- Pre-seed all 13 league members at 1,000 BB each
insert into sb_players (name) values
  ('Tim'),('Wu'),('Jens'),('Todd'),('Mitchell'),('Shep'),('Theo'),
  ('Feder'),('Fryar'),('Korch'),('Molmen'),('Jamzee'),('Buckley')
on conflict do nothing;

create table if not exists sb_bets (
  id               serial primary key,
  player           text not null references sb_players(name) on delete cascade,
  bet_id           text not null,          -- matches BETS[].id in sportsbook.html
  side             text not null,          -- 'yes' | 'no'
  wager            integer not null,
  potential_return integer not null,
  sport            text,
  settled_outcome  text,                   -- null | 'won' | 'lost'
  placed_at        timestamptz default now(),
  constraint sb_bets_unique unique (player, bet_id, placed_at)
);

create index if not exists sb_bets_player_idx on sb_bets(player);

-- Enable Realtime
alter publication supabase_realtime add table sb_players;
alter publication supabase_realtime add table sb_bets;

-- ── place_bet RPC — atomic balance check + bet insert ────────────────────────
-- Prevents double-spend: SELECT FOR UPDATE locks the player row so two concurrent
-- calls can't both pass the balance check for the same player.
-- Call via: sbClient.rpc('place_bet', { p_player, p_bet_id, p_side,
--                                        p_wager, p_potential_return, p_sport })
-- Returns: { ok: true, available: <new balance> }
--       or { ok: false, error: '...', available: <current balance> }
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
  v_balance       integer;
  v_recent_wagers integer;
  v_available     integer;
begin
  -- Lock player row — second concurrent call blocks here until first commits
  select balance into v_balance
  from sb_players
  where name = p_player
  for update;

  if not found then
    insert into sb_players (name, balance, updated_at)
    values (p_player, 1000, now());
    v_balance       := 1000;
    v_recent_wagers := 0;
  else
    -- Bets placed after the last nightly recalc are not yet deducted from balance;
    -- subtract them to get the true available amount.
    select coalesce(sum(wager), 0) into v_recent_wagers
    from sb_bets
    where player = p_player
      and placed_at > (select updated_at from sb_players where name = p_player)
      and settled_outcome is null;
  end if;

  v_available := v_balance - v_recent_wagers;

  if v_available < p_wager then
    return json_build_object(
      'ok',        false,
      'error',     'Insufficient balance',
      'available', v_available
    );
  end if;

  insert into sb_bets (player, bet_id, side, wager, potential_return, sport)
  values (p_player, p_bet_id, p_side, p_wager, p_potential_return, p_sport)
  on conflict (player, bet_id, placed_at) do nothing;

  return json_build_object('ok', true, 'available', v_available - p_wager);
end;
$$;
