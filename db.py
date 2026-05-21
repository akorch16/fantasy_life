"""
db.py — Supabase database layer for Fantasy Life 2026
Replaces local JSON file reads/writes with persistent Postgres via Supabase REST API.
"""

import os, requests, threading
from datetime import datetime
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
        'updated_at': datetime.utcnow().isoformat(),
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
        json={'frozen': True, 'updated_at': datetime.utcnow().isoformat()},
        timeout=_TIMEOUT,
    )
    return r.status_code in (200, 204)

def unfreeze_category(category: str) -> bool:
    """Unfreeze a category so scrapers will update it again."""
    r = requests.patch(
        f'{SUPABASE_URL}/rest/v1/standings',
        headers=_headers(),
        params={'category': f'eq.{category}'},
        json={'frozen': False, 'updated_at': datetime.utcnow().isoformat()},
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
            'updated_at': datetime.utcnow().isoformat(),
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
    settled_at = datetime.utcnow().isoformat()
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
