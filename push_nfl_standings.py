"""
One-off script to push 2025 NFL regular season final standings to Supabase.
Run with: SUPABASE_URL=... SUPABASE_KEY=... python push_nfl_standings.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db import save_standing

NFL_STANDINGS = {
    "standings": [
        # AFC East
        {"team": "New England Patriots",  "wins": 14, "losses": 3,  "win_pct": 0.824},
        {"team": "Buffalo Bills",         "wins": 12, "losses": 5,  "win_pct": 0.706},
        {"team": "Miami Dolphins",        "wins": 7,  "losses": 10, "win_pct": 0.412},
        {"team": "New York Jets",         "wins": 3,  "losses": 14, "win_pct": 0.176},
        # AFC North
        {"team": "Pittsburgh Steelers",   "wins": 10, "losses": 7,  "win_pct": 0.588},
        {"team": "Baltimore Ravens",      "wins": 8,  "losses": 9,  "win_pct": 0.471},
        {"team": "Cincinnati Bengals",    "wins": 6,  "losses": 11, "win_pct": 0.353},
        {"team": "Cleveland Browns",      "wins": 5,  "losses": 12, "win_pct": 0.294},
        # AFC South
        {"team": "Jacksonville Jaguars",  "wins": 13, "losses": 4,  "win_pct": 0.765},
        {"team": "Houston Texans",        "wins": 12, "losses": 5,  "win_pct": 0.706},
        {"team": "Indianapolis Colts",    "wins": 8,  "losses": 9,  "win_pct": 0.471},
        {"team": "Tennessee Titans",      "wins": 3,  "losses": 14, "win_pct": 0.176},
        # AFC West
        {"team": "Denver Broncos",        "wins": 14, "losses": 3,  "win_pct": 0.824},
        {"team": "Los Angeles Chargers",  "wins": 11, "losses": 6,  "win_pct": 0.647},
        {"team": "Kansas City Chiefs",    "wins": 6,  "losses": 11, "win_pct": 0.353},
        {"team": "Las Vegas Raiders",     "wins": 3,  "losses": 14, "win_pct": 0.176},
        # NFC East
        {"team": "Philadelphia Eagles",   "wins": 11, "losses": 6,  "win_pct": 0.647},
        {"team": "Dallas Cowboys",        "wins": 7,  "losses": 9,  "win_pct": 0.441},
        {"team": "Washington Commanders", "wins": 5,  "losses": 12, "win_pct": 0.294},
        {"team": "New York Giants",       "wins": 4,  "losses": 13, "win_pct": 0.235},
        # NFC North
        {"team": "Chicago Bears",         "wins": 11, "losses": 6,  "win_pct": 0.647},
        {"team": "Green Bay Packers",     "wins": 9,  "losses": 7,  "win_pct": 0.559},
        {"team": "Minnesota Vikings",     "wins": 9,  "losses": 8,  "win_pct": 0.529},
        {"team": "Detroit Lions",         "wins": 9,  "losses": 8,  "win_pct": 0.529},
        # NFC South
        {"team": "Carolina Panthers",     "wins": 8,  "losses": 9,  "win_pct": 0.471},
        {"team": "Tampa Bay Buccaneers",  "wins": 8,  "losses": 9,  "win_pct": 0.471},
        {"team": "Atlanta Falcons",       "wins": 8,  "losses": 9,  "win_pct": 0.471},
        {"team": "New Orleans Saints",    "wins": 6,  "losses": 11, "win_pct": 0.353},
        # NFC West
        {"team": "Seattle Seahawks",      "wins": 14, "losses": 3,  "win_pct": 0.824},
        {"team": "Los Angeles Rams",      "wins": 12, "losses": 5,  "win_pct": 0.706},
        {"team": "San Francisco 49ers",   "wins": 12, "losses": 5,  "win_pct": 0.706},
        {"team": "Arizona Cardinals",     "wins": 3,  "losses": 14, "win_pct": 0.176},
    ]
}

if __name__ == '__main__':
    ok = save_standing('NFL', NFL_STANDINGS, frozen=True)
    if ok:
        print('✓ NFL standings pushed to Supabase')
    else:
        print('✗ Failed to push NFL standings')
