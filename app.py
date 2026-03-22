"""
Fantasy Life 2026 — Live Leaderboard
Run: python app.py
Visit: http://localhost:5000
"""

import os
from flask import Flask, render_template, jsonify, request
from scoring import compute_all_scores, get_last_updated
from db import get_all_bonuses, add_bonus, delete_bonus, freeze_category, unfreeze_category

app = Flask(__name__)

@app.route('/')
def index():
    import json
    from scoring import compute_all_scores, get_last_updated
    try:
        scores = compute_all_scores()
        scores_json = json.dumps(scores['players'])
        last_updated = scores.get('last_updated', '')
    except Exception as e:
        print(f'  ✗ compute_all_scores failed: {e}')
        scores_json = '[]'
        last_updated = ''
    return render_template(
        'index.html',
        scores_json=scores_json,
        last_updated=last_updated
    )

@app.route('/admin')
def admin(): return render_template('admin.html')

@app.route('/api/scores')
def api_scores(): return jsonify(compute_all_scores())

@app.route('/api/bonuses', methods=['GET'])
def api_bonuses_get(): return jsonify(get_all_bonuses())

@app.route('/api/bonuses', methods=['POST'])
def api_bonuses_post():
    d = request.json
    player = d.get('player')
    cat    = d.get('category')
    pts    = d.get('points')
    reason = d.get('reason', '')
    if not all([player, cat, pts is not None]):
        return jsonify({'error': 'Missing fields'}), 400
    ok = add_bonus(cat, player, float(pts), reason)
    return jsonify({'ok': ok})

@app.route('/api/bonuses', methods=['DELETE'])
def api_bonuses_delete():
    d = request.json
    ok = delete_bonus(d.get('category'), d.get('player'))
    return jsonify({'ok': ok})

@app.route('/api/refresh', methods=['POST'])
def api_refresh():
    from scrapers import refresh_all
    return jsonify(refresh_all())

@app.route('/api/freeze', methods=['POST'])
def api_freeze():
    d = request.json
    category = d.get('category')
    frozen   = d.get('frozen', True)
    if not category:
        return jsonify({'error': 'Missing category'}), 400
    ok = freeze_category(category) if frozen else unfreeze_category(category)
    return jsonify({'ok': ok, 'category': category, 'frozen': frozen})

if __name__ == '__main__':
    print('\n🏆 Fantasy Life 2026 — Starting server...')
    print('📍 http://localhost:5000\n')
    app.run(debug=True, port=5000)
