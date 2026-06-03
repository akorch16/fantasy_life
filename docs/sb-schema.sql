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
  constraint sb_bets_unique unique (player, bet_id)
);

create index if not exists sb_bets_player_idx on sb_bets(player);

-- Enable Realtime
alter publication supabase_realtime add table sb_players;
alter publication supabase_realtime add table sb_bets;
