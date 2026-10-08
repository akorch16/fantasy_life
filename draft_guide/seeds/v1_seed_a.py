"""v1 seed (2026-10-08): ONE-TIME import of the first research pass into draft_guide/data/*.json. Kept for provenance — after v1, edit the JSON directly (re-running a seed overwrites manual edits). Absolute paths assume the Claude Code cloud checkout."""
import json, os
D = '/home/user/fantasy_life/draft_guide/data'
os.makedirs(D, exist_ok=True)
AS_OF = '2026-10-08'

def team(name, detail, odds, p, mu, sd, c, src, notes=''):
    return {"name": name, "detail": detail, "odds": odds, "p_champ": p, "mu": mu, "sd": sd,
            "confidence": c, "source": src, "as_of": AS_OF, "notes": notes}

def norm(entries, key='p_champ'):
    s = sum(e[key] or 0 for e in entries)
    for e in entries:
        if e[key]:
            e[key] = round(e[key] / s, 4)
    return entries

def dump(cat, entries, note=None):
    with open(f'{D}/{cat}.json', 'w') as f:
        json.dump({"category": cat, "as_of": AS_OF, "note": note, "entries": entries}, f, indent=1, ensure_ascii=False)
    print(cat, len(entries))

ESPN = "ESPN/ABC7 Super Bowl LXI board ~2026-10-05; prediction-market avg 2026-10-07 (defirate)"
# ---- NFL (2026 season in progress; records through week 4) ----
nfl = [
 team("Los Angeles Rams","2-2, NFC West","+650",0.106,0.66,0.09,"B",ESPN),
 team("Buffalo Bills","3-1, AFC East","+750",0.095,0.68,0.09,"B",ESPN,"lost to Patriots wk4"),
 team("Baltimore Ravens","3-1, AFC North","+850",0.085,0.67,0.09,"B",ESPN),
 team("San Francisco 49ers","4-0, NFC West","+850",0.085,0.68,0.09,"B",ESPN),
 team("Kansas City Chiefs","4-0, AFC West","+950",0.079,0.69,0.09,"B",ESPN),
 team("Seattle Seahawks","3-1, NFC West","+950",0.074,0.64,0.09,"B",ESPN,"defending Super Bowl champion"),
 team("Jacksonville Jaguars","3-1, AFC South","+1500",0.058,0.62,0.09,"B",ESPN,"books disagree (+1100 to +2200)"),
 team("Chicago Bears","3-1, NFC North","+1800",0.048,0.59,0.09,"B",ESPN),
 team("Denver Broncos","2-2, AFC West","+2000",0.048,0.60,0.09,"C","ESPN snippet approx"),
 team("Minnesota Vikings","4-0, NFC North","+2200",0.042,0.60,0.09,"B",ESPN),
 team("Philadelphia Eagles","2-2, NFC East","+2400",0.042,0.60,0.09,"B",ESPN),
 team("New England Patriots","2-2, AFC East","+2500",0.037,0.57,0.09,"B",ESPN,"beat Bills wk4"),
 team("Dallas Cowboys","2-2, NFC East","+2000 to +2800",0.032,0.55,0.09,"B","FanDuel ~10-03; Fox"),
 team("Detroit Lions","2-2, NFC North","+3500",0.026,0.57,0.09,"C","estimate"),
 team("Green Bay Packers","2-2, NFC North","+3500",0.026,0.57,0.09,"C","estimate"),
 team("Cleveland Browns","3-1, AFC North","+7500",0.011,0.50,0.09,"C","estimate"),
 team("Las Vegas Raiders","3-1, AFC West","+6500",0.013,0.48,0.09,"C","estimate"),
 team("Indianapolis Colts","2-2, AFC South","+6500",0.013,0.50,0.09,"C","estimate"),
 team("Cincinnati Bengals","2-2, AFC North","+6500",0.013,0.52,0.09,"C","estimate"),
 team("Pittsburgh Steelers","2-2, AFC North","+6500",0.013,0.52,0.09,"C","estimate"),
 team("Houston Texans","0-4, AFC South","+4500",0.013,0.42,0.09,"B",ESPN,"preseason +1800"),
 team("Los Angeles Chargers","0-4, AFC West","+10000",0.004,0.40,0.09,"B",ESPN,"preseason +1700"),
 team("New York Giants","3-1, NFC East","+15000 (stale?)",0.008,0.47,0.09,"C","Fox Sports ~10-06","price looks stale vs 3-1 record"),
 team("Atlanta Falcons","2-2, NFC South","+10000",0.006,0.47,0.09,"C","estimate"),
 team("Carolina Panthers","2-2, NFC South","+10000",0.006,0.46,0.09,"C","estimate"),
 team("Washington Commanders","1-3, NFC East","+15000",0.004,0.42,0.09,"C","estimate"),
 team("Arizona Cardinals","1-3, NFC West","+15000",0.004,0.40,0.09,"C","estimate"),
 team("New Orleans Saints","1-3, NFC South","+25000",0.002,0.38,0.09,"C","estimate"),
 team("New York Jets","1-3, AFC East","+25000",0.002,0.36,0.09,"C","estimate"),
 team("Miami Dolphins","0-4, AFC East","+50000",0.001,0.30,0.09,"C","estimate"),
 team("Tennessee Titans","0-4, AFC South","+50000",0.001,0.30,0.09,"C","estimate"),
 team("Tampa Bay Buccaneers","0-4, NFC South","+20000",0.003,0.40,0.09,"C","estimate"),
]
dump('NFL', norm(nfl), "2026 season in progress; records through week 4. p(champ) renormalised to sum 1. No round/conference/division odds found (ladder inferred).")

# ---- NCAAF (AP poll 10-04, CFP title odds) ----
AP = "AP poll 2026-10-04; DraftKings 10-04 via Fox/SI; Polymarket 10-06"
ncaaf = [
 team("Texas","AP #1, 4-0, SEC","+650",0.11,0.85,0.15,"B",AP),
 team("Georgia","AP #2, 5-0, SEC","+500",0.15,0.85,0.15,"B",AP,"at Alabama Oct 10"),
 team("Notre Dame","AP #3, 5-0, Ind","+550 to +600",0.12,0.82,0.15,"B",AP),
 team("Miami (FL)","AP #4, 5-0, ACC","+700",0.09,0.80,0.15,"B",AP),
 team("Ohio State","AP #5, 4-1, Big Ten","+425",0.15,0.80,0.15,"B",AP,"one loss; books' favourite"),
 team("Alabama","AP #6, 5-0, SEC","+900",0.08,0.74,0.15,"B",AP),
 team("Indiana","AP #7, 5-0, Big Ten","+1000",0.06,0.72,0.15,"C","older lists + estimate"),
 team("BYU","AP #8, 4-0, Big 12","+4000",0.02,0.66,0.16,"C","estimate"),
 team("Ole Miss","AP #9, 3-1, SEC","+5000",0.015,0.62,0.16,"C","estimate"),
 team("LSU","AP #10, 4-1, SEC","+5000",0.015,0.60,0.16,"C","estimate"),
 team("Texas Tech","AP #11, 5-0, Big 12","+2500",0.03,0.62,0.16,"C","older list"),
 team("Utah","AP #12, 4-0, Big 12","+8000",0.01,0.58,0.16,"C","estimate"),
 team("Oregon","AP #13, 3-1, Big Ten","+1800",0.04,0.62,0.16,"C","older lists"),
 team("Missouri","AP #14, 4-1, SEC","+10000",0.008,0.52,0.16,"C","estimate"),
 team("Tennessee","AP #15, 4-1, SEC","+12000",0.006,0.50,0.16,"C","estimate"),
 team("Florida","AP #16, 4-1, SEC","+15000",0.004,0.48,0.16,"C","estimate"),
 team("Mississippi State","AP #17, 4-1, SEC","+30000",0.002,0.44,0.16,"C","estimate"),
 team("Oklahoma State","AP #18, 3-1, Big 12","+30000",0.002,0.42,0.16,"C","estimate"),
 team("USC","AP #19, 5-1, Big Ten","+20000",0.003,0.42,0.16,"C","estimate"),
 team("Iowa","AP #20, 4-1, Big Ten","+30000",0.002,0.38,0.16,"C","estimate"),
 team("UCLA","AP #21, 4-0, Big Ten","+50000",0.001,0.36,0.16,"C","estimate"),
 team("Houston","AP #22, 4-1, Big 12","+50000",0.001,0.34,0.16,"C","estimate"),
 team("Boise State","AP #23, 4-1, MWC","+50000",0.001,0.34,0.16,"C","estimate"),
 team("SMU","AP #24, 4-1, ACC","+50000",0.001,0.32,0.16,"C","estimate"),
 team("Pittsburgh","AP #25, 5-0, ACC","+50000",0.001,0.32,0.16,"C","estimate"),
]
dump('NCAAF', ncaaf, "Only the top-5 DraftKings prices and Polymarket top-4 were seen; the rest are estimates. Title probs total <1 (field has other teams).")

# ---- NBA (2026-27) ----
FD = "FanDuel ~2026-10-07; Polymarket via Covers; BetMGM win totals"
BM = "BetMGM win total; title price estimated"
nba = [
 team("San Antonio Spurs","West; win total 59.5","+270",0.21,0.726,0.06,"B",FD),
 team("Oklahoma City Thunder","West; win total 62.5","+240",0.19,0.762,0.06,"B",FD),
 team("New York Knicks","East; win total 52.5","+1000",0.105,0.640,0.06,"B",FD,"2026 champion in this league's data"),
 team("Philadelphia 76ers","East; win total 50.5","+1000",0.10,0.616,0.06,"B",FD,"ESPN reports LeBron signing (unverified)"),
 team("Boston Celtics","East; win total 51.5","+1400",0.06,0.628,0.06,"B",FD),
 team("Cleveland Cavaliers","East; win total 47.5","+2200",0.035,0.579,0.06,"B","DraftKings 2026-06-14"),
 team("Detroit Pistons","East; win total 49.5","+2200",0.035,0.604,0.06,"B",FD),
 team("Denver Nuggets","West; win total 49.5","+2500",0.035,0.604,0.06,"B",FD),
 team("Los Angeles Lakers","West; win total 46.5","+3500",0.025,0.567,0.06,"B","DraftKings 2026-06-14"),
 team("Houston Rockets","West; win total 47.5","+5000",0.02,0.579,0.06,"B","DraftKings 2026-06-14"),
 team("Toronto Raptors","East; win total 45.5","+2200",0.02,0.555,0.06,"B",FD),
 team("Minnesota Timberwolves","West; win total 48.5",None,0.015,0.591,0.06,"C",BM),
 team("Miami Heat","East; win total 46.5",None,0.01,0.567,0.06,"C",BM),
 team("Orlando Magic","East; win total 43.5",None,0.01,0.530,0.06,"C",BM),
 team("Atlanta Hawks","East; win total 43.5",None,0.008,0.530,0.06,"C",BM),
 team("Indiana Pacers","East; win total 44.5",None,0.006,0.543,0.06,"C",BM),
 team("Portland Trail Blazers","West; win total 42.5",None,0.006,0.518,0.06,"C",BM),
 team("Golden State Warriors","West; win total 40.5",None,0.006,0.494,0.06,"C",BM),
 team("Phoenix Suns","West; win total 40.5",None,0.004,0.494,0.06,"C",BM),
 team("Charlotte Hornets","East; win total 39.5",None,0.004,0.482,0.06,"C",BM),
 team("Dallas Mavericks","West; win total 34.5",None,0.004,0.421,0.06,"C",BM),
 team("Utah Jazz","West; win total 37.5",None,0.002,0.457,0.06,"C",BM),
 team("Washington Wizards","East; win total 34.5",None,0.002,0.421,0.06,"C",BM),
 team("Los Angeles Clippers","West; win total 30.5",None,0.002,0.372,0.06,"C",BM),
 team("Milwaukee Bucks","East; win total 25.5",None,0.002,0.311,0.06,"C",BM),
 team("Memphis Grizzlies","West; win total 29.5",None,0.002,0.360,0.06,"C",BM),
 team("Chicago Bulls","East; win total 29.5",None,0.001,0.360,0.06,"C",BM),
 team("New Orleans Pelicans","West; win total 27.5",None,0.001,0.335,0.06,"C",BM),
 team("Brooklyn Nets","East; win total 24.5",None,0.001,0.299,0.06,"C",BM),
 team("Sacramento Kings","West; win total 21.5",None,0.001,0.262,0.06,"C",BM),
]
dump('NBA', norm(nba), "2026-27 season opens Oct 20. mu = BetMGM win total / 82 (unshrunk). Top-11 title prices from books/Polymarket; the rest estimated. Renormalised.")

# ---- NHL (2026-27) ----
KS = "Kalshi Cup market (~1 month old) normalised; points totals SportsBettingDime"
def nhl(n, d, odds, p, mu, notes=''):
    return team(n, d, odds, p, mu, 0.05, "B" if "pts" in notes else "C", KS, notes)
nhl_e = [
 nhl("Florida Panthers","East","+650 (FD/DK); Kalshi +733",0.111,0.655,"pts 107.5"),
 nhl("Colorado Avalanche","West","+750 (Covers); Kalshi +852",0.102,0.655,"pts 107.5"),
 nhl("Carolina Hurricanes","East","+640 (Covers); Kalshi +1011",0.083,0.662,"pts 108.5, dated; 2026 champion"),
 nhl("Edmonton Oilers","West","+900 (Covers); Kalshi +1233",0.069,0.637,"pts 104.5"),
 nhl("Vegas Golden Knights","West","+950 (Covers)",0.051,0.60,"est."),
 nhl("Tampa Bay Lightning","East","Kalshi +1718",0.051,0.60,"est."),
 nhl("Minnesota Wild","West","Kalshi +1718",0.051,0.613,"pts 100.5"),
 nhl("Washington Capitals","East","Kalshi +2122",0.042,0.56,"est."),
 nhl("Dallas Stars","West","Kalshi +2122",0.042,0.613,"pts 100.5"),
 nhl("San Jose Sharks","West","Kalshi +2122",0.042,0.576,"pts 94.5"),
 nhl("Montreal Canadiens","East","Kalshi +2757",0.032,0.601,"pts 98.5"),
 nhl("Buffalo Sabres","East","Kalshi +2757",0.032,0.588,"pts 96.5"),
 nhl("New Jersey Devils","East","Kalshi +2757",0.032,0.582,"pts 95.5"),
 nhl("Anaheim Ducks","West","Kalshi +3900",0.023,0.576,"pts 94.5"),
 nhl("Utah Mammoth","West","Kalshi +3900",0.023,0.57,"est."),
 nhl("Ottawa Senators","East","Kalshi +3900",0.023,0.576,"pts 94.5"),
 nhl("Toronto Maple Leafs","East","Kalshi +3900",0.023,0.57,"est."),
 nhl("Pittsburgh Penguins","East","Kalshi +4900",0.0185,0.546,"pts 89.5"),
 nhl("Columbus Blue Jackets","East","Kalshi +6567",0.0139,0.558,"pts 91.5"),
 nhl("New York Rangers","East","Kalshi +6567",0.0139,0.527,"pts 86.5"),
 nhl("Los Angeles Kings","West","Kalshi +6567",0.0139,0.582,"pts 95.5"),
 nhl("Philadelphia Flyers","East","Kalshi +6567",0.0139,0.570,"pts 93.5"),
 nhl("Seattle Kraken","West","Kalshi +9900",0.0093,0.52,"est."),
 nhl("New York Islanders","East","Kalshi +9900",0.0093,0.540,"pts 88.5"),
 nhl("St. Louis Blues","West","Kalshi +9900",0.0093,0.52,"est."),
 nhl("Chicago Blackhawks","West","Kalshi +9900",0.0093,0.485,"pts 79.5"),
 nhl("Calgary Flames","West","Kalshi +9900",0.0093,0.473,"pts 77.5"),
 nhl("Winnipeg Jets","West","Kalshi +9900",0.0093,0.54,"est."),
 nhl("Nashville Predators","West","Kalshi +9900",0.0093,0.521,"pts 85.5"),
 nhl("Vancouver Canucks","West","Kalshi +9900",0.0093,0.454,"pts 74.5 (one blog)"),
 nhl("Boston Bruins","East","Kalshi +9900",0.0093,0.540,"pts 88.5"),
 nhl("Detroit Red Wings","East","Kalshi +9900",0.0093,0.527,"pts 86.5"),
]
dump('NHL', norm(nhl_e), "mu = projected points / 164 (82-game basis; one source says the 2026-27 season is 84 games — unverified). Kalshi table ~1 month old.")

# ---- NCAAB (2026-27) ----
CBS = "CBS Sports title odds 2026-08-04"
def b(n, odds, p, mu, c, notes=''):
    return team(n, '', odds, p, mu, 0.08 if c == 'B' else 0.09, c, CBS if c == 'B' else 'estimate', notes)
ncaab = [
 b("Duke","+600",0.12,0.95,"B"), b("Florida","+600",0.12,0.96,"B","ESPN preseason #1"),
 b("UConn","+1300",0.06,0.88,"B"), b("Illinois","+1300",0.06,0.88,"B"),
 b("Michigan","+1600",0.05,0.86,"B","2026 champion"), b("Michigan State","+2200",0.04,0.84,"B"),
 b("Houston","+2500",0.035,0.84,"B"), b("Arizona","+2500",0.035,0.84,"B"),
 b("Kansas","+4000",0.02,0.78,"B"), b("Purdue","+6500",0.013,0.74,"B"),
 b("Kentucky",None,0.02,0.76,"C"), b("Louisville",None,0.015,0.72,"C"), b("Alabama",None,0.015,0.72,"C"),
 b("Texas Tech",None,0.015,0.72,"C"), b("Tennessee",None,0.015,0.72,"C"), b("Gonzaga",None,0.012,0.70,"C"),
 b("Iowa State",None,0.012,0.70,"C"), b("BYU",None,0.012,0.70,"C"), b("Arkansas",None,0.012,0.69,"C"),
 b("North Carolina",None,0.01,0.68,"C"), b("Auburn",None,0.01,0.68,"C"), b("St. John's",None,0.01,0.67,"C"),
 b("Vanderbilt",None,0.01,0.66,"C"), b("Wisconsin",None,0.008,0.65,"C"), b("Texas",None,0.008,0.65,"C"),
 b("Creighton",None,0.008,0.65,"C"), b("Baylor",None,0.008,0.64,"C"), b("Virginia",None,0.008,0.64,"C"),
 b("Missouri",None,0.006,0.62,"C"),
]
dump('NCAAB', ncaab, "AP preseason poll not yet released. Only 10 teams have a posted price (Aug 4); others estimated. Titles do not sum to 1 (full field is larger). UCLA not listed by source.")
