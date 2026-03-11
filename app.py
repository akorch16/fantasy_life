"""
Fantasy Life 2026 — Live Leaderboard
Run: python app.py
Visit: http://localhost:5000
"""

import json, os
from flask import Flask, render_template, jsonify, request
from scoring import compute_all_scores, get_last_updated

app = Flask(__name__)
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

# ── Auto-seed on cold start ───────────────────────────────────────────────────
def _needs_seeding():
    """Return True if any required data file is missing."""
    required = ['nfl', 'nba', 'mlb', 'nhl', 'ncaaf', 'ncaab',
                'tennis', 'golf', 'nascar', 'mls', 'stock', 'country', 'musician']
    for key in required:
        if not os.path.exists(os.path.join(DATA_DIR, f'{key}.json')):
            return True
    return False

def _auto_seed():
    """Seed demo data silently on startup if data is missing."""
    from scrapers import seed_demo_data
    print("⚠️  No data found — seeding demo data for cold start...")
    seed_demo_data()
    print("✅ Demo data seeded.")

if _needs_seeding():
    _auto_seed()

# ─────────────────────────────────────────────────────────────────────────────

def load_bonuses():
    path = os.path.join(DATA_DIR, 'bonuses.json')
    if not os.path.exists(path): return {}
    with open(path) as f: return json.load(f)

def save_bonuses(b):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, 'bonuses.json'), 'w') as f:
        json.dump(b, f, indent=2)

@app.route('/')
def index(): return render_template('index.html')

@app.route('/admin')
def admin(): return render_template('admin.html')

@app.route('/api/scores')
def api_scores(): return jsonify(compute_all_scores())

@app.route('/api/bonuses', methods=['GET'])
def api_bonuses_get(): return jsonify(load_bonuses())

@app.route('/api/bonuses', methods=['POST'])
def api_bonuses_post():
    d = request.json
    player, cat, pts = d.get('player'), d.get('category'), d.get('points')
    if not all([player, cat, pts is not None]): return jsonify({'error': 'Missing fields'}), 400
    b = load_bonuses()
    if cat not in b: b[cat] = {}
    b[cat][player] = round((b[cat].get(player, 0) or 0) + float(pts), 2)
    save_bonuses(b)
    return jsonify({'ok': True})

@app.route('/api/bonuses', methods=['DELETE'])
def api_bonuses_delete():
    d = request.json
    b = load_bonuses()
    cat, player = d.get('category'), d.get('player')
    if cat in b and player in b[cat]: del b[cat][player]
    save_bonuses(b)
    return jsonify({'ok': True})

@app.route('/api/refresh', methods=['POST'])
def api_refresh():
    from scrapers import refresh_all
    return jsonify(refresh_all())

if __name__ == '__main__':
    print("\n🏆 Fantasy Life 2026 — Starting server...")
    print("📍 http://localhost:5000\n")
    app.run(debug=True, port=5000)
