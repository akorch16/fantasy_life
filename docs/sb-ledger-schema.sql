-- Sportsbook Buckley Bucks — append-only ledger (Phase 1: additive, zero risk)
-- Run in Supabase SQL Editor. Does not touch sb_players or sb_bets.
--
-- Design note: this table is the single source of truth for balance history.
-- sb_players.balance remains a cached/materialized value going forward, but
-- once the migration is complete it will be written by exactly one function
-- (recalculate from this table), not by ad hoc UPDATEs from multiple places.

create table if not exists sb_ledger (
  id          bigserial primary key,
  player      text not null references sb_players(name),
  event_type  text not null check (event_type in ('bet_placed', 'bet_settled', 'balance_adjusted')),
  bet_row_id  bigint references sb_bets(id),
  delta       integer not null,
  reason      text,
  created_at  timestamptz not null default now()
);

create index if not exists sb_ledger_player_idx on sb_ledger(player);

-- Deliberately NOT "on delete cascade" on the player FK — see write-up.

-- Enforce append-only at the database level. A REVOKE on UPDATE/DELETE only
-- protects against roles that don't already have blanket privileges, and
-- daily.yml writes via the same key that would need write access to insert
-- in the first place — so REVOKE can't distinguish "insert" from "update"
-- for a single role. A trigger that unconditionally rejects the operation
-- works regardless of which role or key performs it.
create or replace function sb_ledger_reject_mutation()
returns trigger
language plpgsql as $$
begin
  raise exception 'sb_ledger is append-only: % is not permitted', TG_OP;
end;
$$;

create trigger sb_ledger_no_update
  before update on sb_ledger
  for each row execute function sb_ledger_reject_mutation();

create trigger sb_ledger_no_delete
  before delete on sb_ledger
  for each row execute function sb_ledger_reject_mutation();
