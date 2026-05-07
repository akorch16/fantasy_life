"""
Fantasy Life 2026 — Live Leaderboard
Run: python app.py
Visit: http://localhost:5000
"""
import os, json, time, threading
import stripe
from flask import Flask, render_template, jsonify, request
from scoring import compute_all_scores
from db import get_all_bonuses, add_bonus, delete_bonus, freeze_category, unfreeze_category, get_last_updated
from draft_picks_2026 import PLAYERS

app = Flask(__name__)

ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', '')
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
# GitHub Pages URL — used for Stripe success/cancel redirects
PAGES_URL = os.environ.get('PAGES_URL', 'http://localhost:5000')

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
else:
    print('WARNING: STRIPE_SECRET_KEY not set — payment endpoints will return 503.')
_refresh_lock = threading.Lock()

_VALID_CATEGORIES = {
    'NFL', 'NBA', 'MLB', 'NHL', 'NCAAF', 'NCAAB',
    'Tennis', 'Golf', 'NASCAR', 'MLS',
    'Actor', 'Actress', 'Musician', 'Country', 'Stock',
}

if not ADMIN_TOKEN:
    print('WARNING: ADMIN_TOKEN not set — admin endpoints are open to all requests. '
          'Set ADMIN_TOKEN in your environment before deploying.')

def _is_admin():
    if not ADMIN_TOKEN:
        return True  # dev/open mode when no token configured
    token = request.headers.get('X-Admin-Token', '') or request.args.get('token', '')
    return token == ADMIN_TOKEN

def _parse_points(raw) -> tuple[float, str | None]:
    """Return (pts, error_message). Error is None on success."""
    try:
        pts = float(raw)
    except (TypeError, ValueError, OverflowError):
        return 0.0, 'points must be a number'
    if not (-500 <= pts <= 500):
        return 0.0, 'points must be between -500 and 500'
    return pts, None

# Cache scores for 5 minutes
_scores_cache: dict = {}
_scores_cache_time = 0
CACHE_TTL = 300  # seconds

def get_cached_scores():
    global _scores_cache, _scores_cache_time
    now = time.time()
    if (now - _scores_cache_time) > CACHE_TTL:
        try:
            _scores_cache = compute_all_scores()
            _scores_cache_time = now
        except Exception as e:
            print(f'  ✗ compute_all_scores failed: {e}')
    return _scores_cache or {}

def _warmup():
    """Pre-warm Supabase connection and scores cache in background at startup."""
    try:
        get_cached_scores()
        print('  ✓ warmup complete')
    except Exception as e:
        print(f'  ✗ warmup failed: {e}')

threading.Thread(target=_warmup, daemon=True).start()

@app.route('/')
def index():
    scores = get_cached_scores()
    return render_template(
        'index.html',
        scores_json=json.dumps(scores.get('players', [])),
        last_updated=scores.get('last_updated', '')
    )

@app.route('/api/scores')
def api_scores():
    return jsonify(get_cached_scores())

@app.route('/admin')
def admin():
    return render_template('admin.html')

@app.route('/api/bonuses', methods=['GET'])
def api_bonuses_get():
    return jsonify(get_all_bonuses())

@app.route('/api/bonuses', methods=['POST'])
def api_bonuses_post():
    if not _is_admin():
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    if not data or not all(k in data for k in ('category', 'player', 'points')):
        return jsonify({'error': 'Missing required fields: category, player, points'}), 400
    if data['player'] not in PLAYERS:
        return jsonify({'error': f'Unknown player: {data["player"]}'}), 400
    if data['category'] not in _VALID_CATEGORIES:
        return jsonify({'error': f'Unknown category: {data["category"]}'}), 400
    pts, err = _parse_points(data['points'])
    if err:
        return jsonify({'error': err}), 400
    ok = add_bonus(data['category'], data['player'], pts)
    global _scores_cache, _scores_cache_time
    _scores_cache = {}
    _scores_cache_time = 0
    return jsonify({'ok': ok}), (200 if ok else 500)

@app.route('/api/bonuses', methods=['DELETE'])
def api_bonuses_delete():
    if not _is_admin():
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    if not data or not all(k in data for k in ('category', 'player')):
        return jsonify({'error': 'Missing required fields: category, player'}), 400
    if data['player'] not in PLAYERS:
        return jsonify({'error': f'Unknown player: {data["player"]}'}), 400
    if data['category'] not in _VALID_CATEGORIES:
        return jsonify({'error': f'Unknown category: {data["category"]}'}), 400
    ok = delete_bonus(data['category'], data['player'])
    global _scores_cache, _scores_cache_time
    _scores_cache = {}
    _scores_cache_time = 0
    return jsonify({'ok': ok}), (200 if ok else 500)

@app.route('/api/refresh', methods=['POST'])
def api_refresh():
    if not _is_admin():
        return jsonify({'error': 'Unauthorized'}), 401
    if not _refresh_lock.acquire(blocking=False):
        return jsonify({'status': 'refresh already in progress'}), 429
    from scrapers import refresh_all
    def run():
        global _scores_cache, _scores_cache_time
        try:
            refresh_all()
            _scores_cache = {}
            _scores_cache_time = 0
        finally:
            _refresh_lock.release()
    threading.Thread(target=run, daemon=True).start()
    return jsonify({'status': 'refresh started in background'})

@app.route('/api/freeze', methods=['POST'])
def api_freeze():
    if not _is_admin():
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    if not data or 'category' not in data:
        return jsonify({'error': 'Missing required field: category'}), 400
    if data['category'] not in _VALID_CATEGORIES:
        return jsonify({'error': f'Unknown category: {data["category"]}'}), 400
    ok = freeze_category(data['category'])
    return jsonify({'ok': ok}), (200 if ok else 500)

@app.route('/api/unfreeze', methods=['POST'])
def api_unfreeze():
    if not _is_admin():
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    if not data or 'category' not in data:
        return jsonify({'error': 'Missing required field: category'}), 400
    if data['category'] not in _VALID_CATEGORIES:
        return jsonify({'error': f'Unknown category: {data["category"]}'}), 400
    ok = unfreeze_category(data['category'])
    return jsonify({'ok': ok}), (200 if ok else 500)

# ── Stripe payments ───────────────────────────────────────────────────────────

_TODD_TIERS = {
    1: {'name': "Todd's Basic Unlock — See the number. Weep.",         'amount': 499},
    2: {'name': "Todd's Premium Unlock — Full category-by-category roast", 'amount': 999},
    3: {'name': "Todd's Enterprise Unlock — 30 min with Todd himself", 'amount': 2999},
}

def _cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return resp

@app.route('/api/create-checkout-session', methods=['POST', 'OPTIONS'])
def api_create_checkout_session():
    if request.method == 'OPTIONS':
        return _cors(jsonify({}))
    if not STRIPE_SECRET_KEY:
        return _cors(jsonify({'error': 'Payments not configured'})), 503
    data = request.get_json() or {}
    tier = int(data.get('tier', 1))
    product = _TODD_TIERS.get(tier, _TODD_TIERS[1])
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {'name': product['name']},
                    'unit_amount': product['amount'],
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f'{PAGES_URL}/index.html?session_id={{CHECKOUT_SESSION_ID}}',
            cancel_url=f'{PAGES_URL}/index.html',
        )
    except stripe.StripeError as e:
        return _cors(jsonify({'error': str(e)})), 502
    return _cors(jsonify({'url': session.url}))

@app.route('/api/check-unlock', methods=['GET', 'OPTIONS'])
def api_check_unlock():
    if request.method == 'OPTIONS':
        return _cors(jsonify({}))
    if not STRIPE_SECRET_KEY:
        return _cors(jsonify({'unlocked': False}))
    session_id = request.args.get('session_id', '')
    if not session_id.startswith('cs_'):
        return _cors(jsonify({'unlocked': False}))
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        unlocked = session.payment_status == 'paid'
    except stripe.StripeError:
        unlocked = False
    return _cors(jsonify({'unlocked': unlocked}))
