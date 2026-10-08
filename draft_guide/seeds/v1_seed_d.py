"""v1 seed (2026-10-08): ONE-TIME import of the first research pass into draft_guide/data/*.json. Kept for provenance — after v1, edit the JSON directly (re-running a seed overwrites manual edits). Absolute paths assume the Claude Code cloud checkout."""
import json
D = '/home/user/fantasy_life/draft_guide/data'
AS_OF = '2026-10-08'

def dump(cat, entries, note=None):
    with open(f'{D}/{cat}.json', 'w') as f:
        json.dump({"category": cat, "as_of": AS_OF, "note": note, "entries": entries}, f, indent=1, ensure_ascii=False)
    print(cat, len(entries))

# ---------------- Awards (Oscars 99th, Mar 2027): Kalshi exchange mids (A) ----------------
KS = "Kalshi {} (exchange mid-price, Actions-runner pull 2026-10-08)"
def aw(name, cat, film, p_nom, p_win, series, conf='A', notes=''):
    p_nom = max(p_nom, p_win)
    return {"name": name, "category": cat, "film": film, "p_nom": p_nom, "p_win": p_win, "odds": f"win {p_win*100:.1f}% / nom {p_nom*100:.0f}%",
            "source": KS.format(series), "confidence": conf, "as_of": AS_OF, "notes": notes}
A = "Best Actor"; AC = "Best Actress"; SA = "Best Supporting Actor"; SC = "Best Supporting Actress"
rows = [
 aw("John Malkovich", A, "Wild Horse Nine", .925, .395, "KXOSCARACTO/NOMACTO-27"),
 aw("Matt Damon", A, "The Odyssey", .93, .225, "KXOSCARACTO/NOMACTO-27"),
 aw("Andrew Scott", A, "Elsinore", .855, .195, "KXOSCARACTO/NOMACTO-27"),
 aw("Tom Cruise", A, "Digger", .48, .135, "KXOSCARACTO/NOMACTO-27"),
 aw("Robert Pattinson", A, "Primetime", .52, .045, "KXOSCARACTO/NOMACTO-27", notes="Kalshi also lists him in Supporting Actor (nom 25%, win 10.5%) — one film can only land one"),
 aw("Timothée Chalamet", A, "Dune: Part Three (Dec 2026)", .21, .035, "KXOSCARACTO/NOMACTO-27"),
 aw("Ryan Gosling", A, "Project Hail Mary", .44, .015, "KXOSCARACTO/NOMACTO-27"),
 aw("Anthony Ippolito", A, "?", .46, .02, "KXOSCARACTO/NOMACTO-27"),
 aw("John Turturro", A, "The Only Living Pickpocket in New York", .345, .01, "KXOSCARACTO/NOMACTO-27"),
 aw("Sebastian Stan", A, "Fjord", .195, .01, "KXOSCARACTO/NOMACTO-27"),
 aw("Pedro Pascal", A, "Behemoth!", .16, .005, "KXOSCARACTO/NOMACTO-27"),
 aw("Tom Holland", A, "Spider-Man: Brand New Day / The Odyssey", .02, .005, "KXOSCARACTO-27", notes="nomination price not seen; estimate"),
 aw("Julianne Moore", AC, "The Debut", .94, .675, "KXOSCARACTR/NOMACTR-27"),
 aw("Inde Navarrette", AC, "Obsession", .735, .19, "KXOSCARACTR/NOMACTR-27"),
 aw("Sandra Hüller", AC, "Rose", .69, .035, "KXOSCARACTR/NOMACTR-27"),
 aw("Olivia Wilde", AC, "The Invite", .61, .025, "KXOSCARACTR/NOMACTR-27"),
 aw("Renate Reinsve", AC, "Fjord", .395, .025, "KXOSCARACTR/NOMACTR-27"),
 aw("Anne Hathaway", AC, "The Odyssey (lead)", .05, .015, "KXOSCARACTR-27", notes="her main play is Supporting Actress (below); nomination price for lead not seen"),
 aw("Paul Giamatti", SA, "The Debut", .87, .28, "KXOSCARSUPACTO/NOMSUPACTO-27"),
 aw("Andrew Garfield", SA, "?", .69, .27, "KXOSCARSUPACTO/NOMSUPACTO-27"),
 aw("John Leguizamo", SA, "The Odyssey", .74, .165, "KXOSCARSUPACTO/NOMSUPACTO-27"),
 aw("Robert Pattinson", SA, "?", .25, .105, "KXOSCARSUPACTO/NOMSUPACTO-27"),
 aw("Sam Rockwell", SA, "?", .775, .085, "KXOSCARSUPACTO/NOMSUPACTO-27"),
 aw("Edward Norton", SA, "The Invite", .61, .035, "KXOSCARSUPACTO/NOMSUPACTO-27"),
 aw("Skyler Gisondo", SA, "?", .08, .025, "KXOSCARSUPACTO-27", notes="nomination price not seen; estimate"),
 aw("Tom Holland", SA, "?", .03, .005, "KXOSCARSUPACTO-27", notes="nomination price not seen; estimate"),
 aw("Anne Hathaway", SC, "The Odyssey", .92, .525, "KXOSCARSUPACTR/NOMSUPACTR-27", notes="near-lock; main risk is lead-vs-supporting placement"),
 aw("Penélope Cruz", SC, "?", .73, .185, "KXOSCARSUPACTR/NOMSUPACTR-27"),
 aw("Amanda Seyfried", SC, "?", .21, .125, "KXOSCARSUPACTR/NOMSUPACTR-27"),
 aw("Kate O'Flynn", SC, "Tender Loving Care", .30, .105, "KXOSCARSUPACTR/NOMSUPACTR-27"),
 aw("Samantha Morton", SC, "The Odyssey", .745, .08, "KXOSCARSUPACTR-27", notes="win price not seen; estimate"),
 aw("Tao Okamoto", SC, "All of a Sudden", .46, .01, "KXOSCARSUPACTR/NOMSUPACTR-27"),
 aw("Zendaya", SC, "Dune: Part Three / Spider-Man: BND (2026 releases)", .05, .01, "KXOSCARSUPACTR-27", notes="nomination price not seen; estimate"),
 aw("Mariana di Girolamo", SC, "Wild Horse Nine", .41, .01, "KXOSCARNOMSUPACTR-27"),
 aw("Sandra Hüller", SC, "?", .285, .055, "KXOSCARSUPACTR/NOMSUPACTR-27", notes="also lead in Best Actress above — counted in both markets"),
]
dump('Awards', rows, "99th Academy Awards (Mar 2027), films released in 2026. Win prices: Kalshi KXOSCAR*-27; nomination prices: Kalshi KXOSCARNOM*-27. Lead win 13 / supp win 9 / lead nom 4 / supp nom 2.5.")

# ---------------- Musician: Hot 100 baseline (2027) + Grammy EV from Kalshi ----------------
def grammy(big_wins, big_noms, bna=(0, 0), other_wins=0.0, other_noms=0.0):
    """big_wins: p(win) for each big-3 category (7 pts); big_noms: p(nom) in the same; bna=(p_nom,p_win) 3 pts win/1 nom;
    other_wins: expected # other Grammy wins (3 each); other_noms: expected # other noms that do not win (1 each)."""
    ev = 7 * sum(big_wins) + sum(max(n - w, 0) for n, w in zip(big_noms, big_wins))
    ev += 3 * bna[1] + max(bna[0] - bna[1], 0)
    ev += 3 * other_wins + other_noms
    return min(ev, 13.0)
def mus(name, mu, sd, detail, g_ev, conf='C', notes='', g_src="Kalshi KXGRAM*-69 prices (A) + estimates for other categories (C)", **kw):
    d = {"name": name, "detail": detail, "odds": f"Grammy EV {g_ev:.1f}", "mu": mu, "sd": sd, "grammy_ev": round(g_ev, 2),
         "confidence": conf, "source": f"2027 Hot 100 baseline = my estimate; Grammy: {g_src}", "as_of": AS_OF, "notes": notes}
    d.update(kw); return d
M = []
M.append(mus("Ella Langley", 12, 9, "'Choosin' Texas' 24 wks #1 in 2026 (record run); top-10 tail into 2027; 'Dandelion' album", grammy([.045, .35, .25], [.625, .915, .85], (.98, .655), 0.9, 2.0), notes="Grammy figures: BNA win 65.5%, ROTY nom 91.5%, SOTY nom 85% (Kalshi); ROTY/SOTY win shares are estimates"))
M.append(mus("Taylor Swift", 14, 10, "6 #1 weeks in 2026 (3 songs); 2027 album unannounced", grammy([.025, .15, .10], [.82, .885, .81], (0, 0), 0.5, 2.0), notes="Showgirl AOTY nom 82%, Fate of Ophelia ROTY nom 88.5% (Kalshi)"))
M.append(mus("Olivia Rodrigo", 10, 8, "2026 #1 'drop dead' (1 wk) + top-10 songs; AOTY frontrunner album", grammy([.475, 0, .20], [.95, 0, .91], (0, 0), 0.8, 2.2), notes="AOTY win 47.5% (Kalshi): the market favourite"))
M.append(mus("Olivia Dean", 9, 7, "'Man I Need' (2026 top 10, 43+ wks per Wikipedia); The Art of Loving", grammy([.155, .20, .30], [.895, .90, .91], (0, 0), 0.7, 1.3), notes="Best New Artist won in Feb 2026, so ineligible"))
M.append(mus("Bruno Mars", 10, 7, "'I Just Might' 3 wks #1 (Jan 2026); The Romantic", grammy([.01, .15, .06], [.88, .88, .51], (0, 0), 0.6, 1.9)))
M.append(mus("Rosalía", 2, 2, "Lux (Grammy-driven pick; small Hot 100 profile)", grammy([.21, 0, 0], [.75, 0, 0], (0, 0), 1.0, 2.0)))
M.append(mus("Raye", 3, 3, "'WHERE IS MY HUSBAND!' ROTY/SOTY nominee", grammy([.01, .08, .10], [.25, .79, .81], (0, 0), 0.4, 1.6)))
M.append(mus("Harry Styles", 9, 7, "'Aperture' 1 wk #1 (Feb 2026); 'Kiss All the Time. Disco, Occasionally'", grammy([.02, .03, .02], [.49, .49, .245], (0, 0), 0.3, 1.2)))
M.append(mus("Phoebe Bridgers", 0, 1, "Lost Weekend (AOTY nominee candidate)", grammy([.095, 0, 0], [.56, 0, 0], (0, 0), 0.4, 1.6)))
M.append(mus("Ariana Grande", 5, 5, "'hate that i made you love me' #1 (Jun 2026); SOTY nom 35%", grammy([0, 0, .03], [0, 0, .35], (0, 0), 0.3, 1.2)))
M.append(mus("Sienna Spiro", 1, 1.5, "Best New Artist candidate (nom 89.5%, win 26%)", grammy([0, 0, 0], [0, 0, 0], (.895, .26), 0.3, 0.7)))
M.append(mus("BTS", 9, 8, "Arirang (2026) #1 on the Billboard 200; 'Swim' #1 (Apr 2026); world tour", 2.6, notes="Grammy EV is an estimate", g_src="estimate (C)"))
M.append(mus("Drake", 14, 10, "Iceman / Maid of Honour / Habibti (May 2026): 9 top-10 songs in one week", 1.4, notes="2027 release unconfirmed; boycotts Grammys but PartyNextDoor collab was nominated", g_src="estimate (C)"))
M.append(mus("Morgan Wallen", 10, 8, "No new album found", 0.8, g_src="estimate (C)"))
M.append(mus("Sabrina Carpenter", 8, 7, "Man's Best Friend (Aug 2025) was last cycle; no successor found", 1.0, g_src="estimate (C)"))
M.append(mus("Bad Bunny", 6, 5, "Won AOTY (Feb 2026); acting in The Comebacker (Jul 30, 2027)", 1.1, g_src="estimate (C)"))
M.append(mus("Kendrick Lamar", 6, 5, "GNX cycle ended Feb 2026; nothing eligible found", 0.9, g_src="estimate (C)"))
M.append(mus("The Weeknd", 6, 5, "No info found", 0.5, g_src="estimate (C)"))
M.append(mus("Beyoncé", 4, 4, "No info found", 0.5, g_src="estimate (C)"))
M.append(mus("SZA", 4, 4, "Voice in CoComelon: The Movie (Feb 19, 2027) — film, not chart", 0.5, g_src="estimate (C)"))
M.append(mus("Lady Gaga", 3, 3, "No info found", 0.5, g_src="estimate (C)"))
M.append(mus("Justin Bieber", 4, 4, "No info found", 0.3, g_src="estimate (C)"))
M.append(mus("Billie Eilish", 4, 4, "No info found", 0.5, g_src="estimate (C)"))
M.append(mus("Doja Cat", 3, 3, "No info found", 0.3, g_src="estimate (C)"))
M.append(mus("Travis Scott", 4, 4, "No info found", 0.3, g_src="estimate (C)"))
M.append(mus("Tyler, the Creator", 3, 3, "No info found", 0.3, g_src="estimate (C)"))
M.append(mus("Post Malone", 4, 4, "Kalshi: 17% to have a #1 in 2026", 0.3, g_src="estimate (C)"))
M.append(mus("Tate McRae", 4, 4, "Kalshi: 16% to have a #1 in 2026", 0.3, g_src="estimate (C)"))
M.append(mus("Zach Bryan", 3, 3, "No info found", 0.3, g_src="estimate (C)"))
M.append(mus("Chappell Roan", 3, 3, "No info found", 0.3, g_src="estimate (C)"))
M.append(mus("Doechii", 2, 3, "No info found", 0.3, g_src="estimate (C)"))
dump('Musician', M, "Baseline = 2 x #1 weeks + top-10 song-weeks in 2027 (estimates; no 2027 album dates found). Grammy EV (Feb 2027 ceremony) from Kalshi where marked A; cap 13.")

# ---------------- Country (IMF Oct-2026 WEO publishes Oct 13; priors until then) ----------------
def ctry(name, mu, sd, p_top3, detail, c='C', notes='', f27=None):
    return {"name": name, "detail": detail, "odds": None, "mu": mu, "sd": sd, "p_top3": p_top3, "forecast_2027": f27, "confidence": c,
            "source": "prior from IMF Jul-2026 update + regional outlooks; NO country-level 2027 table retrieved (IMF API blocked) — replace with the Oct 13 WEO", "as_of": AS_OF, "notes": notes}
C = [
 ctry("South Sudan", 6, 14, .20, "Oil-pipeline dependent; 2026 printed 22%+ vs forecast ~4.5%", notes="Sources conflict on 2026 (46% vs 4%)"),
 ctry("Guyana", 4, 8, .12, "Oil ramp maturing; growth fading from 20%+ years"),
 ctry("Libya", 5, 9, .08, "Oil-output swings; conflict risk"),
 ctry("Sudan", 4, 9, .06, "Post-war rebound only with a ceasefire"),
 ctry("Syria", 5, 8, .10, "Post-conflict rebound from a tiny base; poor data"),
 ctry("Venezuela", 4, 9, .08, "Political transition / oil; IMF data often missing"),
 ctry("Niger", 6, 5, .10, "Oil pipeline; junta/security risk", c='B', notes="2026 = 6.7% (Forbes Africa, Apr 2026)"),
 ctry("Ethiopia", 6.5, 3, .05, "IMF projections not reported (debt restructuring) — an n/a forecast is a scoring risk", c='B'),
 ctry("Senegal", 6, 3.5, .06, "Hydrocarbons; hidden-debt program risk", c='B'),
 ctry("Rwanda", 7, 1.5, .05, "Stable; low forecast error", c='B'),
 ctry("India", 6.5, 0.8, .10, "IMF Jul 2026: FY27 6.4%, FY28 6.7% (fiscal-year basis)", c='A', f27=6.5),
 ctry("Tanzania", 6, 1.2, .04, "Stable"),
 ctry("Uganda", 6, 1.5, .04, "Oil start-up 2026-27"),
 ctry("Côte d'Ivoire", 6, 1.2, .04, "Stable"),
 ctry("Bhutan", 6, 2, .04, "Hydropower"),
 ctry("Mongolia", 4.5, 3, .03, "Mining"),
 ctry("Armenia", 4.5, 2.5, .02, ""),
 ctry("Ukraine", 3.5, 6, .04, "Rebound lottery if ceasefire holds"),
 ctry("Lebanon", 4, 6, .03, "Rebound lottery"),
 ctry("Gaza / West Bank", 4, 10, .04, "Rebound lottery; data quality poor"),
 ctry("Uzbekistan", 5.5, 1.2, .02, ""),
 ctry("Philippines", 5.5, 1.0, .02, ""),
 ctry("Vietnam", 6, 1.0, .03, ""),
 ctry("Bangladesh", 5, 1.5, .02, ""),
 ctry("China", 4.2, 0.8, .01, "IMF Jul 2026: 2027 = 4.2%", c='A', f27=4.2),
 ctry("United States", 2.2, 1.0, .0, "IMF Jul 2026: 2.2%", c='A', f27=2.2),
 ctry("Euro area", 1.2, 0.8, .0, "IMF Jul 2026: 1.2% (comparator)", c='A', f27=1.2),
 ctry("Spain", 2.0, 0.8, .0, "Strong large economy"),
 ctry("Norway", 1.7, 1.0, .0, ""),
 ctry("Argentina", 3.5, 4.5, .02, "Reform-driven; high uncertainty"),
 ctry("Brazil", 2.0, 1.5, .0, ""), ctry("Canada", 1.8, 0.7, .0, ""), ctry("Germany", 1.0, 0.9, .0, ""),
 ctry("France", 1.1, 0.7, .0, ""), ctry("Netherlands", 1.5, 0.8, .0, ""), ctry("Switzerland", 1.5, 0.6, .0, ""),
 ctry("Guinea", 6.5, 4, .06, "Simandou iron-ore ramp"),
]
dump('Country', C, "PROVISIONAL. The Oct 13, 2026 IMF WEO (2027 column) replaces all of this. Priors only; sd reflects forecast-vs-realised error class (fragile/commodity >> stable).")

# ---------------- Stock (calendar-2027 return; rank scoring) ----------------
def stk(name, mu, sd, detail, notes=''):
    return {"name": name, "detail": detail, "odds": None, "mu": mu, "sd": sd, "confidence": "C",
            "source": "my estimate: sector view + typical vol; no price data pulled (verify quotes before drafting)", "as_of": AS_OF, "notes": notes}
ST = [
 stk("NVDA (Long)", 15, 45, "mega-cap AI; ~$221 (Sep 1); beta ~1.7", "consensus target $300-345; Q4 FY27 earnings Feb"),
 stk("AMD (Long)", 18, 55, "MI400/Helios ramp 2H26-27"), stk("MU (Long)", 10, 60, "HBM4; memory-cycle peak risk"),
 stk("AVGO (Long)", 15, 42, "custom ASIC demand"), stk("SMCI (Long)", 10, 80, "high-variance AI servers"),
 stk("PLTR (Long)", 8, 60, "momentum; valuation risk"), stk("COIN (Long)", 15, 75, "BTC-cycle beta"), stk("MSTR (Long)", 10, 90, "levered BTC proxy"),
 stk("HOOD (Long)", 15, 65, "crypto/retail volumes"), stk("TSLA (Long)", 12, 60, "robotaxi/Optimus narrative"), stk("RKLB (Long)", 20, 80, "Neutron first launch"),
 stk("IONQ (Long)", 10, 100, "quantum lottery"), stk("OKLO (Long)", 15, 90, "nuclear/AI power milestones"), stk("CRWV (Long)", 15, 90, "neocloud; leverage"),
 stk("CRCL (Long)", 10, 80, "stablecoin; rate-cut sensitivity"), stk("INTC (Long)", 8, 55, "foundry / 14A news; +187% in 2026 already"),
 stk("UNH (Long)", 12, 35, "turnaround"), stk("TSLA (Short)", -5, 60, "squeeze risk"), stk("PLTR (Short)", -3, 60, "valuation short; painful if momentum persists"),
 stk("MSTR (Short)", 0, 90, "huge variance both ways"),
]
dump('Stock', ST, "Placeholder research: researchers could not retrieve live prices. Treat as a screening list, not a recommendation. 2026 league used Long/Short picks scored on calendar-year return.")
