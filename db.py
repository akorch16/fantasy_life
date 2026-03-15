"""
db.py — Supabase database layer for Fantasy Life 2026
Replaces local JSON file reads/writes with persistent Postgres via Supabase REST API.
"""

import os, json, requests
from datetime import datetime

SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')

if not SUPABASE_URL or not SUPABASE_KEY:
    print('WARNING: SUPABASE_URL or SUPABASE_KEY not set — db calls will fail gracefully')

def _headers():
    return {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation',
    }

# ── Standings ────────────────────────────────────────────────────────────────

def get_standing(category: str) -> dict:
    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/standings',
        headers=_headers(),
        params={'category': f'eq.{category}', 'select': 'data,frozen'},
    )
    rows = r.json()
    if not isinstance(rows, list) or not rows:
        print(f'  ✗ get_standing({category}): unexpected response: {rows}')
        return {}
    return rows[0]['data'] or {}

def get_all_standings() -> dict:
    """Return {category: data} for all categories."""
    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/standings',
        headers=_headers(),
        params={'select': 'category,data,frozen'},
    )
    return {row['category']: row['data'] for row in r.json()}

def is_frozen(category: str) -> bool:
    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/standings',
        headers=_headers(),
        params={'category': f'eq.{category}', 'select': 'frozen'},
    )
    rows = r.json()
    if not isinstance(rows, list) or not rows:
        return False
    return rows[0].get('frozen', False)

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
    )
    return r.status_code in (200, 204)

def unfreeze_category(category: str) -> bool:
    """Unfreeze a category so scrapers will update it again."""
    r = requests.patch(
        f'{SUPABASE_URL}/rest/v1/standings',
        headers=_headers(),
        params={'category': f'eq.{category}'},
        json={'frozen': False, 'updated_at': datetime.utcnow().isoformat()},
    )
    return r.status_code in (200, 204)

# ── Bonuses ──────────────────────────────────────────────────────────────────

def get_all_bonuses() -> dict:
    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/bonuses',
        headers=_headers(),
        params={'select': 'category,player,points,reason'},
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

def add_bonus(category: str, player: str, points: float, reason: str = '') -> bool:
    """Add points to a player's bonus for a category (accumulates)."""
    # Get existing first
    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/bonuses',
        headers=_headers(),
        params={'category': f'eq.{category}', 'player': f'eq.{player}', 'select': 'points'},
    )
    existing = float(r.json()[0]['points']) if r.json() else 0.0
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
    )
    return r.status_code in (200, 201)

def delete_bonus(category: str, player: str) -> bool:
    """Remove a player's bonus for a category."""
    r = requests.delete(
        f'{SUPABASE_URL}/rest/v1/bonuses',
        headers=_headers(),
        params={'category': f'eq.{category}', 'player': f'eq.{player}'},
    )
    return r.status_code in (200, 204)
