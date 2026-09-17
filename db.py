"""
db.py — Supabase database layer for Fantasy Life 2026
Replaces local JSON file reads/writes with persistent Postgres via Supabase REST API.
"""

import os, json as _json, requests, threading
from datetime import datetime, timezone
from typing import Optional

_bonus_lock = threading.Lock()

SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')

if not SUPABASE_URL or not SUPABASE_KEY:
    print('WARNING: SUPABASE_URL or SUPABASE_KEY not set — db calls will fail gracefully')

_TIMEOUT = 10  # seconds

def _headers():
    return {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation',
    }

# ── Standings ────────────────────────────────────────────────────────────────

def get_last_updated() -> Optional[str]:
    """Return the most recent standings updated_at as a human-readable UTC string."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/standings',
            headers=_headers(),
            params={'select': 'updated_at', 'order': 'updated_at.desc', 'limit': '1'},
            timeout=_TIMEOUT,
        )
        rows = r.json()
        if rows:
            dt = datetime.fromisoformat(rows[0]['updated_at'].replace('Z', '+00:00'))
            return dt.strftime('%Y-%m-%d %H:%M UTC')
    except Exception:
        pass
    return None

def get_standing(category: str) -> dict:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return {}
    try:
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/standings',
            headers=_headers(),
            params={'category': f'eq.{category}', 'select': 'data,frozen'},
            timeout=_TIMEOUT,
        )
        rows = r.json()
        if not isinstance(rows, list) or not rows:
            print(f'  ✗ get_standing({category}): unexpected response: {rows}')
            return {}
        return rows[0]['data'] or {}
    except Exception as e:
        print(f'  ✗ get_standing({category}): {e}')
        return {}

def get_all_standings() -> dict:
    """Return {category: data} for all categories."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return {}
    try:
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/standings',
            headers=_headers(),
            params={'select': 'category,data,frozen'},
            timeout=_TIMEOUT,
        )
        return {row['category']: row['data'] for row in r.json()}
    except Exception as e:
        print(f'  ✗ get_all_standings(): {e}')
        return {}

def get_standing_updated_at(category: str) -> Optional[str]:
    """Return the updated_at ISO timestamp for a category, or None if unavailable."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/standings',
            headers=_headers(),
            params={'category': f'eq.{category}', 'select': 'updated_at'},
            timeout=_TIMEOUT,
        )
        rows = r.json()
        if rows and isinstance(rows, list):
            return rows[0].get('updated_at')
    except Exception:
        pass
    return None

def is_frozen(category: str) -> bool:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False
    try:
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/standings',
            headers=_headers(),
            params={'category': f'eq.{category}', 'select': 'frozen'},
            timeout=_TIMEOUT,
        )
        rows = r.json()
        if not isinstance(rows, list) or not rows:
            return False
        return rows[0].get('frozen', False)
    except Exception:
        return False

def save_standing(category: str, data: dict, frozen: bool = None) -> bool:
    """Upsert standings data for a category. Pass frozen=True/False to change freeze state."""
    payload = {
        'category': category,
        'data': data,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
    if frozen is not None:
        payload['frozen'] = frozen

    r = requests.post(
        f'{SUPABASE_URL}/rest/v1/standings',
        headers={**_headers(), 'Prefer': 'resolution=merge-duplicates,return=representation'},
        json=payload,
        timeout=_TIMEOUT,
    )
    ok = r.status_code in (200, 201)
    if ok:
        print(f'  ✓ {category} saved to Supabase')
    else:
        print(f'  ✗ {category} save failed: {r.status_code} {r.text}')
    return ok

def freeze_category(category: str) -> bool:
    """Mark a category as frozen so scrapers skip it."""
    r = requests.patch(
        f'{SUPABASE_URL}/rest/v1/standings',
        headers=_headers(),
        params={'category': f'eq.{category}'},
        json={'frozen': True, 'updated_at': datetime.now(timezone.utc).isoformat()},
        timeout=_TIMEOUT,
    )
    return r.status_code in (200, 204)

def unfreeze_category(category: str) -> bool:
    """Unfreeze a category so scrapers will update it again."""
    r = requests.patch(
        f'{SUPABASE_URL}/rest/v1/standings',
        headers=_headers(),
        params={'category': f'eq.{category}'},
        json={'frozen': False, 'updated_at': datetime.now(timezone.utc).isoformat()},
        timeout=_TIMEOUT,
    )
    return r.status_code in (200, 204)

# ── Bonuses ──────────────────────────────────────────────────────────────────

def get_all_bonuses() -> dict:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return {}
    try:
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/bonuses',
            headers=_headers(),
            params={'select': 'category,player,points,reason'},
            timeout=_TIMEOUT,
        )
        rows = r.json()
        if not isinstance(rows, list):
            print(f'  ✗ get_all_bonuses(): unexpected response: {rows}')
            return {}
        result = {}
        for row in rows:
            cat, player, pts = row['category'], row['player'], float(row['points'])
            if cat not in result:
                result[cat] = {}
            result[cat][player] = pts
        return result
    except Exception as e:
        print(f'  ✗ get_all_bonuses(): {e}')
        return {}

def add_bonus(category: str, player: str, points: float, reason: str = '') -> bool:
    """Set a player's bonus for a category (replaces existing value).

    Uses a process-level lock to prevent concurrent read-modify-write races
    when multiple requests arrive simultaneously. The lock is per-process;
    for multi-process deployments a database-level atomic update is preferred.
    """
    with _bonus_lock:
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/bonuses',
            headers=_headers(),
            params={'category': f'eq.{category}', 'player': f'eq.{player}', 'select': 'points'},
            timeout=_TIMEOUT,
        )
        rows = r.json() if r.ok else []
        existing = float(rows[0]['points']) if rows else 0.0
        new_total = round(existing + points, 2)

        payload = {
            'category': category,
            'player': player,
            'points': new_total,
            'reason': reason,
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
        r = requests.post(
            f'{SUPABASE_URL}/rest/v1/bonuses',
            headers={**_headers(), 'Prefer': 'resolution=merge-duplicates,return=representation'},
            json=payload,
            timeout=_TIMEOUT,
        )
        return r.status_code in (200, 201)

def delete_bonus(category: str, player: str) -> bool:
    """Remove a player's bonus for a category."""
    r = requests.delete(
        f'{SUPABASE_URL}/rest/v1/bonuses',
        headers=_headers(),
        params={'category': f'eq.{category}', 'player': f'eq.{player}'},
        timeout=_TIMEOUT,
    )
    return r.status_code in (200, 204)


# ── Buckley Bucks ─────────────────────────────────────────────────────────────

def get_account_by_email(email: str) -> Optional[dict]:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/bb_accounts',
            headers=_headers(),
            params={'email': f'eq.{email}', 'select': 'id,email,player_name,password_hash,balance'},
            timeout=_TIMEOUT,
        )
        rows = r.json()
        return rows[0] if isinstance(rows, list) and rows else None
    except Exception as e:
        print(f'  ✗ get_account_by_email: {e}')
        return None


def create_account(email: str, player_name: str, password_hash: str) -> Optional[str]:
    """Insert a new bb_account. Returns the new account id, or None on failure."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        r = requests.post(
            f'{SUPABASE_URL}/rest/v1/bb_accounts',
            headers=_headers(),
            json={'email': email, 'player_name': player_name, 'password_hash': password_hash},
            timeout=_TIMEOUT,
        )
        if r.status_code in (200, 201):
            rows = r.json()
            return rows[0]['id'] if rows else None
    except Exception as e:
        print(f'  ✗ create_account: {e}')
    return None


def get_balance(account_id: str) -> float:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return 0.0
    try:
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/bb_accounts',
            headers=_headers(),
            params={'id': f'eq.{account_id}', 'select': 'balance'},
            timeout=_TIMEOUT,
        )
        rows = r.json()
        return float(rows[0]['balance']) if rows else 0.0
    except Exception as e:
        print(f'  ✗ get_balance: {e}')
        return 0.0


def update_balance(account_id: str, delta: float) -> bool:
    """Atomically add delta (positive or negative) to an account's balance.
    Uses a read-then-patch with a process lock; safe for single-process deploys."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False
    with _bonus_lock:
        current = get_balance(account_id)
        new_bal = round(current + delta, 2)
        if new_bal < 0:
            return False  # insufficient funds
        r = requests.patch(
            f'{SUPABASE_URL}/rest/v1/bb_accounts',
            headers=_headers(),
            params={'id': f'eq.{account_id}'},
            json={'balance': new_bal},
            timeout=_TIMEOUT,
        )
        return r.status_code in (200, 204)


def get_open_markets() -> list:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []
    try:
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/bb_markets',
            headers=_headers(),
            params={'status': 'eq.open', 'select': 'id,type,subject,odds_pct', 'order': 'type.asc,subject.asc'},
            timeout=_TIMEOUT,
        )
        return r.json() if isinstance(r.json(), list) else []
    except Exception as e:
        print(f'  ✗ get_open_markets: {e}')
        return []


def upsert_market(market_type: str, subject: str, odds_pct: float) -> bool:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False
    try:
        r = requests.post(
            f'{SUPABASE_URL}/rest/v1/bb_markets',
            headers={**_headers(), 'Prefer': 'resolution=merge-duplicates,return=representation'},
            json={'type': market_type, 'subject': subject, 'odds_pct': round(odds_pct, 2)},
            timeout=_TIMEOUT,
        )
        return r.status_code in (200, 201)
    except Exception as e:
        print(f'  ✗ upsert_market: {e}')
        return False


def place_bet(account_id: str, market_id: str, stake: float, odds_pct: float, payout: float) -> Optional[str]:
    """Deduct stake from balance and insert bet row. Returns bet id or None."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    if not update_balance(account_id, -stake):
        return None  # insufficient funds or db error
    try:
        r = requests.post(
            f'{SUPABASE_URL}/rest/v1/bb_bets',
            headers=_headers(),
            json={
                'account_id': account_id,
                'market_id': market_id,
                'stake': stake,
                'odds_pct': odds_pct,
                'potential_payout': payout,
            },
            timeout=_TIMEOUT,
        )
        if r.status_code in (200, 201):
            rows = r.json()
            return rows[0]['id'] if rows else None
        # Refund on insert failure
        update_balance(account_id, stake)
    except Exception as e:
        print(f'  ✗ place_bet: {e}')
        update_balance(account_id, stake)
    return None


def get_bets_for_account(account_id: str) -> list:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []
    try:
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/bb_bets',
            headers=_headers(),
            params={
                'account_id': f'eq.{account_id}',
                'select': 'id,market_id,stake,odds_pct,potential_payout,status,placed_at,'
                          'bb_markets(type,subject)',
                'order': 'placed_at.desc',
            },
            timeout=_TIMEOUT,
        )
        return r.json() if isinstance(r.json(), list) else []
    except Exception as e:
        print(f'  ✗ get_bets_for_account: {e}')
        return []


def settle_market(market_id: str, result: bool) -> int:
    """Mark a market settled, then pay out winners or zero out losers.
    Returns number of bets processed."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return 0
    settled_at = datetime.now(timezone.utc).isoformat()
    requests.patch(
        f'{SUPABASE_URL}/rest/v1/bb_markets',
        headers=_headers(),
        params={'id': f'eq.{market_id}'},
        json={'status': 'settled', 'result': result, 'settled_at': settled_at},
        timeout=_TIMEOUT,
    )
    # Fetch all pending bets for this market
    try:
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/bb_bets',
            headers=_headers(),
            params={'market_id': f'eq.{market_id}', 'status': 'eq.pending',
                    'select': 'id,account_id,potential_payout'},
            timeout=_TIMEOUT,
        )
        bets = r.json() if isinstance(r.json(), list) else []
    except Exception:
        return 0

    count = 0
    for bet in bets:
        new_status = 'won' if result else 'lost'
        requests.patch(
            f'{SUPABASE_URL}/rest/v1/bb_bets',
            headers=_headers(),
            params={'id': f'eq.{bet["id"]}'},
            json={'status': new_status, 'settled_at': settled_at},
            timeout=_TIMEOUT,
        )
        if result:
            update_balance(bet['account_id'], float(bet['potential_payout']))
        count += 1
    return count


def settle_sb_bet(bet_id: str, outcome: str) -> int:
    """Settle all unsettled sb_bets rows for a sportsbook prop.
    outcome: 'yes' | 'no' | 'push'
    Writes a bet_settled event to sb_ledger for each bet (the source of truth
    for balance). sb_bets.settled_outcome is also patched as a read-model
    convenience column for the frontend, but nothing derives balance from it.
    Does NOT touch sb_players.balance directly — both call sites of this
    function (scoring.py, projections.py) already run recalculate_sb_balance()
    for every player immediately afterward, so there is exactly one function
    in the whole codebase that ever writes sb_players.balance.
    Returns number of bets processed."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return 0
    try:
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/sb_bets',
            headers=_headers(),
            params={
                'bet_id': f'eq.{bet_id}',
                'settled_outcome': 'is.null',
                'select': 'id,player,side,wager,potential_return',
            },
            timeout=_TIMEOUT,
        )
        bets = r.json() if isinstance(r.json(), list) else []
    except Exception as e:
        print(f'  ✗ settle_sb_bet fetch ({bet_id}): {e}')
        return 0

    count = 0
    for bet in bets:
        is_push = outcome == 'push'
        won = (not is_push) and bet['side'] == outcome
        settled_outcome = 'void' if is_push else ('won' if won else 'lost')
        delta = bet['wager'] if is_push else (bet['potential_return'] if won else 0)

        requests.patch(
            f'{SUPABASE_URL}/rest/v1/sb_bets',
            headers=_headers(),
            params={'id': f'eq.{bet["id"]}'},
            json={'settled_outcome': settled_outcome},
            timeout=_TIMEOUT,
        )
        try:
            requests.post(
                f'{SUPABASE_URL}/rest/v1/sb_ledger',
                headers=_headers(),
                json={
                    'player': bet['player'],
                    'event_type': 'bet_settled',
                    'bet_row_id': bet['id'],
                    'delta': delta,
                    'reason': settled_outcome,
                },
                timeout=_TIMEOUT,
            )
        except Exception as e:
            print(f'  ✗ settle_sb_bet ledger insert ({bet["player"]}, bet {bet["id"]}): {e}')
        count += 1

    if count:
        print(f'  ✓ Settled {count} BB bet(s) for {bet_id!r} (outcome={outcome})')
    return count


def _load_sb_adjustments() -> dict:
    """Historical only — used by _synthesize_ledger_events() (the one-time
    migration script) to reproduce what data/sb_adjustments.json used to
    encode. No longer read by the live balance path; every adjustment it held
    was backfilled into sb_ledger as a real balance_adjusted event."""
    path = os.path.join(os.path.dirname(__file__), 'data', 'sb_adjustments.json')
    try:
        with open(path) as f:
            return _json.load(f)
    except Exception:
        return {}


def recalculate_sb_balance(player: str, starting_bb: int = 1000) -> bool:
    """Recompute a player's BB balance by summing sb_ledger and update Supabase.
    sb_ledger is the sole source of truth for balance history now — this is
    the ONLY function in the codebase that writes sb_players.balance, and it
    uses the exact same formula place_bet() uses to check available balance.
    There is no longer a second, independent formula that has to agree with
    this one (the old settle_sb_bet incremental-patch path is gone).
    Returns True on success."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False
    try:
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/sb_ledger',
            headers=_headers(),
            params={'player': f'eq.{player}', 'select': 'delta'},
            timeout=_TIMEOUT,
        )
        deltas = r.json() if isinstance(r.json(), list) else []
    except Exception as e:
        print(f'  ✗ recalculate_sb_balance fetch ({player}): {e}')
        return False

    new_balance = starting_bb + sum(d['delta'] for d in deltas)

    try:
        requests.patch(
            f'{SUPABASE_URL}/rest/v1/sb_players',
            headers=_headers(),
            params={'name': f'eq.{player}'},
            json={'balance': new_balance, 'updated_at': datetime.now(timezone.utc).isoformat()},
            timeout=_TIMEOUT,
        )
        print(f'  ✓ {player} BB balance recalculated → {new_balance} BB '
              f'(from {len(deltas)} ledger events)')
        return True
    except Exception as e:
        print(f'  ✗ recalculate_sb_balance patch ({player}): {e}')
        return False


def get_all_markets() -> list:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []
    try:
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/bb_markets',
            headers=_headers(),
            params={'select': 'id,type,subject,odds_pct,status,result', 'order': 'type.asc,subject.asc'},
            timeout=_TIMEOUT,
        )
        return r.json() if isinstance(r.json(), list) else []
    except Exception as e:
        print(f'  ✗ get_all_markets: {e}')
        return []


def _synthesize_ledger_events() -> list:
    """Read sb_bets + sb_adjustments.json and produce the sb_ledger rows that
    would represent the same history if it had been recorded as a ledger from
    day one. Pure function of what's already in Supabase/the repo — makes no
    writes. Returns a list of dicts shaped like sb_ledger rows (minus id)."""
    events = []

    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/sb_bets',
        headers=_headers(),
        params={'select': 'id,player,wager,potential_return,settled_outcome,placed_at',
                'order': 'player.asc,placed_at.asc'},
        timeout=_TIMEOUT,
    )
    bets = r.json() if isinstance(r.json(), list) else []

    for bet in bets:
        events.append({
            'player': bet['player'],
            'event_type': 'bet_placed',
            'bet_row_id': bet['id'],
            'delta': -bet['wager'],
            'reason': None,
            'created_at': bet['placed_at'],
        })
        outcome = bet.get('settled_outcome')
        if outcome is not None:
            delta = {'won': bet['potential_return'], 'void': bet['wager'], 'lost': 0}.get(outcome)
            if delta is None:
                print(f'  ⚠ bet {bet["id"]} ({bet["player"]}) has unrecognized settled_outcome={outcome!r} — skipped')
                continue
            events.append({
                'player': bet['player'],
                'event_type': 'bet_settled',
                'bet_row_id': bet['id'],
                'delta': delta,
                'reason': outcome,
                # Settlement doesn't carry its own timestamp in sb_bets today — placed_at
                # is the best available ordering proxy. Real settlement timestamps start
                # existing once settle_sb_bet itself writes to sb_ledger (Phase 3).
                'created_at': bet['placed_at'],
            })

    adjustments = _load_sb_adjustments()
    for player, amount in adjustments.items():
        if amount:
            events.append({
                'player': player,
                'event_type': 'balance_adjusted',
                'bet_row_id': None,
                'delta': amount,
                'reason': 'backfilled from data/sb_adjustments.json — original incident/reason not recorded',
                'created_at': '2026-01-01T00:00:00Z',
            })

    return events


def migrate_ledger(execute: bool = False) -> bool:
    """Phase 2: backfill sb_ledger from existing sb_bets + sb_adjustments.json.

    Default is a dry run — computes and prints a diff against live sb_players
    balances, writes nothing. Pass execute=True to actually insert the rows
    into sb_ledger. The default being "safe" rather than "the flag you might
    forget" is deliberate: --migrate-ledger alone can never mutate anything.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        print('  ✗ migrate_ledger: SUPABASE_URL/SUPABASE_KEY not set')
        return False

    events = _synthesize_ledger_events()

    computed = {}
    for e in events:
        computed[e['player']] = computed.get(e['player'], 1000) + e['delta']

    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/sb_players',
        headers=_headers(),
        params={'select': 'name,balance', 'order': 'name.asc'},
        timeout=_TIMEOUT,
    )
    live = {row['name']: row['balance'] for row in (r.json() if isinstance(r.json(), list) else [])}

    print(f'{"player":<10} {"live balance":>12} {"ledger fold":>12} {"match":>7}')
    all_match = True
    for player in sorted(live.keys() | computed.keys()):
        live_bal = live.get(player)
        fold_bal = computed.get(player, 1000)  # no events at all → correct fold is the starting balance, not "unknown"
        ok = live_bal == fold_bal
        all_match = all_match and ok
        print(f'{player:<10} {str(live_bal):>12} {str(fold_bal):>12} {"✓" if ok else "✗ MISMATCH":>7}')

    print(f'\n{len(events)} ledger events synthesized from sb_bets + sb_adjustments.json.')

    if not all_match:
        print('  ✗ Mismatch(es) found — do not proceed to --execute until every player matches.')
        return False

    print('  ✓ All players match. Safe to backfill for real.')

    if not execute:
        print('  (dry run — nothing written. Re-run with --migrate-ledger --execute to insert.)')
        return True

    r = requests.post(
        f'{SUPABASE_URL}/rest/v1/sb_ledger',
        headers=_headers(),
        json=events,
        timeout=_TIMEOUT * 3,
    )
    if r.status_code >= 400:
        print(f'  ✗ Insert failed: {r.status_code} {r.text}')
        return False
    print(f'  ✓ Inserted {len(events)} ledger rows.')
    return True


if __name__ == '__main__':
    import sys

    if '--migrate-ledger' in sys.argv:
        migrate_ledger(execute='--execute' in sys.argv)

    elif '--dump-sb' in sys.argv:
        print('=== sb_players ===')
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/sb_players',
            headers=_headers(),
            params={'select': 'name,balance,updated_at', 'order': 'name.asc'},
            timeout=_TIMEOUT,
        )
        for row in (r.json() if isinstance(r.json(), list) else []):
            print(row)
        print()
        print('=== sb_bets ===')
        r = requests.get(
            f'{SUPABASE_URL}/rest/v1/sb_bets',
            headers=_headers(),
            params={'select': '*', 'order': 'player.asc,placed_at.asc'},
            timeout=_TIMEOUT,
        )
        for row in (r.json() if isinstance(r.json(), list) else []):
            print(row)

    elif '--repair-korch' in sys.argv:
        # One-time repair: insert Korch's 7 bets that were deleted by sbResetPlayer.
        # potential_return values derived from Jamzee's bets (same event, same odds window):
        #   NBA YES was 47% → Korch's NO effective odds = 53% → PR = round(100*100/53) = 189
        #   NHL YES was 42% → Korch's YES effective odds = 42% → PR = round(100*100/42) = 238
        #   Tennis: total PR across all 7 confirmed = 1427 BB → tennis = 1427 - 1258 = 169
        # After insert: recalc gives 1000 - 800 + 189 (NBA win) = 389 BB.
        placed = '2026-06-01T00:00:00Z'
        bets = [
            {'player': 'Korch', 'bet_id': 'pts-mitchell-v-todd',               'side': 'yes', 'wager': 100, 'potential_return': 154, 'sport': 'Total Points', 'settled_outcome': None,    'placed_at': placed},
            {'player': 'Korch', 'bet_id': 'pts-buckley-v-theo',                'side': 'yes', 'wager': 100, 'potential_return': 125, 'sport': 'Total Points', 'settled_outcome': None,    'placed_at': placed},
            {'player': 'Korch', 'bet_id': 'pts-wu-v-korch',                    'side': 'no',  'wager': 200, 'potential_return': 377, 'sport': 'Total Points', 'settled_outcome': None,    'placed_at': placed},
            {'player': 'Korch', 'bet_id': 'stocks-fryar-avgo-v-mitchell-cvna', 'side': 'yes', 'wager': 100, 'potential_return': 175, 'sport': 'Stocks',        'settled_outcome': None,    'placed_at': placed},
            {'player': 'Korch', 'bet_id': 'nba-fin-wu-v-buckley',              'side': 'no',  'wager': 100, 'potential_return': 189, 'sport': 'NBA',           'settled_outcome': 'won',   'placed_at': placed},
            {'player': 'Korch', 'bet_id': 'nhl-fin-tim-v-jamzee',              'side': 'yes', 'wager': 100, 'potential_return': 238, 'sport': 'NHL',           'settled_outcome': 'lost',  'placed_at': placed},
            {'player': 'Korch', 'bet_id': 'rg-w-fryar-v-feder',               'side': 'no',  'wager': 100, 'potential_return': 169, 'sport': 'Tennis',        'settled_outcome': 'lost',  'placed_at': placed},
        ]
        r = requests.post(
            f'{SUPABASE_URL}/rest/v1/sb_bets',
            headers={**_headers(), 'Prefer': 'resolution=merge-duplicates'},
            json=bets,
            timeout=_TIMEOUT,
        )
        print(f'Repair Korch bets: status={r.status_code}')
        if r.status_code >= 400:
            print(r.text[:500])
