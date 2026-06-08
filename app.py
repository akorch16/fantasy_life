"""
Fantasy Life 2026 — Live Leaderboard
Run: python app.py
Visit: http://localhost:5000
"""
import os, json, time, threading
import bcrypt
import stripe
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from scoring import compute_all_scores
from db import (get_all_bonuses, add_bonus, delete_bonus, freeze_category, unfreeze_category,
                get_last_updated, get_account_by_email, create_account, get_balance,
                update_balance, get_open_markets, upsert_market, place_bet,
                get_bets_for_account, settle_market, get_all_markets)
from draft_picks_2026 import PLAYERS

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-insecure-change-me')

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
    stripe_session_id = request.args.get('session_id', '')
    if not stripe_session_id.startswith('cs_'):
        return _cors(jsonify({'unlocked': False}))
    try:
        stripe_session = stripe.checkout.Session.retrieve(stripe_session_id)
        unlocked = stripe_session.payment_status == 'paid'
    except stripe.StripeError:
        unlocked = False
    return _cors(jsonify({'unlocked': unlocked}))


# ── Buckley Bucks sportsbook ─────────────────────────────────────────────────

def _bb_account():
    """Return the logged-in bb_account dict from session, or None."""
    bb = session.get('bb')
    if not bb:
        return None
    return bb


def _bb_required():
    """Return (account, None) or (None, redirect_response)."""
    bb = _bb_account()
    if not bb:
        return None, redirect(url_for('sportsbook_login'))
    return bb, None


@app.route('/sportsbook')
def sportsbook():
    bb = _bb_account()
    if not bb:
        return redirect(url_for('sportsbook_login'))
    markets = get_open_markets()
    balance = get_balance(bb['account_id'])
    bets = get_bets_for_account(bb['account_id'])
    return render_template('sportsbook.html',
                           account=bb, balance=balance,
                           markets=markets, bets=bets)


@app.route('/sportsbook/login', methods=['GET', 'POST'])
def sportsbook_login():
    error = None
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        acct = get_account_by_email(email)
        if acct and bcrypt.checkpw(password.encode(), acct['password_hash'].encode()):
            session['bb'] = {
                'account_id': acct['id'],
                'player_name': acct['player_name'],
                'email': acct['email'],
            }
            return redirect(url_for('sportsbook'))
        error = 'Invalid email or password.'
    return render_template('sportsbook.html', page='login', error=error)


@app.route('/sportsbook/register', methods=['GET', 'POST'])
def sportsbook_register():
    error = None
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        player_name = request.form.get('player_name') or ''
        password = request.form.get('password') or ''
        confirm = request.form.get('confirm') or ''

        if player_name not in PLAYERS:
            error = 'Select your name from the league roster.'
        elif not email or '@' not in email:
            error = 'Enter a valid email address.'
        elif len(password) < 6:
            error = 'Password must be at least 6 characters.'
        elif password != confirm:
            error = 'Passwords do not match.'
        elif get_account_by_email(email):
            error = 'An account with that email already exists.'
        else:
            pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            acct_id = create_account(email, player_name, pw_hash)
            if acct_id:
                session['bb'] = {
                    'account_id': acct_id,
                    'player_name': player_name,
                    'email': email,
                }
                return redirect(url_for('sportsbook'))
            error = 'Registration failed — try again.'
    return render_template('sportsbook.html', page='register', error=error, players=PLAYERS)


@app.route('/sportsbook/logout', methods=['POST'])
def sportsbook_logout():
    session.pop('bb', None)
    return redirect(url_for('sportsbook_login'))


@app.route('/api/bb/bet', methods=['POST'])
def api_bb_bet():
    bb, redir = _bb_required()
    if redir:
        return jsonify({'error': 'Not logged in'}), 401
    data = request.get_json() or {}
    market_id = data.get('market_id', '')
    try:
        stake = float(data.get('stake', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid stake'}), 400

    if stake < 10:
        return jsonify({'error': 'Minimum bet is 10 BB'}), 400

    balance = get_balance(bb['account_id'])
    if stake > balance:
        return jsonify({'error': f'Insufficient balance ({balance:.0f} BB)'}), 400

    # Look up market odds
    markets = get_open_markets()
    market = next((m for m in markets if m['id'] == market_id), None)
    if not market:
        return jsonify({'error': 'Market not found or closed'}), 404

    odds_pct = float(market['odds_pct'])
    if odds_pct <= 0:
        return jsonify({'error': 'Market has invalid odds'}), 400

    payout = round(stake * (100.0 / odds_pct), 2)
    bet_id = place_bet(bb['account_id'], market_id, stake, odds_pct, payout)
    if not bet_id:
        return jsonify({'error': 'Bet failed — check your balance'}), 500

    new_balance = get_balance(bb['account_id'])
    return jsonify({'ok': True, 'bet_id': bet_id, 'payout': payout, 'balance': new_balance})


@app.route('/api/bb/settle', methods=['POST'])
def api_bb_settle():
    if not _is_admin():
        return jsonify({'error': 'Unauthorized'}), 401

    scores_path = os.path.join(os.path.dirname(__file__), 'docs', 'scores.json')
    try:
        with open(scores_path) as f:
            scores = json.load(f)
    except Exception as e:
        return jsonify({'error': f'Could not read scores.json: {e}'}), 500

    players_sorted = sorted(scores.get('players', []),
                            key=lambda p: p.get('total', 0), reverse=True)
    if not players_sorted:
        return jsonify({'error': 'No player data in scores.json'}), 400

    winner = players_sorted[0]['name']
    top4 = {p['name'] for p in players_sorted[:4]}

    all_markets = get_all_markets()
    total_paid = 0
    results = []
    for m in all_markets:
        if m['status'] == 'settled':
            continue
        if m['type'] == 'win':
            hit = m['subject'] == winner
        elif m['type'] == 'top4':
            hit = m['subject'] in top4
        else:
            continue
        n = settle_market(m['id'], hit)
        total_paid += n
        results.append({'market': f"{m['type']}:{m['subject']}", 'result': hit, 'bets': n})

    return jsonify({'ok': True, 'winner': winner, 'top4': list(top4),
                    'markets_settled': len(results), 'bets_processed': total_paid,
                    'details': results})


@app.route('/api/bb/sync-markets', methods=['POST'])
def api_bb_sync_markets():
    if not _is_admin():
        return jsonify({'error': 'Unauthorized'}), 401

    proj_path = os.path.join(os.path.dirname(__file__), 'docs', 'projections.json')
    try:
        with open(proj_path) as f:
            proj = json.load(f)
    except Exception as e:
        return jsonify({'error': f'Could not read projections.json: {e}'}), 500

    synced = 0
    for p in proj.get('players', []):
        name = p.get('name', '')
        if not name:
            continue
        upsert_market('win', name, p.get('win_pct', 0))
        upsert_market('top4', name, p.get('top4_pct', 0))
        synced += 1

    return jsonify({'ok': True, 'players_synced': synced})
