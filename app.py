"""
Fantasy Life 2026 — Live Leaderboard
Run: python app.py
Visit: http://localhost:5000
"""
import os, json, time
from flask import Flask, render_template, jsonify, request
from scoring import compute_all_scores, get_last_updated
from db import get_all_bonuses, add_bonus, delete_bonus, freeze_category, unfreeze_category

app = Flask(__name__)

# Cache scores for 5 minutes
_scores_cache = None
_scores_cache_time = 0
CACHE_TTL = 300  # seconds

def get_cached_scores():
    global _scores_cache, _scores_cache_time
    now = time.time()
    if _scores_cache is None or (now - _scores_cache_time) > CACHE_TTL:
        try:
            _scores_cache = compute_all_scores()
            _scores_cache_time = now
        except Exception as e:
            print(f'  ✗ compute_all_scores failed: {e}')
            if _scores_cache is None:
                _scores_cache = {'players': [], 'last_updated': ''}
    return _scores_cache

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

@app.route('/api/refresh', methods=['POST'])
def api_refresh():
    import threading
    from scrapers import refresh_all
    def run():
        global _scores_cache, _scores_cache_time
        result = refresh_all()
        # Invalidate cache after refresh
        _scores_cache = None
        _scores_cache_time = 0
    threading.Thread(target=run, daemon=True).start()
    return jsonify({'status': 'refresh started in background'})
