"""v1 seed (2026-10-08): ONE-TIME import of the first research pass into draft_guide/data/*.json. Kept for provenance — after v1, edit the JSON directly (re-running a seed overwrites manual edits). Absolute paths assume the Claude Code cloud checkout."""
import json, math, os
D = '/home/user/fantasy_life/draft_guide/data'
AS_OF = '2026-10-08'

def load(cat):
    return json.load(open(f'{D}/{cat}.json'))

def dump(cat, entries, note=None):
    with open(f'{D}/{cat}.json', 'w') as f:
        json.dump({"category": cat, "as_of": AS_OF, "note": note, "entries": entries}, f, indent=1, ensure_ascii=False)
    print(cat, len(entries))

def ent(name, detail, odds, mu, sd, c, src, notes='', **kw):
    d = {"name": name, "detail": detail, "odds": odds, "mu": mu, "sd": sd, "confidence": c, "source": src, "as_of": AS_OF, "notes": notes}
    d.update(kw)
    return d

# ---------- overlay real Kalshi exchange mid-prices (confidence A) on team title odds ----------
def overlay(cat, kalshi, market, finals=None, final_market='', field_mass=0.0):
    doc = load(cat)
    es = doc['entries']
    def find(key, taken):
        kl = key.lower()
        exact = [e for e in es if e['name'].lower() == kl and id(e) not in taken]
        if exact: return exact[0]
        cand = [e for e in es if kl in e['name'].lower() and id(e) not in taken]
        return sorted(cand, key=lambda e: len(e['name']))[0] if cand else None
    taken, unmatched = set(), []
    for k, p in kalshi.items():
        e = find(k, taken)
        if e: taken.add(id(e)); e['_k'] = p
        else: unmatched.append(k)
    sum_named = sum(e['_k'] for e in es if '_k' in e)
    others = [e for e in es if '_k' not in e]
    rest = max(1.0 - field_mass - sum_named, 0.02)
    s_other = sum(e.get('p_champ') or 0 for e in others) or 1
    for e in es:
        if '_k' in e:
            e['p_champ'] = e.pop('_k')
            e['odds'] = f"Kalshi {e['p_champ']*100:.1f}%"
            e['source'] = f"{market} exchange mid-price, Actions-runner pull 2026-10-08"
            e['confidence'] = 'A'
        else:
            e['p_champ'] = round(e['p_champ'] / s_other * rest, 4)
            if e.get('confidence') == 'B':
                e['confidence'] = 'C'
                e['notes'] = (e.get('notes') or '') + ' | price superseded by Kalshi field; p rescaled'
    if finals:
        ft = set(); fu = []
        for k, p in finals.items():
            e = find(k, ft)
            if e: ft.add(id(e)); e['p_final'] = p; e['source'] = (e.get('source') or '') + f"; p(final)={final_market} Kalshi mid"
            else: fu.append(k)
        print(cat, 'unmatched final keys:', fu)
    print(cat, 'unmatched kalshi names:', unmatched, 'sum_named', round(sum_named, 3), 'rest', round(rest, 3))
    dump(cat, es, doc.get('note'))

overlay('NFL', {"Rams": .115, "Bills": .105, "49ers": .095, "Chiefs": .095, "Seahawks": .085, "Ravens": .075, "Jaguars": .065,
                "Bears": .045, "Vikings": .035, "Broncos": .035, "Cowboys": .035, "Bengals": .035, "Eagles": .025, "Patriots": .025},
        "Kalshi KXSB-27 (Super Bowl LXI)",
        finals={"Bills": .195, "Chiefs": .175, "Ravens": .155, "Jaguars": .125, "Bengals": .075, "Patriots": .065, "Broncos": .065, "Texans": .035, "Browns": .025,
                "Rams": .195, "49ers": .175, "Seahawks": .145, "Bears": .095, "Vikings": .085, "Cowboys": .085, "Lions": .055, "Eagles": .045, "Falcons": .035},
        final_market="KXNFLAFCCHAMP/KXNFLNFCCHAMP-27")
overlay('NBA', {"San Antonio": .215, "Oklahoma City": .215, "Philadelphia": .125, "New York": .085, "Minnesota": .065, "Miami": .065,
                "Boston": .045, "Lakers": .035, "Toronto": .025, "Denver": .025, "Cleveland": .025, "Orlando": .015, "Indiana": .015, "Houston": .015},
        "Kalshi KXNBA-27 (2027 NBA champion)",
        finals={"Philadelphia": .235, "New York": .205, "Boston": .125, "Miami": .105, "Toronto": .075, "Cleveland": .07, "Detroit": .06, "Indiana": .05, "Orlando": .025,
                "Oklahoma City": .345, "San Antonio": .325, "Minnesota": .09, "Lakers": .065, "Denver": .055, "Houston": .035, "Golden State": .025, "Utah": .015, "Portland": .015},
        final_market="KXNBAEAST/KXNBAWEST-27")
overlay('NHL', {"Colorado": .125, "Florida": .105, "Carolina": .095, "Edmonton": .085, "Vegas": .075, "Minnesota": .065, "Washington": .055,
                "Tampa": .055, "Dallas": .055, "San Jose": .045, "Montreal": .045, "New Jersey": .035, "Anaheim": .035, "Utah": .03},
        "Kalshi KXNHL-27 (2027 Stanley Cup)",
        finals={"Florida": .18, "Carolina": .165, "Washington": .135, "Tampa": .125, "New Jersey": .065, "Montreal": .055, "Buffalo": .055, "Rangers": .045, "Toronto": .035,
                "Colorado": .195, "Edmonton": .165, "Vegas": .125, "Dallas": .115, "San Jose": .11, "Minnesota": .10, "Utah": .085, "Anaheim": .045, "Kings": .035},
        final_market="KXNHLEAST/KXNHLWEST-27")
overlay('NCAAF', {"Ohio State": .165, "Georgia": .155, "Texas": .135, "Notre Dame": .115, "Miami": .105, "Alabama": .095, "Indiana": .075,
                  "Oregon": .045, "LSU": .045, "Ole Miss": .025, "Texas Tech": .015, "Florida": .015, "Mississippi State": .005},
        "Kalshi KXNCAAF-27 (national title)", field_mass=0.04)

# ---------- MLB: our own 2026 standings (A) + early-model title probabilities (C) ----------
mlb_raw = [  # name, win_pct (league standings 2026-10-08), p_champ estimate
 ("Milwaukee Brewers", .6358, .08), ("Los Angeles Dodgers", .6173, .15), ("Tampa Bay Rays", .6049, .055), ("Atlanta Braves", .5802, .065),
 ("New York Yankees", .5776, .08), ("San Diego Padres", .5617, .05), ("Chicago Cubs", .5494, .05), ("Philadelphia Phillies", .5432, .05),
 ("Boston Red Sox", .5370, .045), ("Arizona Diamondbacks", .5309, .03), ("Cleveland Guardians", .5247, .025), ("Chicago White Sox", .5185, .02),
 ("Pittsburgh Pirates", .5062, .03), ("Houston Astros", .5000, .025), ("Texas Rangers", .4938, .025), ("Miami Marlins", .4938, .012),
 ("Baltimore Orioles", .4907, .03), ("Toronto Blue Jays", .4877, .03), ("Minnesota Twins", .4753, .01), ("Washington Nationals", .4753, .01),
 ("St. Louis Cardinals", .4753, .01), ("Detroit Tigers", .4691, .025), ("Seattle Mariners", .4691, .03), ("Cincinnati Reds", .4630, .015),
 ("New York Mets", .4568, .035), ("Kansas City Royals", .4259, .01), ("San Francisco Giants", .4012, .006), ("Athletics", .3951, .01),
 ("Los Angeles Angels", .3827, .005), ("Colorado Rockies", .3580, .002)]
s = sum(p for _, _, p in mlb_raw)
mlb = []
for n, wp, p in mlb_raw:
    w = round(wp * 162)
    mlb.append(ent(n, f"2026: {w}-{162-w} (.{int(wp*10000):04d})", None, round(0.5 + 0.45 * (wp - 0.5), 4), 0.05, "C",
                   "2026 win% from league standings (A); title prob = model estimate — no 2027 World Series odds posted",
                   "2026 playoffs still in progress", p_champ=round(p / s, 4)))
dump('MLB', mlb, "No 2027 World Series futures exist yet. mu = 0.5 + 0.45*(2026 win% - 0.5). p(champ) are model estimates (C), normalised. Re-pull after the World Series (Oct 23-31).")

# ---------- MLS: league standings (A) + Kalshi 2026-Cup market as strength proxy ----------
mls_pts = {"Nashville SC": 60, "New England Revolution": 46, "Inter Miami CF": 46, "Charlotte FC": 43, "Chicago Fire FC": 42, "Philadelphia Union": 39,
 "Orlando City SC": 34, "New York Red Bulls": 33, "New York City FC": 33, "FC Cincinnati": 33, "D.C. United": 30, "Columbus Crew": 29, "Toronto FC": 29,
 "Atlanta United FC": 27, "CF Montréal": 24, "Vancouver Whitecaps FC": 50, "St. Louis City SC": 47, "FC Dallas": 47, "San Jose Earthquakes": 45,
 "Houston Dynamo FC": 44, "Los Angeles FC": 41, "Seattle Sounders FC": 38, "Colorado Rapids": 36, "LA Galaxy": 36, "Portland Timbers": 32,
 "Real Salt Lake": 32, "San Diego FC": 32, "Austin FC": 31, "Minnesota United FC": 29, "Sporting Kansas City": 21}
kal = {"Vancouver": .235, "Nashville": .18, "Inter Miami": .165, "St. Louis": .055, "Los Angeles FC": .055, "Dallas": .045, "Chicago": .045,
       "Philadelphia": .035, "New England": .035, "Houston": .035, "San Jose": .025, "Charlotte": .025, "Seattle": .015, "LA Galaxy": .015}
mls = []
for n, pts in mls_pts.items():
    kp = next((p for k, p in kal.items() if k.lower() in n.lower()), 0.005)
    p27 = 0.5 * kp + 0.5 / 30                       # mean-revert a year out
    mls.append(ent(n, f"2026: {pts} pts (as of 10-08; season ends Nov 7)", f"2026 Cup: Kalshi {kp*100:.1f}%", round(0.5 * (pts / 30) + 0.5 * 1.4, 3), 0.30, "C",
                   "2026 points (league standings, A) + Kalshi KXMLSCUP-26 price as strength proxy, shrunk 50% toward the field", "No 2027 MLS Cup market yet", p_champ=round(p27, 4)))
sm = sum(e['p_champ'] for e in mls)
for e in mls: e['p_champ'] = round(e['p_champ'] / sm, 4)
dump('MLS', mls, "mu = ppg proxy (half this year's points/30, half league-average 1.4). p(champ) = 2026 Kalshi price shrunk toward 1/30, normalised. Regular season ends Nov 7 -> refresh.")

# ---------- NASCAR: Kalshi 2026-title prices shrunk to a 2027 prior ----------
k26 = {"Kyle Larson": .42, "Denny Hamlin": .28, "Christopher Bell": .105, "Ryan Blaney": .055, "Joey Logano": .055, "Chase Briscoe": .035,
       "Shane van Gisbergen": .005, "William Byron": .005, "Tyler Reddick": .02, "Chase Elliott": .01, "Ty Gibbs": .005, "Alex Bowman": .005,
       "Daniel Suarez": .005, "Bubba Wallace": .005, "Ross Chastain": .005, "Austin Cindric": .005, "Carson Hocevar": .005, "Michael McDowell": .005,
       "Ryan Preece": .005, "Riley Herbst": .005, "Noah Gragson": .005, "AJ Allmendinger": .005, "Zane Smith": .005, "Todd Gilliland": .005}
chase = {"Kyle Larson": "2,318 pts, leads Chase after Las Vegas", "Denny Hamlin": "2,278 pts (2nd)", "Christopher Bell": "2,263 pts (3rd)", "Ryan Blaney": "2,238 pts (5th)",
         "Joey Logano": "2,247 pts (4th)", "Chase Briscoe": "2 wins incl. Las Vegas; 6th", "Tyler Reddick": "7th, -106"}
nas = []
for n, p26 in k26.items():
    p27 = 0.35 * p26 + 0.65 * (1 / 16)
    mu = min(0.95, max(0.25, 0.5 + 6 * (p27 - 1 / 16)))
    top5 = min(0.9, 2.6 * p27 + 0.15)
    nas.append(ent(n, chase.get(n, "2026 Cup Series"), f"2026 title: Kalshi {p26*100:.1f}%", round(mu, 3), 0.15, "C",
                   "Kalshi KXNASCARCUPSERIES-NCS26 (2026 champion) shrunk to a 2027 prior; Chase standings via search", "No 2027 title market yet",
                   p_champ=round(p27, 4), p_top5=round(top5, 3)))
sm = sum(e['p_champ'] for e in nas)
for e in nas: e['p_champ'] = round(e['p_champ'] / sm, 4)
dump('NASCAR', nas, "2027 baseline = regular-season standing (frozen before the Chase); bonus = final Chase standing 1st-5th. p(champ) = 0.35*2026 Kalshi + 0.65*(1/16); p(top5) = 2.6*p + 0.15.")

# ---------- Golf: real OWGR ranks (A) + major-win model ----------
owgr = ["Scottie Scheffler","Rory McIlroy","Matt Fitzpatrick","Cameron Young","Wyndham Clark","Russell Henley","Tommy Fleetwood","Chris Gotterup","Sam Burns",
 "Xander Schauffele","Collin Morikawa","J.J. Spaun","Viktor Hovland","Si Woo Kim","Jon Rahm","Aaron Rai","Justin Rose","Ludvig Åberg","Robert MacIntyre",
 "Jacob Bridgeman","Alex Noren","Ryan Fox","Ryan Gerard","Tyrrell Hatton","Ben Griffin","Hideki Matsuyama","Justin Thomas","Patrick Cantlay","Patrick Reed",
 "Kristoffer Reitan","Min Woo Lee","Tom Kim","Michael Brennan","Akshay Bhatia","Joaquin Niemann","Sepp Straka","Bryson DeChambeau","J.T. Poston","Shane Lowry",
 "Michael Thorbjornsen"]
notes = {"Scottie Scheffler": "2026: Masters runner-up, US Open T4. Masters 2027 +450 (DK/FD, Apr)", "Rory McIlroy": "Won 2026 Masters. +550-600 Masters 2027",
         "Cameron Young": "2026 Open runner-up", "Wyndham Clark": "Won 2026 US Open", "Aaron Rai": "Won 2026 PGA Championship", "Ryan Fox": "Won 2026 Open",
         "Sam Burns": "2026 US Open runner-up", "Jon Rahm": "LIV; 2026 PGA runner-up. +1200-1400 Masters 2027", "Bryson DeChambeau": "LIV. +1400 Masters 2027",
         "Xander Schauffele": "+1600 Masters 2027", "Ludvig Åberg": "Sweden; 2027 contender"}
share_w = [math.exp(-0.17 * i) for i in range(60)]
sw = sum(share_w)
golf = []
for i, n in enumerate(owgr, 1):
    share = 0.75 * share_w[i - 1] / sw + 0.25 / 60
    p_win = 1 - (1 - share) ** 4
    p_ru = 1 - (1 - share * 0.9) ** 4
    mu = max(0.2, 1 - 0.9 * (i - 1) / 60)
    golf.append(ent(n, f"OWGR {i} (2026-10-08)", None, round(mu, 3), 0.12, "C",
                    "OWGR rank from league standings pull (A); major-win probabilities = model (rank-weighted share of 4 majors)", notes.get(n, ''),
                    p_major_win=round(p_win, 3), p_major_ru=round(p_ru, 3)))
dump('Golf', golf, "mu = year-end-2027 OWGR strength (1 best), mean-reverting. p(>=1 major win) = 1-(1-share)^4 with share = 0.75*exp(-0.17*(rank-1))/norm + 0.25/60.")

# ---------- Tennis: ATP real ranks (A) + agent odds/probabilities ----------
T = [  # name, tour, rank, odds, p_win, p_ru, note
 ("Jannik Sinner","M",1,"+100 AO 2027 (pre-injury)",0.50,0.30,"Won Wimbledon 2026. Knee injury reported Oct 6 (unverified) — AO price likely longer"),
 ("Carlos Alcaraz","M",3,"+150 AO 2027",0.55,0.30,"Won AO 2026 over Djokovic; missed RG (wrist)"),
 ("Alexander Zverev","M",2,"+700 AO 2027",0.30,0.30,"Won RG and US Open 2026; Wimbledon runner-up"),
 ("Novak Djokovic","M",8,"+1600 AO 2027",0.10,0.15,"39; AO 2026 runner-up"),
 ("Ben Shelton","M",4,None,0.06,0.10,"US Open 2026 runner-up"),
 ("Felix Auger-Aliassime","M",5,None,0.03,0.04,""),
 ("Daniil Medvedev","M",6,None,0.03,0.04,""),
 ("Flavio Cobolli","M",7,None,0.02,0.04,"RG 2026 runner-up"),
 ("Alex de Minaur","M",9,None,0.02,0.03,""),
 ("Frances Tiafoe","M",10,None,0.01,0.02,""),
 ("Arthur Fils","M",11,None,0.02,0.03,""),
 ("Taylor Fritz","M",12,None,0.02,0.03,""),
 ("Elena Rybakina","W",1,"+300 AO 2027",0.40,0.30,"Won AO and US Open 2026"),
 ("Aryna Sabalenka","W",2,"+175 to +185 AO 2027",0.45,0.40,"Runner-up AO and US Open 2026 (both to Rybakina)"),
 ("Jessica Pegula","W",3,None,0.05,0.08,""),
 ("Coco Gauff","W",4,None,0.15,0.12,""),
 ("Mirra Andreeva","W",5,None,0.18,0.14,"Won RG 2026"),
 ("Linda Noskova","W",6,None,0.08,0.08,"Won Wimbledon 2026"),
 ("Elina Svitolina","W",7,None,0.03,0.04,""),
 ("Karolina Muchova","W",8,None,0.04,0.07,"Wimbledon 2026 runner-up"),
 ("Iga Swiatek","W",9,"+500 AO 2027",0.25,0.20,""),
 ("Marta Kostyuk","W",10,None,0.02,0.03,""),
 ("Amanda Anisimova","W",14,None,0.06,0.06,"rank sources conflict (11-18)"),
]
ten = []
for n, g, r, odds, pw, pr, note in T:
    rr = r + (0.5 if g == "W" else 0)             # Amendment 7.4: women's rank +0.5
    mu = max(0.2, 1 - 0.9 * (rr - 1) / 50)
    ten.append(ent(n, f"{'ATP' if g=='M' else 'WTA'} {r} ({AS_OF})", odds, round(mu, 3), 0.08, "B" if odds else "C",
                   "ATP rank from league standings pull (A) / WTA via Olympics.com Oct 5; AO odds VegasInsider/Johnnybet Oct 2026; probabilities = agent estimates",
                   note, p_slam_win=pw, p_slam_ru=pr, gender=g))
dump('Tennis', ten, "mu = year-end-2027 rank strength with the women's +0.5 rank adjustment; p(>=1 slam win/RU) are estimates. Re-check Sinner's injury.")
