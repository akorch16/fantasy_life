-- FL Draft App — Supabase schema
-- Paste into Supabase SQL Editor and click Run.
-- Then go to Database → Replication and enable Realtime for both tables.

create table if not exists draft_sessions (
  id                text primary key,
  status            text not null default 'setup',   -- setup | keeper | draft | complete
  draft_order       jsonb not null default '[]',     -- ["Korch","Wu",…]
  current_pick_idx  integer not null default 0,
  pick_started_at   timestamptz,                     -- when current timer began
  paused_at         timestamptz,                     -- non-null while paused
  paused            boolean not null default false,
  created_at        timestamptz default now()
);

create table if not exists draft_picks (
  id           serial primary key,
  session_id   text not null references draft_sessions(id) on delete cascade,
  player       text not null,       -- "Wu"
  category     text not null,       -- "NBA"
  team         text not null,       -- "Spurs"
  phase        text not null,       -- "keeper" | "draft"
  pick_number  integer not null,    -- 1-based overall pick counter
  made_at      timestamptz default now()
);

create index if not exists draft_picks_session on draft_picks(session_id);
create index if not exists draft_picks_player  on draft_picks(session_id, player);

-- Enable Realtime for both tables:
alter publication supabase_realtime add table draft_sessions;
alter publication supabase_realtime add table draft_picks;
